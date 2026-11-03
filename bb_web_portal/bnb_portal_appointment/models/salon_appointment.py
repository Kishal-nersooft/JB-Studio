from odoo import api, fields, models


class SalonAppointment(models.Model):
    _inherit = 'salon.appointment'

    # Explicit origin flag used by the database concurrency guard on service
    # lines.  Do not infer this from a payment row: zero-value and abandoned
    # checkout bookings are still public online bookings.
    booked_online = fields.Boolean(default=False, index=True, copy=False)

    @api.model
    def _normalize_booking_source_vals(self, vals, appointment=None):
        """Preserve explicit origins across ORM imports and counter edits.

        is_online_booking describes payment evidence and is deliberately not
        used here. Receiving an online payment does not change a manual origin.
        """
        vals = dict(vals)
        channel = vals.get('appointment_type')
        if channel in ('leave', 'break'):
            return vals
        if channel in ('instore', 'callcenter'):
            vals['booked_online'] = False
        elif channel == 'online' or vals.get('booked_online'):
            vals.update(appointment_type='online', booked_online=True, is_walk_in=False)
        elif 'booked_online' in vals and not vals['booked_online']:
            if appointment and appointment.appointment_type == 'online' and not channel:
                vals['appointment_type'] = 'instore'
        elif appointment and (appointment.booked_online or appointment.appointment_type == 'online'):
            vals.update(appointment_type='online', booked_online=True, is_walk_in=False)
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([self._normalize_booking_source_vals(vals) for vals in vals_list])

    def write(self, vals):
        if not {'appointment_type', 'booked_online', 'is_walk_in'} & vals.keys():
            return super().write(vals)
        result = True
        for records in self.grouped(lambda appt: (appt.appointment_type, appt.booked_online)).values():
            normalized = self._normalize_booking_source_vals(vals, records[:1])
            result = super(SalonAppointment, records).write(normalized) and result
        return result

    @api.model
    def _booking_channel(self, vals):
        """A booking made through the public website is an online booking."""
        if vals.get('booked_online'):
            return 'online'
        return super()._booking_channel(vals)

    discount_amount = fields.Monetary(string='Discount Amount', default=0.0)
    total_amount_before_discount = fields.Monetary(string='Total Before Discount', default=0.0)
    total_amount_after_discount = fields.Monetary(string='Total After Discount', default=0.0)

    is_advance_payment = fields.Boolean(string='Advance Payment', compute='_compute_payment_summary', store=True)
    advance_payment_amount = fields.Monetary(string='Advance Amount', compute='_compute_payment_summary', store=True)

    @api.depends('payment_line_ids.payment_option', 'payment_line_ids.payment_amount', 'payment_line_ids.payment_date')
    def _compute_payment_summary(self):
        for record in self:
            payment = record.payment_line_ids.sorted(
                key=lambda p: p.payment_date or p.create_date or p.id, reverse=True
            )[:1]
            if payment and payment.payment_option == 'half':
                record.is_advance_payment = True
                record.advance_payment_amount = payment.payment_amount
            else:
                record.is_advance_payment = False
                record.advance_payment_amount = 0.0
