from odoo import _, fields, models


class AppointmentCancelWizard(models.TransientModel):
    """Ask why an appointment is being cancelled, from the backend form.

    The reason is optional: staff cancelling in a hurry should not be blocked,
    and the appointment still cancels if they pick nothing.
    """

    _name = 'salon.appointment.cancel.wizard'
    _description = 'Cancel Appointment'

    appointment_id = fields.Many2one(
        'salon.appointment',
        string='Appointment',
        required=True,
        ondelete='cascade',
    )
    reason_id = fields.Many2one(
        'salon.cancellation.reason',
        string='Reason for cancellation',
    )
    note = fields.Char(
        string='Note',
        help='Anything the list above does not cover.',
    )

    def action_confirm_cancel(self):
        self.ensure_one()
        self.appointment_id.action_cancel(
            reason_id=self.reason_id.id or None,
            note=self.note or None,
        )
        return {'type': 'ir.actions.act_window_close'}
