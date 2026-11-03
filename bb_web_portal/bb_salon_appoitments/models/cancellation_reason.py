from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class SalonCancellationReason(models.Model):
    """Pre-defined reasons staff pick from when cancelling an appointment.

    Kept as records rather than a Selection so branch managers can add and
    retire reasons themselves without a code change, and so reporting can group
    cancellations by reason.
    """

    _name = 'salon.cancellation.reason'
    _description = 'Appointment Cancellation Reason'
    _order = 'sequence, name'

    name = fields.Char(string='Reason', required=True, translate=True)
    sequence = fields.Integer(string='Sequence', default=10)
    # Retiring a reason keeps it on the appointments already cancelled with it,
    # while removing it from the dropdown for new cancellations.
    active = fields.Boolean(string='Active', default=True)
    # No company_id: cancellation reasons are shared by every company, so a
    # branch manager anywhere sees the same list and reporting can group by
    # reason across the whole business.

    @api.constrains('name')
    def _check_name_unique(self):
        """Reject duplicate reasons, ignoring case."""
        for reason in self:
            duplicate = self.sudo().search([
                ('id', '!=', reason.id),
                ('name', '=ilike', (reason.name or '').strip()),
            ], limit=1)
            if duplicate:
                raise ValidationError(_(
                    "The cancellation reason '%s' already exists.", reason.name))
