from odoo import models, fields, api, _
from markupsafe import Markup, escape
from datetime import timedelta
from odoo.exceptions import ValidationError
from odoo.tools.misc import format_amount


class SalonAppointmentPayment(models.Model):
    _name = 'salon.appointment.payment'
    _description = 'Salon Appointment Payment Details'

    # -------------------------
    # Link to Appointment
    # -------------------------
    appointment_id = fields.Many2one(
        'salon.appointment',
        string='Appointment',
        required=True,
        ondelete='cascade'
    )

    # -------------------------
    # Payment Method
    # -------------------------
    payment_method = fields.Selection([
        ('card', 'Credit/Debit Card'),
        ('cash', 'Cash'),
        ('bank_transfer', 'Bank Transfer'),
        ('online', 'Online Payment'),
        ('stripe', 'Stripe'),
        ('afterpay', 'Afterpay'),
        ('apple_pay', 'Apple Pay'),
        ('google_pay', 'Google Pay'),
    ], string='Payment Method', default='card')

    # -------------------------
    # Payment Details
    # -------------------------
    payment_amount = fields.Monetary(string='Payment Amount', required=True)
    payment_date = fields.Datetime(string='Payment Date', default=fields.Datetime.now)
    payment_reference = fields.Char(string='Payment Reference')
    currency_id = fields.Many2one('res.currency', related='appointment_id.currency_id')

    # -------------------------
    # Card Details (if applicable)
    # -------------------------
    card_number_masked = fields.Char(string='Card Number (Masked)')
    card_type = fields.Char(string='Card Type')

    # -------------------------
    # Billing Address
    # -------------------------
    billing_address = fields.Text(string='Billing Address')
    billing_city = fields.Char(string='City')
    billing_state = fields.Char(string='State')
    billing_postcode = fields.Char(string='Postcode')

    # -------------------------
    # Promo Codes & Discounts
    # -------------------------
    promo_code = fields.Char(string='Promo Code')
    discount_amount = fields.Monetary(string='Discount Amount', default=0.0)
    payment_option = fields.Selection([
        ('full', 'Full Payment'),
        ('half', '50% Deposit'),
    ], string='Payment Option', default='full')

    # -------------------------
    # Payment Status & Provider
    # -------------------------
    payment_status = fields.Selection([
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('refunded', 'Refunded')
    ], string='Payment Status', default='pending')

    payment_provider = fields.Char(string='Payment Provider', default='TimelyPay')
    transaction_id = fields.Char(string='Transaction ID')
    refunded_amount = fields.Monetary(string='Refunded Amount', default=0.0, copy=False)
    refund_date = fields.Datetime(string='Refund Date', copy=False)
    refund_reference = fields.Char(string='Refund Reference', copy=False)

    # -------------------------
    # OVERRIDE CREATE
    # -------------------------
    @api.model
    def create(self, vals):
        payment = super(SalonAppointmentPayment, self).create(vals)
        payment._log_appointment_change(payment._payment_log_title(_('recorded')))
        # Update related appointment's payment status
        payment.appointment_id._update_payment_status()
        return payment

    # -------------------------
    # OVERRIDE WRITE
    # -------------------------
    def write(self, vals):
        if vals:
            tracked_fields = self._get_chatter_tracked_fields(vals)
            old_values = {
                record.id: {name: record[name] for name in tracked_fields}
                for record in self
            }
        result = super(SalonAppointmentPayment, self).write(vals)
        if vals:
            for payment in self:
                payment._log_field_changes(
                    vals,
                    prefix=payment._payment_log_title(_('updated')),
                    old_values=old_values.get(payment.id, {})
                )
        # Update related appointment's payment status
        for payment in self:
            payment.appointment_id._update_payment_status()
        return result

    def unlink(self):
        for payment in self:
            payment._log_appointment_change(
                payment._payment_log_title(_('removed'))
            )
        return super().unlink()

    def _payment_log_title(self, action):
        self.ensure_one()
        method = dict(self._fields['payment_method'].selection).get(
            self.payment_method, _('Payment'))
        option = dict(self._fields['payment_option'].selection).get(
            self.payment_option, _('Unspecified option'))
        currency = self.currency_id or self.appointment_id.currency_id
        amount = format_amount(self.env, self.payment_amount or 0.0, currency)
        return _("%s %s — %s (%s)") % (method, action, amount, option)

    def _log_appointment_change(self, body):
        if not body:
            return
        for payment in self:
            if payment.appointment_id:
                payment.appointment_id.message_post(
                    body=Markup(
                        '<div class="o_mail_notification"><p>{}</p><hr/></div>'
                    ).format(escape(body)),
                    subtype_xmlid="mail.mt_note",
                )

    def _get_chatter_tracked_fields(self, vals):
        skip = {
            'message_follower_ids', 'message_partner_ids', 'message_ids',
            'activity_ids', 'activity_exception_decoration', 'activity_state',
            'activity_type_icon', 'activity_type_id', 'activity_user_id',
            'display_name',
        }
        return [name for name in vals.keys() if name in self._fields and name not in skip]

    def _log_field_changes(self, vals, prefix, old_values=None):
        old_values = old_values or {}
        changes = []
        for name in self._get_chatter_tracked_fields(vals):
            field = self._fields.get(name)
            if not field:
                continue
            old = old_values.get(name, False)
            new = self[name]

            if field.type == 'many2one':
                old_cmp = old.id if old else False
                new_cmp = new.id if new else False
            elif field.type in ('many2many', 'one2many'):
                old_cmp = old.ids if old else []
                new_cmp = new.ids if new else []
            else:
                old_cmp = old
                new_cmp = new

            if old_cmp == new_cmp and name in old_values:
                continue

            field_label = field.string or name
            old_disp = self._format_field_value(field, old)
            new_disp = self._format_field_value(field, new)
            changes.append(_("%s: %s → %s") % (field_label, old_disp, new_disp))

        if changes:
            items = Markup('').join(
                Markup('<li>{}</li>').format(escape(change))
                for change in changes
            )
            body = Markup(
                '<div class="o_mail_notification">'
                '<p><strong>{}</strong></p><ul>{}</ul><hr/></div>'
            ).format(escape(prefix), items)
            self.appointment_id.message_post(body=body, subtype_xmlid='mail.mt_note')

    def _format_field_value(self, field, value):
        empty_label = _("Not set")
        if field.type == 'many2one':
            return value.display_name if value else empty_label
        if field.type in ('many2many', 'one2many'):
            return ", ".join(value.mapped('display_name')) if value else empty_label
        if field.type == 'monetary':
            if value in (False, None, ''):
                return empty_label
            currency = self.currency_id or self.appointment_id.currency_id
            return format_amount(self.env, value, currency)
        if field.type == 'selection':
            if value in (False, None, ''):
                return empty_label
            selection = dict(field.selection)
            return selection.get(value, value)
        if field.type == 'boolean':
            return "Yes" if value else "No"
        if field.type in ('date', 'datetime'):
            if not value:
                return empty_label
            return fields.Date.to_string(value) if field.type == 'date' else fields.Datetime.to_string(value)
        return str(value) if value not in (False, None, '') else empty_label
