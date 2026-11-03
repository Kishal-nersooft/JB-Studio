import logging
from urllib.parse import urlencode

import psycopg2
from odoo import fields, http
from odoo.http import request
from odoo.exceptions import ValidationError
from werkzeug.exceptions import Forbidden, NotFound
from odoo.addons.payment.controllers.portal import PaymentPortal

_logger = logging.getLogger(__name__)


class PaymentIntentController(http.Controller):
    def _intent(self, intent_id, access_token):
        intent = request.env['bb.online.booking.intent'].sudo().search([
            ('id', '=', intent_id), ('website_id', '=', request.website.id),
            ('company_id', '=', request.website.company_id.id),
        ], limit=1)
        if not intent or not intent._check_token(access_token):
            raise NotFound()
        return intent.with_company(intent.company_id).with_context(allowed_company_ids=intent.company_id.ids)

    def start_checkout(self, **form):
        """Both old booking endpoints enter here; neither creates business records."""
        try:
            with request.env.cr.savepoint():
                branch = request.env['beauty.branch'].sudo().search([
                    ('id', '=', int(form.get('salon_id', 0))),
                    ('company_id', '=', request.website.company_id.id), ('active', '=', True),
                ], limit=1)
                if not branch:
                    raise ValidationError('Please choose a valid location.')
                Intent = request.env['bb.online.booking.intent'].sudo()
                # One uncharged checkout per browser: refresh updates the intent
                # rather than accumulating customer data and slot reservations.
                previous = request.session.get('bnb_checkout') or {}
                existing = Intent.browse(previous.get('id', 0)).exists()
                if existing and existing.website_id == request.website and existing._check_token(previous.get('token')):
                    if existing.transaction_ids:
                        if existing.state == 'paid' or all(tx.state in ('cancel', 'error') for tx in existing.transaction_ids):
                            request.session.pop('bnb_checkout', None)
                        else:
                            raise ValidationError('A payment has already started. Return to that checkout to check its status before booking again.')
                replace_id = existing.id if existing and existing._check_token(previous.get('token')) and not existing.transaction_ids else False
                vals = Intent.with_context(bnb_replace_intent_id=replace_id)._prepare(form, branch, request.website,
                    social=request.session.get('social_auth_user_data') or {})
                if replace_id:
                    existing.unlink()
                intent = Intent.create(vals)
                request.session['bnb_checkout'] = {'id': intent.id, 'token': intent.access_token}
                return request.make_json_response({'success': True,
                    'redirect_url': '/salon/secure-checkout/%s?%s' % (intent.id, urlencode({'access_token': intent.access_token}))})
        except psycopg2.OperationalError:
            raise
        except (ValidationError, ValueError, TypeError) as error:
            return request.make_json_response({'success': False, 'error': str(error)})
        except Exception:
            _logger.exception('Unable to start online checkout')
            return request.make_json_response({'success': False, 'error': 'Unable to start checkout. Please try again or contact the salon.'})

    def _providers(self, intent):
        # No contact is created: payer details are stored on the transaction.
        partner = intent.website_id.user_id.partner_id
        providers = request.env['payment.provider'].sudo()._get_compatible_providers(
            intent.company_id.id, partner.id, intent.amount, currency_id=intent.currency_id.id)
        # Live public checkouts must never expose a simulated payment method.
        if not request.env.user.has_group('base.group_system'):
            providers = providers.filtered(lambda p: p.state == 'enabled')
        providers = providers.filtered(lambda p: not p._is_tokenization_required())
        methods = request.env['payment.method'].sudo()._get_compatible_payment_methods(
            providers.ids, partner.id, currency_id=intent.currency_id.id)
        return partner, providers, methods

    @http.route('/salon/secure-checkout/<int:intent_id>', type='http', auth='public', website=True, sitemap=False)
    def checkout(self, intent_id, access_token=None, **kwargs):
        intent = self._intent(intent_id, access_token)
        if intent.transaction_ids:
            return request.redirect('/salon/checkout-result/%s?%s' % (intent.id, urlencode({'access_token': access_token})))
        if intent.expires_at <= fields.Datetime.now():
            return request.render('bnb_portal_appointment.checkout_result', {'intent': intent, 'status': 'expired'})
        partner, providers, methods = self._providers(intent)
        result_url = '/salon/checkout-result/%s?%s' % (intent.id, urlencode({'access_token': access_token}))
        transaction_url = '/salon/checkout-transaction/%s' % intent.id
        nab = providers.filtered(lambda p: p.code == 'nab_gateway')[:1]
        wallet = None
        if nab and (getattr(nab, 'nab_google_pay_enabled', False) or getattr(nab, 'nab_apple_pay_enabled', False)):
            wallet = {'provider_id': nab.id, 'card_method_id': request.env.ref('payment.payment_method_card').id,
                'access_token': access_token, 'transaction_route': transaction_url, 'landing_route': result_url,
                'amount': intent.amount, 'currency': intent.currency_id.name,
                'country': intent.company_id.country_id.code or 'AU', 'is_test': '1' if nab.state == 'test' else '0',
                'merchant_id': nab.nab_merchant_id or '', 'google_merchant_id': nab.nab_google_merchant_id or '',
                'google': '1' if nab.nab_google_pay_enabled else '0', 'apple': '1' if nab.nab_apple_pay_enabled else '0'}
        return request.render('bnb_portal_appointment.secure_checkout', {
            'intent': intent, 'amount': intent.amount, 'currency': intent.currency_id,
            'partner_id': partner.id, 'reference_prefix': intent.name, 'access_token': access_token,
            'providers_sudo': providers, 'payment_methods_sudo': methods.filtered(lambda m: m.code not in ('google_pay', 'apple_pay')),
            'tokens_sudo': request.env['payment.token'].browse(), 'availability_report': {},
            'show_tokenize_input_mapping': {p.id: False for p in providers},
            'transaction_route': transaction_url, 'landing_route': result_url, 'nab_wallet': wallet,
        })

    @http.route('/salon/checkout-transaction/<int:intent_id>', type='jsonrpc', auth='public', website=True)
    def transaction(self, intent_id, access_token=None, **kwargs):
        intent = self._intent(intent_id, access_token)
        intent._lock()
        if intent.expires_at <= fields.Datetime.now() or intent.state != 'draft':
            raise ValidationError('This checkout has expired or already completed. Please check its payment status.')
        # Reject replay rather than asking a provider to charge an existing
        # transaction twice. Its status remains accessible on the result page.
        if intent.transaction_ids:
            raise ValidationError('Payment has already started for this checkout. Please check its status.')
        intent._validate_slot()
        partner, providers, methods = self._providers(intent)
        try:
            provider = providers.filtered(lambda p: p.id == int(kwargs.get('provider_id', 0)))
            method = methods.filtered(lambda m: m.id == int(kwargs.get('payment_method_id', 0)))
        except (TypeError, ValueError):
            raise Forbidden()
        if not provider or not method or (method not in provider.payment_method_ids and method.primary_payment_method_id not in provider.payment_method_ids):
            raise Forbidden()
        if kwargs.get('flow') not in ('direct', 'redirect') or kwargs.get('token_id') or kwargs.get('tokenization_requested'):
            raise Forbidden()
        booking = intent.payload['booking']
        custom = {'bnb_booking_intent_id': intent.id}
        if 'nab_client_reference' in request.env['payment.transaction']._fields:
            custom['nab_client_reference'] = intent.name
        result_url = '/salon/checkout-result/%s?%s' % (intent.id, urlencode({'access_token': access_token}))
        tx = PaymentPortal()._create_transaction(
            provider_id=provider.id, payment_method_id=method.id, token_id=None,
            amount=intent.amount, currency_id=intent.currency_id.id, partner_id=partner.id,
            flow=kwargs['flow'], tokenization_requested=False, landing_route=result_url,
            reference_prefix=intent.name, custom_create_values=custom)
        # Core create copies values from partner_id; replace that snapshot
        # before any gateway request with the verified checkout form's payer.
        tx.write({'partner_name': booking['first_name'] + ' ' + booking['last_name'],
            'partner_email': booking['email'], 'partner_phone': booking['mobile_phone'],
            'partner_address': booking['billing_address'], 'partner_city': booking['city'],
            'partner_zip': booking['postcode'], 'partner_country_id': intent.company_id.country_id.id})
        return tx._get_processing_values()

    @http.route('/salon/checkout-result/<int:intent_id>', type='http', auth='public', website=True, sitemap=False)
    def result(self, intent_id, access_token=None, **kwargs):
        intent = self._intent(intent_id, access_token)
        tx = intent.transaction_ids[:1]
        if tx.state == 'done':
            try:
                with request.env.cr.savepoint():
                    tx._post_process()
            except psycopg2.OperationalError:
                raise
            except Exception:
                _logger.exception('Checkout post-processing deferred to recovery for %s', intent.name)
        status = 'paid' if intent.appointment_id else ('refunded' if intent.state == 'refunded' else 'review' if tx.state == 'done' else tx.state or 'draft')
        if status in ('cancel', 'error'):
            current = request.session.get('bnb_checkout') or {}
            if current.get('id') == intent.id:
                request.session.pop('bnb_checkout', None)
            intent.write({'state': 'expired'})
        return request.render('bnb_portal_appointment.checkout_result', {'intent': intent, 'status': status})
