# -*- coding: utf-8 -*-
import json
import logging

from psycopg2.errors import UniqueViolation

from odoo import fields
from odoo.http import request, route
from odoo.tools import config
from odoo.addons.portal.controllers import portal

from .booking_helpers import (
    _get_start_hour_from_timeslots,
    _compute_discount_from_code,
    _validate_booking_availability,
    _validate_booking_resource_availability,
    _get_service_resource_ids,
    _pick_available_beautician,
)

_logger = logging.getLogger(__name__)


class SalonPaymentController(portal.CustomerPortal):
    """Controller for salon booking payment integration - uses Odoo's payment.form like shop checkout"""

    @staticmethod
    def _allowed_company_ids():
        return request.env.companies.ids or [request.env.company.id]

    def _get_scoped_branch(self, branch_id):
        return request.env['beauty.branch'].sudo().search([
            ('id', '=', int(branch_id)),
            ('company_id', 'in', self._allowed_company_ids()),
            ('active', '=', True),
        ], limit=1)

    def _get_scoped_appointment(self, appointment_id):
        return request.env['salon.appointment'].sudo().search([
            ('id', '=', int(appointment_id)),
            ('company_id', 'in', self._allowed_company_ids()),
        ], limit=1)

    def _get_scoped_transaction(self, tx_id, appointment):
        tx = request.env['payment.transaction'].sudo().search([
            ('id', '=', int(tx_id)), ('company_id', '=', appointment.company_id.id),
            ('partner_id', '=', appointment.customer_id.id),
            ('currency_id', '=', appointment.company_id.currency_id.id),
        ], limit=1)
        reference = appointment.appointment_ref or ''
        return tx.filtered(lambda item: reference and (item.reference == reference or item.reference.startswith(reference + '-')))

    @route('/salon/create-booking-payment', type='http', auth='public', methods=['POST'], website=True)
    def create_booking_payment(self, **kwargs):
        from .payment_intent import PaymentIntentController
        return PaymentIntentController().start_checkout(**kwargs)

    @route(
        '/salon/checkout/<int:appointment_id>',
        type='http', auth='public', website=True, sitemap=False,
    )
    def salon_checkout(self, appointment_id, access_token=None, **kwargs):
        """
        Render the salon checkout page with Odoo's payment.form
        Same pattern as /shop/payment in website_sale
        """
        from odoo.addons.payment import utils as payment_utils

        appointment = self._get_scoped_appointment(appointment_id)
        if not appointment.exists():
            return request.redirect('/book-online')

        customer = appointment.customer_id
        if not customer:
            return request.redirect('/book-online')

        # Get payment record for amount
        payment_record = request.env['salon.appointment.payment'].sudo().search([
            ('appointment_id', '=', appointment.id),
            ('appointment_id.company_id', 'in', self._allowed_company_ids()),
        ], limit=1)

        amount = payment_record.payment_amount if payment_record else 0
        currency = appointment.branch_id.company_id.currency_id or request.env.company.currency_id
        company = appointment.branch_id.company_id or request.env.company

        access_token = access_token or kwargs.get('access_token')
        if not access_token or not payment_utils.check_access_token(access_token, customer.id, amount, currency.id):
            return request.redirect('/book-online')

        # Get compatible payment providers (same as shop checkout)
        availability_report = {}
        providers_sudo = request.env['payment.provider'].sudo()._get_compatible_providers(
            company.id,
            customer.id,
            amount,
            currency_id=currency.id,
            report=availability_report,
        )
        payment_methods_sudo = request.env['payment.method'].sudo()._get_compatible_payment_methods(
            providers_sudo.ids,
            customer.id,
            currency_id=currency.id,
            report=availability_report,
        )
        # Wallet methods are rendered by the custom NAB express buttons below.
        # Leaving them in payment.form shows duplicate radio rows that still use
        # the card inline-form flow, which cannot start Apple Pay / Google Pay.
        payment_methods_sudo = payment_methods_sudo.filtered(
            lambda method: method.code not in ('google_pay', 'apple_pay')
        )
        tokens_sudo = request.env['payment.token'].sudo()._get_available_tokens(
            providers_sudo.ids, customer.id
        )

        # Reference prefix for the transaction
        reference_prefix = payment_utils.singularize_reference_prefix(
            prefix=appointment.appointment_ref
        )

        # Build rendering context (same structure as shop checkout)
        show_tokenize_input_mapping = {}
        for provider_sudo in providers_sudo:
            show_tokenize_input = (
                provider_sudo.allow_tokenization
                and not provider_sudo._is_tokenization_required()
            )
            show_tokenize_input_mapping[provider_sudo.id] = show_tokenize_input

        # Get service details for summary
        service_lines = request.env['salon.appointment.service'].sudo().search([
            ('appointment_id', '=', appointment.id),
            ('appointment_id.company_id', 'in', self._allowed_company_ids()),
        ])

        # Calculate totals for summary display
        service_total = sum(line.total_price for line in service_lines) if service_lines else 0
        booking_fee = appointment.booking_fee or 0
        discount_amount = payment_record.discount_amount if payment_record else 0
        payment_option = payment_record.payment_option if payment_record else 'full'
        total_before_option = service_total + booking_fee - discount_amount
        remaining_balance = total_before_option - amount if payment_option == 'half' else 0

        # NAB wallet (Google Pay / Apple Pay) express buttons — only when NAB is a
        # compatible provider and has wallets enabled. Rendered separately from
        # payment.form (which handles Card). getattr guards keep this safe if the
        # payment_nab_gateway module is not installed.
        nab_wallet = None
        nab_provider = providers_sudo.filtered(lambda p: p.code == 'nab_gateway')[:1]
        if nab_provider and (getattr(nab_provider, 'nab_google_pay_enabled', False)
                             or getattr(nab_provider, 'nab_apple_pay_enabled', False)):
            nab_wallet = {
                'provider_id': nab_provider.id,
                'card_method_id': request.env.ref('payment.payment_method_card').id,
                'access_token': access_token,
                'transaction_route': f'/salon/payment/transaction/{appointment.id}',
                'landing_route': '/salon/payment/confirm',
                'amount': amount,
                'currency': currency.name,
                'country': company.country_id.code or 'AU',
                'is_test': '1' if nab_provider.state == 'test' else '0',
                'merchant_id': nab_provider.nab_merchant_id or '',
                # Google-issued Merchant ID, required by Google Pay in production
                # (sent as merchantInfo.merchantId by the wallet JS).
                'google_merchant_id': nab_provider.nab_google_merchant_id or '',
                'google': '1' if nab_provider.nab_google_pay_enabled else '0',
                'apple': '1' if nab_provider.nab_apple_pay_enabled else '0',
            }

        rendering_context = {
            'nab_wallet': nab_wallet,
            # Payment form context (required by payment.form template)
            'reference_prefix': reference_prefix,
            'amount': amount,
            'currency': currency,
            'partner_id': customer.id,
            'providers_sudo': providers_sudo,
            'payment_methods_sudo': payment_methods_sudo,
            'tokens_sudo': tokens_sudo,
            'availability_report': availability_report,
            'transaction_route': f'/salon/payment/transaction/{appointment.id}',
            'landing_route': '/salon/payment/confirm',
            'access_token': access_token,
            'show_tokenize_input_mapping': show_tokenize_input_mapping,
            # Appointment context for booking summary
            'appointment': appointment,
            'service_lines': service_lines,
            'payment_record': payment_record,
            'branch': appointment.branch_id,
            # Payment summary details
            'service_total': service_total,
            'booking_fee': booking_fee,
            'discount_amount': discount_amount,
            'payment_option': payment_option,
            'remaining_balance': remaining_balance,
            # Temporary NAB test bypass (only while the NAB provider is in test mode)
            'nab_test_mode': False,
            'nab_test_url': f'/salon/payment/test-complete/{appointment.id}?access_token={access_token}',
        }

        return request.render(
            'bnb_portal_appointment.salon_checkout_page', rendering_context
        )

    @route(
        '/salon/payment/transaction/<int:appointment_id>',
        type='jsonrpc', auth='public', website=True,
    )
    def salon_payment_transaction(self, appointment_id, access_token, **kwargs):
        """
        Create a payment.transaction for the salon appointment.
        Same pattern as /shop/payment/transaction in website_sale.
        """
        from odoo.addons.payment import utils as payment_utils
        from odoo.addons.payment.controllers.portal import PaymentPortal
        from werkzeug.exceptions import Forbidden

        appointment = self._get_scoped_appointment(appointment_id)
        if not appointment.exists():
            raise Forbidden()

        customer = appointment.customer_id
        payment_record = request.env['salon.appointment.payment'].sudo().search([
            ('appointment_id', '=', appointment.id),
            ('appointment_id.company_id', 'in', self._allowed_company_ids()),
        ], limit=1)

        amount = payment_record.payment_amount if payment_record else 0
        currency = appointment.branch_id.company_id.currency_id or request.env.company.currency_id

        # Validate access token
        if not payment_utils.check_access_token(access_token, customer.id, amount, currency.id):
            raise Forbidden()

        # Set reference prefix in kwargs (whitelisted via additional_allowed_keys)
        kwargs['reference_prefix'] = appointment.appointment_ref
        # Remove any non-whitelisted keys that the payment form may have sent
        kwargs.pop('partner_id', None)
        kwargs.pop('currency_id', None)
        kwargs.pop('amount', None)

        try:
            provider_id = int(kwargs.get('provider_id'))
            payment_method_id = int(kwargs.get('payment_method_id')) if kwargs.get('payment_method_id') else False
        except (TypeError, ValueError):
            raise Forbidden()
        compatible_providers = request.env['payment.provider'].sudo()._get_compatible_providers(
            appointment.branch_id.company_id.id,
            customer.id,
            amount,
            currency_id=currency.id,
        )
        if provider_id not in compatible_providers.ids:
            raise Forbidden()
        compatible_methods = request.env['payment.method'].sudo()._get_compatible_payment_methods(
            [provider_id], customer.id, currency_id=currency.id,
        )
        if payment_method_id and payment_method_id not in compatible_methods.ids:
            raise Forbidden()

        existing_tx = request.env['payment.transaction'].sudo().search([
            ('reference', 'like', f'{appointment.appointment_ref}%'),
            ('partner_id', '=', customer.id),
            ('amount', '=', amount),
            ('currency_id', '=', currency.id),
            ('state', 'in', ('pending', 'authorized', 'done')),
        ], order='id desc', limit=1)
        if existing_tx:
            PaymentPortal._update_landing_route(existing_tx, access_token)
            request.session['salon_appointment_id'] = appointment.id
            request.session['salon_last_tx_id'] = existing_tx.id
            return existing_tx._get_processing_values()

        payment_portal = PaymentPortal()
        payment_portal._validate_transaction_kwargs(
            kwargs, additional_allowed_keys=('reference_prefix',)
        )
        tx_sudo = payment_portal._create_transaction(
            amount=amount,
            currency_id=currency.id,
            partner_id=customer.id,
            **kwargs,
        )
        if tx_sudo.provider_code == 'nab_gateway' and 'nab_client_reference' in tx_sudo._fields:
            tx_sudo.nab_client_reference = appointment.appointment_ref

        # Update landing route with access token
        PaymentPortal._update_landing_route(tx_sudo, access_token)

        # Store appointment reference in session for confirmation
        request.session['salon_appointment_id'] = appointment.id
        request.session['salon_last_tx_id'] = tx_sudo.id

        return tx_sudo._get_processing_values()

    def _get_nab_test_provider(self):
        """Expose the fake payment provider only in an Odoo test process."""
        if not config.get('test_enable'):
            return request.env['payment.provider'].sudo().browse()
        return request.env['payment.provider'].sudo().search([
            ('code', '=', 'nab_gateway'),
            ('state', '=', 'test'),
        ], limit=1)

    @route('/salon/payment/test-complete/<int:appointment_id>', type='http', auth='public', methods=['GET'], website=True, sitemap=False)
    def salon_payment_test_complete(self, appointment_id, access_token=None, **kwargs):
        from werkzeug.exceptions import NotFound
        raise NotFound()

    @route('/salon/payment/confirm', type='http', auth='public', methods=['GET'], website=True, sitemap=False)
    def salon_payment_confirm(self, **kwargs):
        """
        Landing route after Odoo payment.form completes payment.
        Odoo redirects here with tx_id and access_token after Stripe payment succeeds.
        Confirms the appointment and renders the confirmation page.
        """
        from odoo.addons.payment import utils as payment_utils

        appointment_id = kwargs.get('appointment_id')
        tx_id = kwargs.get('tx_id')

        # Get appointment from URL param or session
        if not appointment_id:
            appointment_id = request.session.get('salon_appointment_id')

        if not appointment_id:
            return request.redirect('/book-online')

        appointment = self._get_scoped_appointment(int(appointment_id))
        if not appointment.exists():
            return request.redirect('/book-online')

        payment_record = request.env['salon.appointment.payment'].sudo().search([
            ('appointment_id', '=', appointment.id),
            ('appointment_id.company_id', 'in', self._allowed_company_ids()),
        ], limit=1)

        currency = appointment.branch_id.company_id.currency_id or request.env.company.currency_id
        amount = payment_record.payment_amount if payment_record else 0

        access_token = kwargs.get('access_token')
        if not access_token or not payment_utils.check_access_token(
            access_token, appointment.customer_id.id, amount, currency.id
        ):
            return request.redirect('/book-online')

        # Check payment transaction status if tx_id is provided
        tx_sudo = None
        payment_status = 'pending'
        payment_success = False
        if tx_id:
            tx_sudo = self._get_scoped_transaction(int(tx_id), appointment)
            if tx_sudo.exists():
                payment_status = tx_sudo.state  # 'done', 'authorized', 'pending', 'error', 'cancel'
                payment_success = tx_sudo.state == 'done'

        # Also check session tx_id as fallback
        if not tx_sudo or not tx_sudo.exists():
            session_tx_id = request.session.get('salon_last_tx_id')
            if session_tx_id:
                tx_sudo = self._get_scoped_transaction(session_tx_id, appointment)
                if tx_sudo.exists():
                    payment_status = tx_sudo.state
                    payment_success = tx_sudo.state == 'done'

        if tx_sudo and (not payment_record or currency.compare_amounts(tx_sudo.amount, payment_record.payment_amount)):
            return request.redirect('/book-online')

        # Sync payment record status based on transaction state (never mark paid unless done)
        if payment_record and tx_sudo and tx_sudo.exists():
            payment_update = {
                'payment_reference': appointment.appointment_ref,
                'transaction_id': tx_sudo.provider_reference or tx_sudo.reference or str(tx_sudo.id),
            }
            if tx_sudo.state == 'done':
                payment_update['payment_status'] = 'completed'
            elif tx_sudo.state in ('authorized', 'pending'):
                payment_update['payment_status'] = 'processing'
            elif tx_sudo.state in ('error', 'cancel'):
                payment_update['payment_status'] = 'failed'
            payment_record.sudo().write(payment_update)

        # If payment failed, cancel the appointment
        if payment_status in ('error', 'cancel'):
            if appointment.state == 'draft':
                appointment.sudo().write({'state': 'cancelled'})
            if payment_record and payment_record.payment_status != 'failed':
                payment_record.sudo().write({'payment_status': 'failed'})

        # If payment succeeded, confirm the appointment
        if payment_success:
            if tx_sudo:
                if not tx_sudo.reference or not tx_sudo.reference.startswith(appointment.appointment_ref):
                    return request.redirect('/book-online')
                if tx_sudo.partner_id.id != appointment.customer_id.id:
                    return request.redirect('/book-online')
                if payment_record and abs(tx_sudo.amount - payment_record.payment_amount) > 0.01:
                    return request.redirect('/book-online')

            # The appointment deliberately STAYS IN DRAFT after a successful
            # payment (full or 50% deposit): staff confirm it manually, and the
            # Confirm click anchors the actual time-consumption tracking
            # (client decision — do not auto-confirm here).

            # Create deposit record (same as POS deposit flow)
            if payment_record:
                self._create_online_deposit(appointment, payment_record, tx_sudo)

        # Get service lines for confirmation display
        service_lines = request.env['salon.appointment.service'].sudo().search([
            ('appointment_id', '=', appointment.id),
            ('appointment_id.company_id', 'in', self._allowed_company_ids()),
        ])

        currency = appointment.branch_id.company_id.currency_id or request.env.company.currency_id

        # Clean up session
        request.session.pop('salon_appointment_id', None)
        request.session.pop('salon_last_tx_id', None)

        raw_payment_status = payment_status
        failure_reason = ''
        if tx_sudo and tx_sudo.exists():
            failure_reason = tx_sudo.state_message or ''
        if not failure_reason and raw_payment_status in ('error', 'cancel'):
            failure_reason = 'Payment failed'
        ui_payment_status = 'done' if payment_success else ('pending' if payment_status in ('authorized', 'pending') else payment_status)

        return request.render('bnb_portal_appointment.salon_payment_confirmation', {
            'appointment': appointment,
            'service_lines': service_lines,
            'payment_record': payment_record,
            'payment_status': ui_payment_status,
            'raw_payment_status': raw_payment_status,
            'failure_reason': failure_reason,
            'transaction': tx_sudo,
            'branch': appointment.branch_id,
            'currency': currency,
        })

    def _create_online_deposit(self, appointment, payment_record, transaction):
        return request.env['bb.online.deposit.service']._create_online_deposit(
            appointment, payment_record, transaction)

    def _create_online_deposit_move(self, deposit, appointment, deposit_product, deposit_total, transaction=None):
        return request.env['bb.online.deposit.service']._create_online_deposit_move(
            deposit, appointment, deposit_product, deposit_total, transaction)
