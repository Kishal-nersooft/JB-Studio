from odoo import fields, models


class SalonAppointmentService(models.Model):
    _inherit = 'salon.appointment.service'

    appointment_date = fields.Date(
        related='appointment_id.appointment_date',
        store=True,
        readonly=True,
        index=True,
    )
    appointment_booked_online = fields.Boolean(
        related='appointment_id.booked_online',
        store=True,
        readonly=True,
        index=True,
    )

    appointment_is_advance_payment = fields.Boolean(
        related='appointment_id.is_advance_payment', readonly=True
    )
    appointment_advance_payment_amount = fields.Monetary(
        related='appointment_id.advance_payment_amount', readonly=True
    )
    appointment_discount_amount = fields.Monetary(
        related='appointment_id.discount_amount', readonly=True
    )
    appointment_total_before_discount = fields.Monetary(
        related='appointment_id.total_amount_before_discount', readonly=True
    )
    appointment_total_after_discount = fields.Monetary(
        related='appointment_id.total_amount_after_discount', readonly=True
    )

    def init(self):
        super().init()
        # Keep the database as the final concurrency guard.  Two public HTTP
        # requests can validate availability simultaneously; only a unique
        # index can make the identical online slot atomic.  Store/POS parallel
        # bookings remain intentionally allowed.
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
                salon_appt_service_online_slot_uniq
            ON salon_appointment_service
                (beautician_id, appointment_date, start_hour)
            WHERE appointment_booked_online IS TRUE
              AND beautician_id IS NOT NULL
        """)
