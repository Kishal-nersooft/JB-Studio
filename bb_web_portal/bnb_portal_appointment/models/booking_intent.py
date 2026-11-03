"""Payment-first website checkout. No customer or appointment exists before settlement."""
import hashlib
import hmac
import json
import logging
import math
import secrets
from datetime import timedelta

import psycopg2
from odoo import api, fields, models, modules
from odoo.modules.registry import Registry
from odoo.exceptions import ValidationError
from odoo.tools import email_normalize

from ..services.booking import (
    _compute_discount_from_code, _get_service_resource_ids,
    _validate_booking_availability, _validate_booking_resource_availability,
)

_logger = logging.getLogger(__name__)


class BookingIntent(models.Model):
    _name = 'bb.online.booking.intent'
    _description = 'Online payment checkout'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(required=True, readonly=True, copy=False)
    access_token = fields.Char(required=True, readonly=True, copy=False, groups='base.group_system')
    company_id = fields.Many2one('res.company', required=True, readonly=True, index=True)
    website_id = fields.Many2one('website', required=True, readonly=True)
    branch_id = fields.Many2one('beauty.branch', required=True, readonly=True)
    appointment_date = fields.Date(required=True, readonly=True, index=True)
    currency_id = fields.Many2one('res.currency', required=True, readonly=True)
    amount = fields.Monetary(required=True, readonly=True)
    payload = fields.Json(readonly=True, groups='base.group_system')
    # tracking=True: every state/outcome change is logged to the chatter
    # automatically (who, when, old value -> new value) -- this is the audit
    # trail staff and support rely on, so it must survive any future code
    # path that writes these fields, not just the ones we remember to log.
    state = fields.Selection([
        ('draft', 'Awaiting payment'), ('paid', 'Booked'),
        ('review', 'Payment needs attention'), ('expired', 'Expired'), ('refunded', 'Refund in progress or completed'),
    ], default='draft', required=True, readonly=True, index=True, tracking=True)
    expires_at = fields.Datetime(required=True, readonly=True, index=True)
    appointment_id = fields.Many2one('salon.appointment', readonly=True, copy=False, ondelete='restrict', tracking=True)
    transaction_ids = fields.One2many('payment.transaction', 'bnb_booking_intent_id', readonly=True)
    review_reason = fields.Text(readonly=True, tracking=True)

    _name_unique = models.Constraint('unique(name)', 'Checkout reference must be unique.')

    def _check_token(self, token):
        self.ensure_one()
        return bool(isinstance(token, str) and token and hmac.compare_digest(self.access_token, token))

    @api.model
    def _lock_company(self, company):
        # The write also forces concurrent REPEATABLE READ transactions to retry
        # with a fresh snapshot. SELECT FOR UPDATE alone can retain stale reads.
        self.env.cr.execute('UPDATE res_company SET write_date = write_date WHERE id = %s', [company.id])

    def _lock(self):
        self.ensure_one()
        self._lock_company(self.company_id)
        self.env.cr.execute('SELECT id FROM bb_online_booking_intent WHERE id = %s FOR UPDATE', [self.id])
        self.invalidate_recordset()

    @api.model
    def _held(self, company, day, staff_id, resource_ids, start, end, exclude_id=False, email=None):
        """Whether another live checkout is holding this staff member or resource.

        A hold only means "a customer is about to pay". It is not counted when
        that payment has already failed or been cancelled, nor when it is the
        same customer's (same email) earlier attempt that never started to pay:
        they are retrying, not competing with themselves.
        """
        intents = self.sudo().search([
            ('company_id', '=', company.id), ('appointment_date', '=', day),
            ('state', '=', 'draft'), ('expires_at', '>', fields.Datetime.now()),
            ('id', '!=', exclude_id or self.env.context.get('bnb_replace_intent_id') or 0),
        ])
        dead = ('cancel', 'error')
        intents = intents.filtered(lambda i: not (
            i.transaction_ids and all(tx.state in dead for tx in i.transaction_ids)
        ))
        if email:
            # The same customer's earlier attempt is only set aside while
            # nothing has reached the gateway: no submission, no payment in flight.
            submitted = self.env['bb.online.gateway.submission'].sudo().search([
                ('transaction_id', 'in', intents.transaction_ids.ids)]).transaction_id
            intents = intents.filtered(lambda i: (
                ((i.payload or {}).get('booking') or {}).get('email') != email
                or any(tx in submitted or tx.state in ('pending', 'authorized', 'done')
                       for tx in i.transaction_ids)))
        for intent in intents:
            for line in (intent.payload or {}).get('lines', []):
                if start < line['start_hour'] + line['duration'] and end > line['start_hour']:
                    if staff_id == line['beautician_id'] or set(resource_ids).intersection(line['resource_ids']):
                        return True
        return False

    @api.model
    def _plan_any_professionals(self, services, branch, day, start, email=None, exclude_id=False):
        """Return one available qualified professional for each sequential service.

        The website's ``Any professional`` option is only truthful when every
        service in the requested sequence can be assigned.  Keep this planner
        shared by the professional-selection endpoint and final checkout
        preparation so the UI cannot advertise an option which Pay Now will
        immediately reject.
        """
        assignments = []
        current = float(start)
        held_by_checkout = False
        for service in services:
            duration = float(service.duration or 0)
            resources = _get_service_resource_ids(service, branch)
            staff_lines = service.product_tmpl_id.beautician_line_ids.filtered(
                lambda line: line.beautician_id.active
                and line.beautician_id.is_beautician
                and line.beautician_id.company_id == branch.company_id
                and (
                    branch in line.beautician_id.beautician_branch_ids
                    or line.beautician_id.branch_id == branch
                )
            )
            selected_line = False
            for candidate in staff_lines.sorted('id'):
                staff = candidate.beautician_id
                if not staff._get_online_booking_availability(
                    branch, day, start_hour=current, duration=duration
                ).get('available'):
                    continue
                ok, _error = _validate_booking_availability(
                    self.env,
                    str(day),
                    branch,
                    [service],
                    {str(service.id): staff.id},
                    current,
                )
                if not ok:
                    continue
                if self._held(
                    branch.company_id,
                    day,
                    staff.id,
                    resources,
                    current,
                    current + duration,
                    exclude_id=exclude_id,
                    email=email,
                ):
                    held_by_checkout = True
                    continue
                selected_line = candidate
                break
            if not selected_line:
                return [], held_by_checkout
            assignments.append(selected_line)
            current += duration
        return assignments, held_by_checkout

    @api.model
    def _waiting_list_allowed(self, branch, start, total_duration):
        """Whether a request nobody can take may join the waiting list.

        Only a time inside the branch's opening hours is worth queueing; staff
        then confirm a professional and time with the customer.
        """
        work_start = branch.work_start_hour or 9.0
        work_end = branch.work_end_hour or 18.0
        return work_start <= float(start) and float(start) + float(total_duration) <= work_end

    @api.model
    def _prepare(self, form, branch, website, social=None):
        """Validate and quote entirely from trusted server data; persist nothing."""
        self = self.sudo().with_company(branch.company_id).with_context(allowed_company_ids=branch.company_id.ids)
        if not branch.active or branch.company_id != website.company_id or (branch.website_id and branch.website_id != website):
            raise ValidationError('This location is not available on this website.')
        self._lock_company(branch.company_id)
        keys = ('first_name', 'last_name', 'email', 'mobile_phone', 'pronouns',
                'billing_address', 'city', 'state', 'postcode', 'promo_code')
        booking = {key: str(form.get(key) or '').strip()[:255] for key in keys}
        booking['other_phone'] = str(form.get('other_phone') or form.get('customer_other_phone') or '')[:64]
        booking['email'] = email_normalize(booking['email'])
        if not booking['email'] or not all(booking[k] for k in ('first_name', 'last_name', 'mobile_phone')):
            raise ValidationError('Please enter your name, valid email address and phone number.')
        if form.get('agree_policy') != 'on':
            raise ValidationError('Please accept the booking terms before paying.')
        booking['remember_customer'] = form.get('remember_me') == 'on'
        option = form.get('payment_option', 'full')
        if option not in ('half', 'full'):
            raise ValidationError('Choose either 50% or full payment.')
        booking['payment_option'] = option
        try:
            day = fields.Date.to_date(form.get('appointment_date'))
            service_ids = json.loads(form.get('selected_services', '[]'))
            selected = json.loads(form.get('selected_beauticians', '{}'))
            slots = json.loads(form.get('selected_timeslots', '{}'))
            if not isinstance(slots, dict) or not slots:
                raise ValueError()
            start = float(next(iter(slots.values()))['start_hour'])
            if not math.isfinite(start) or not isinstance(selected, dict):
                raise ValueError()
            if not isinstance(service_ids, list) or not 1 <= len(service_ids) <= 20:
                raise ValueError()
            service_ids = [int(value) for value in service_ids]
            if len(set(service_ids)) != len(service_ids):
                raise ValueError()
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ValidationError('Please select valid services, date and time.')
        now = fields.Datetime.context_timestamp(self.with_context(tz=branch.tz or 'UTC'), fields.Datetime.now())
        if not day or day < now.date() or (day == now.date() and start <= now.hour + now.minute / 60):
            raise ValidationError('Please choose a future appointment time.')
        products = self.env['product.product'].search([
            ('id', 'in', service_ids), ('type', '=', 'service'), ('active', '=', True),
            ('product_tmpl_id.is_appointment_service', '=', True),
            ('product_tmpl_id.branch_ids', 'in', branch.ids),
            ('company_id', 'in', [False, branch.company_id.id]),
        ])
        if len(products) != len(service_ids):
            raise ValidationError('One of the selected services is not offered at this location.')
        ordered = [products.filtered(lambda p: p.id == pid) for pid in service_ids]
        requested_staff = {
            service.id: selected.get(str(service.id))
            for service in ordered
        }
        all_any = all(not chosen or chosen == 'any' for chosen in requested_staff.values())
        any_assignments = []
        waiting_list = False
        if all_any:
            any_assignments, held_by_checkout = self._plan_any_professionals(
                ordered,
                branch,
                day,
                start,
                email=booking['email'],
            )
            if not any_assignments:
                if held_by_checkout:
                    raise ValidationError(
                        'This time is being held by another customer who is completing their payment. '
                        'Please choose another time, or try again in a few minutes.')
                # Nobody rostered and free: the customer may have accepted the
                # waiting list on the professional step. Never fall into it
                # silently, they must have been shown it before paying.
                total_duration = sum(float(service.duration or 0) for service in ordered)
                if (form.get('accept_waiting_list') == 'on'
                        and self._waiting_list_allowed(branch, start, total_duration)):
                    waiting_list = True
                else:
                    raise ValidationError(
                        'No professional is available for the complete service selection at this time. '
                        'Please choose another time.')

        lines, current = [], start
        for service_index, service in enumerate(ordered):
            duration = float(service.duration or 0)
            if not math.isfinite(duration) or duration <= 0:
                raise ValidationError('This service does not have a valid booking duration.')
            if waiting_list:
                # No staff, no resources: nothing is held until staff place it.
                lines.append({
                    'service_id': service.id, 'name': service.name,
                    'beautician_id': False, 'staff_name': '',
                    'staff_requested_by_client': False,
                    'base_price': service.list_price, 'beautician_addon_price': 0.0,
                    'duration': duration, 'start_hour': current, 'resource_ids': [],
                })
                current += duration
                continue
            staff_lines = service.product_tmpl_id.beautician_line_ids.filtered(
                lambda l: l.beautician_id.active and l.beautician_id.is_beautician
                and l.beautician_id.company_id == branch.company_id
                and (branch in l.beautician_id.beautician_branch_ids or l.beautician_id.branch_id == branch))
            chosen = requested_staff[service.id]
            requested = bool(chosen and chosen != 'any')
            if all_any:
                staff_line = any_assignments[service_index]
                held_by_checkout = False
            elif requested:
                try:
                    staff_lines = staff_lines.filtered(lambda l: l.beautician_id.id == int(chosen))
                except (TypeError, ValueError):
                    raise ValidationError('Invalid professional selection.')
            resources = _get_service_resource_ids(service, branch)
            if not all_any:
                staff_line = False
                held_by_checkout = False
                for candidate in staff_lines.sorted('id'):
                    staff = candidate.beautician_id
                    if not staff._get_online_booking_availability(branch, day, start_hour=current, duration=duration).get('available'):
                        continue
                    ok, _ = _validate_booking_availability(self.env, str(day), branch, [service], {str(service.id): staff.id}, current)
                    if not ok:
                        continue
                    if self._held(branch.company_id, day, staff.id, resources, current, current + duration, email=booking['email']):
                        held_by_checkout = True
                        continue
                    staff_line = candidate
                    break
            if not staff_line:
                if held_by_checkout:
                    raise ValidationError(
                        'This time is being held by another customer who is completing their payment. '
                        'Please choose another time, or try again in a few minutes.')
                raise ValidationError('This professional or time is no longer available. Please choose another time.')
            ok, error = _validate_booking_resource_availability(self.env, str(day), branch, [service], current)
            if not ok:
                raise ValidationError(error)
            lines.append({
                'service_id': service.id, 'name': service.name,
                'beautician_id': staff_line.beautician_id.id,
                'staff_name': staff_line.beautician_id.name,
                'staff_requested_by_client': requested,
                'base_price': service.list_price,
                'beautician_addon_price': staff_line.price if requested else 0.0,
                'duration': duration, 'start_hour': current, 'resource_ids': resources,
            })
            current += duration
        pricing = self.env['bb.appointment.pricing.service']
        service_total = pricing.calculate_service_totals(
            sum(pricing.calculate_line_total(l['base_price'], l['beautician_addon_price']) for l in lines),
            appointment_date=day, saturday_surcharge_percent=branch.saturday_surcharge_percent,
            sunday_surcharge_percent=branch.sunday_surcharge_percent)['total_amount']
        discount = 0.0
        if booking['promo_code']:
            # Stored-value redemption needs its own debit, not an unlimited discount.
            card = self.env['loyalty.card'].search([
                ('code', '=ilike', booking['promo_code']),
                ('program_id.program_type', 'in', ['gift_card', 'ewallet']),
                ('program_id.company_id', 'in', [False, branch.company_id.id]),
            ], limit=1)
            if card:
                raise ValidationError('Please contact the salon to book using a gift card or account credit.')
            discount, error = _compute_discount_from_code(self.env, booking['promo_code'], service_total + branch.booking_fee, branch=branch)
            if error:
                raise ValidationError(error)
        totals = pricing.calculate_checkout_totals(service_total, branch.booking_fee, discount, option)
        amount = branch.company_id.currency_id.round(totals['payment_amount'])
        if not math.isfinite(amount) or amount <= 0:
            raise ValidationError('Online bookings require a 50% or full payment. Please contact the salon for a no-charge booking.')
        return {
            'name': 'WEB-' + secrets.token_hex(12).upper(), 'access_token': secrets.token_urlsafe(32),
            'company_id': branch.company_id.id, 'website_id': website.id, 'branch_id': branch.id,
            'appointment_date': day, 'currency_id': branch.company_id.currency_id.id, 'amount': amount,
            'expires_at': fields.Datetime.now() + timedelta(minutes=20),
            'payload': {'booking': booking, 'lines': lines, 'totals': totals,
                        'service_total': service_total, 'booking_fee': branch.booking_fee,
                        'waiting_list': waiting_list,
                        'social': social or {}},
        }

    def _validate_slot(self):
        self.ensure_one()
        now = fields.Datetime.context_timestamp(self.with_context(tz=self.branch_id.tz or 'UTC'), fields.Datetime.now())
        if self.appointment_date < now.date() or (self.appointment_date == now.date() and self.payload['lines'][0]['start_hour'] <= now.hour + now.minute / 60):
            raise ValidationError('The requested appointment time has already passed.')
        if self.payload.get('waiting_list'):
            # Nobody is assigned, so there is no staff or resource to re-check.
            for line in self.payload['lines']:
                if not self.env['product.product'].browse(line['service_id']).exists():
                    raise ValidationError('The selected service is no longer available.')
            return
        for line in self.payload['lines']:
            service = self.env['product.product'].browse(line['service_id']).exists()
            staff = self.env['hr.employee'].browse(line['beautician_id']).exists()
            if not service or not staff or not staff.active:
                raise ValidationError('The selected service or professional is no longer available.')
            if not staff._get_online_booking_availability(self.branch_id, self.appointment_date,
                    start_hour=line['start_hour'], duration=line['duration']).get('available'):
                raise ValidationError('The selected professional is no longer rostered at this time.')
            ok, error = _validate_booking_availability(self.env, str(self.appointment_date), self.branch_id,
                [service], {str(service.id): staff.id}, line['start_hour'])
            if not ok:
                raise ValidationError(error)
            ok, error = _validate_booking_resource_availability(self.env, str(self.appointment_date), self.branch_id, [service], line['start_hour'])
            if not ok:
                raise ValidationError(error)
            if self._held(self.company_id, self.appointment_date, staff.id, line['resource_ids'],
                          line['start_hour'], line['start_hour'] + line['duration'], exclude_id=self.id,
                          email=self.payload['booking']['email']):
                raise ValidationError('The requested time is currently reserved by another checkout.')

    def _customer(self):
        booking = self.payload['booking']
        social = self.payload.get('social') or {}
        Partner = self.env['res.partner'].sudo()
        domain = [('company_id', 'in', [False, self.company_id.id]), ('is_company', '=', False)]
        customer = Partner.browse()
        if social.get('verified_email') and social.get('email', '').lower() == booking['email'].lower():
            if social.get('partner_id'):
                customer = Partner.search(domain + [('id', '=', social['partner_id'])], limit=1)
            if not customer and social.get('apple_sub'):
                customer = Partner.search(domain + [('apple_signin_sub', '=', social['apple_sub'])], limit=1)
        # Serialise shared email creation even across companies. No existing
        # customer details are modified based on an unverified form email.
        key = int.from_bytes(hashlib.sha256(booking['email'].encode()).digest()[:8], 'big', signed=True)
        self.env.cr.execute('SELECT pg_advisory_xact_lock(%s)', [key])
        if not customer:
            customer = Partner.search(domain + [('email', '=ilike', booking['email'])], limit=1)
        if not customer:
            vals = {'name': booking['first_name'] + ' ' + booking['last_name'], 'email': booking['email'],
                    'phone': booking['mobile_phone'], 'street': booking['billing_address'],
                    'city': booking['city'], 'zip': booking['postcode'], 'company_id': self.company_id.id}
            if social.get('verified_email') and social.get('email', '').lower() == booking['email'].lower() and social.get('apple_sub'):
                vals.update(apple_signin_sub=social['apple_sub'], apple_signin_first_name=social.get('first_name'),
                            apple_signin_last_name=social.get('last_name'))
            customer = Partner.create(vals)
        return customer

    def _finalize(self, tx):
        """Called only by verified transaction processing, never from form values."""
        self.ensure_one()
        self = self.sudo().with_company(self.company_id).with_context(allowed_company_ids=self.company_id.ids)
        self._lock()
        tx.invalidate_recordset()
        if tx.bnb_booking_intent_id != self or tx.state != 'done' or tx.operation not in ('online_direct', 'online_redirect'):
            raise ValidationError('A completed online payment is required.')
        if tx.company_id != self.company_id or tx.currency_id != self.currency_id or self.currency_id.compare_amounts(tx.amount, self.amount):
            raise ValidationError('The payment does not match this checkout.')
        if self.appointment_id:
            return self.appointment_id
        if tx.child_transaction_ids.filtered(lambda child: child.operation == 'refund' and child.state not in ('error', 'cancel')):
            self.write({'state': 'refunded', 'review_reason': 'Refund initiated; automatic booking creation stopped.'})
            return self.env['salon.appointment']
        try:
            with self.env.cr.savepoint():
                self._validate_slot()
                customer = self._customer()
                booking, totals = self.payload['booking'], self.payload['totals']
                vals = {'customer_id': customer.id, 'branch_id': self.branch_id.id,
                        'appointment_date': self.appointment_date, 'booked_online': True,
                        'policy_agreed': True, 'remember_customer': booking['remember_customer'],
                        'state': 'draft', 'is_waiting_list': bool(self.payload.get('waiting_list')),
                        'discount_amount': totals['discount_amount'],
                        'total_amount_before_discount': totals['total_before_discount'],
                        'total_amount_after_discount': totals['total_after_discount']}
                for key in ('first_name', 'last_name', 'email'):
                    vals['customer_' + key] = booking[key]
                vals.update(customer_phone=booking['mobile_phone'], customer_other_phone=booking['other_phone'], customer_pronouns=booking['pronouns'])
                Appointment = self.env['salon.appointment']
                if 'auto_send_consultation_forms' in Appointment._fields:
                    vals['auto_send_consultation_forms'] = False
                appointment = Appointment.with_context(skip_mobile_message_sms=True, skip_auto_consultation_forms=True).create(vals)
                for line in self.payload['lines']:
                    line_vals = {key: line[key] for key in ('service_id', 'beautician_id', 'staff_requested_by_client', 'beautician_addon_price', 'start_hour', 'duration')}
                    line_vals.update(appointment_id=appointment.id, time_period='morning' if line['start_hour'] < 12 else 'evening')
                    if 'resource_ids' in self.env['salon.appointment.service']._fields:
                        line_vals['resource_ids'] = [(6, 0, line['resource_ids'])]
                    created = self.env['salon.appointment.service'].create(line_vals)
                    # Preserve the paid quote when a price changes during checkout.
                    created.write({'base_price': line['base_price']})
                if self.currency_id.compare_amounts(appointment.total_amount, self.payload['service_total']) or self.currency_id.compare_amounts(appointment.booking_fee, self.payload['booking_fee']):
                    raise ValidationError('Booking prices changed while payment was in progress; staff must review this payment.')
                self.env['salon.appointment.payment'].create({
                    'appointment_id': appointment.id, 'payment_method': 'online',
                    'payment_amount': self.amount, 'payment_status': 'completed',
                    'payment_option': booking['payment_option'], 'discount_amount': totals['discount_amount'],
                    'promo_code': booking['promo_code'], 'billing_address': booking['billing_address'],
                    'billing_city': booking['city'], 'billing_state': booking['state'], 'billing_postcode': booking['postcode'],
                    'payment_reference': appointment.appointment_ref,
                    'transaction_id': tx.provider_reference or tx.reference,
                    # The real source, e.g. "NAB Gateway - Apple Pay", instead
                    # of the field's legacy 'TimelyPay' default.
                    'payment_provider': ' - '.join(filter(None, [tx.provider_id.name, tx.payment_method_id.name])),
                })
                tx.write({'partner_id': customer.id})
                self.write({'appointment_id': appointment.id, 'state': 'paid', 'review_reason': False})
                if hasattr(appointment, '_generate_sms_token'):
                    appointment._generate_sms_token()
                self._notify_after_commit(appointment)
                return appointment
        except psycopg2.OperationalError:
            raise
        except Exception:
            _logger.exception('Paid checkout %s could not be booked', self.name)
            self._mark_review('Payment received but booking could not be completed. Check availability and arrange the booking or refund.')
            return self.env['salon.appointment']

    def _mark_review(self, reason):
        self.ensure_one()
        self.sudo().write({'state': 'review', 'review_reason': reason})
        if not self.activity_ids:
            self.sudo().activity_schedule('mail.mail_activity_data_todo',
                user_id=self.env.ref('base.user_admin').id,
                summary='Online payment needs attention', note=reason)

    def _notify_after_commit(self, appointment):
        """Notify only for a persisted paid booking, also on the public callback path."""
        appointment_id, dbname, uid = appointment.id, self.env.cr.dbname, self.env.uid

        def notify(env):
            record = env['salon.appointment'].sudo().browse(appointment_id).exists()
            if not record or record.is_waiting_list:
                # A waiting-list request has no professional or confirmed time
                # yet, so the usual confirmation would promise one.
                return
            if hasattr(record, '_send_sms_confirmation') and not record.sms_confirmation_sent:
                record._send_sms_confirmation()
            if 'auto_send_consultation_forms' in record._fields:
                record.write({'auto_send_consultation_forms': True})

        if modules.module.current_test:
            notify(self.env)
            return

        @self.env.cr.postcommit.add
        def notify_paid_booking():
            try:
                with Registry(dbname).cursor() as cr:
                    notify(api.Environment(cr, uid, {}))
            except Exception:
                _logger.exception('Notification failed for paid appointment %s', appointment_id)

    @api.model
    def _cron_checkout_maintenance(self):
        # Financial evidence and paid-but-unresolved requests are never deleted.
        cutoff = fields.Datetime.now() - timedelta(days=1)
        stale = self.sudo().search([('state', 'in', ['draft', 'expired']), ('expires_at', '<', cutoff)], limit=500)
        stale.filtered(lambda i: not i.transaction_ids).unlink()
        stale.exists().filtered(lambda i: i.state == 'draft' and not any(t.state in ('done', 'pending', 'authorized') for t in i.transaction_ids)).write({'state': 'expired'})
        for intent in self.sudo().search([('state', 'in', ['draft', 'review']), ('transaction_ids.state', '=', 'done')], limit=500):
            done = intent.transaction_ids.filtered(lambda tx: tx.state == 'done')
            if done:
                try:
                    with self.env.cr.savepoint():
                        done._post_process()
                except psycopg2.OperationalError:
                    raise
                except Exception:
                    _logger.exception('Checkout recovery failed for %s', intent.name)
