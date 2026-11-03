from odoo import models, fields, api, _
from markupsafe import Markup
from odoo.exceptions import ValidationError


class SalonAppointmentConsumption(models.Model):
    _name = 'salon.appointment.consumption'
    _description = 'Salon Appointment Consumption'
    _order = 'service_line_id, id'

    service_line_id = fields.Many2one(
        'salon.appointment.service',
        string='Service Line',
        required=True,
        ondelete='cascade'
    )
    appointment_id = fields.Many2one(
        'salon.appointment',
        related='service_line_id.appointment_id',
        store=True,
        readonly=True
    )
    product_id = fields.Many2one(
        'product.product',
        string='Consumption Product',
        required=True,
        domain=[('type', 'in', ['product', 'consu'])]
    )
    uom_id = fields.Many2one(
        'uom.uom',
        string='UoM',
        required=True
    )
    planned_qty = fields.Float(string="Planned Qty", default=1.0)
    actual_qty = fields.Float(string="Actual Qty", default=0.0)

    @api.constrains('planned_qty', 'actual_qty')
    def _check_quantities(self):
        for line in self:
            if line.planned_qty < 0 or line.actual_qty < 0:
                raise ValidationError(_("Quantities cannot be negative."))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            record._log_appointment_change(
                _("Consumption added: %s") % (record.product_id.display_name or "Unknown")
            )
        return records

    def write(self, vals):
        if vals:
            tracked_fields = self._get_chatter_tracked_fields(vals)
            old_values = {
                rec.id: {name: rec[name] for name in tracked_fields}
                for rec in self
            }
        res = super().write(vals)
        if vals:
            for record in self:
                record._log_field_changes(
                    vals,
                    prefix=_("Consumption updated: %s") % (record.product_id.display_name or "Unknown"),
                    old_values=old_values.get(record.id, {})
                )
        return res

    def unlink(self):
        for record in self:
            record._log_appointment_change(
                _("Consumption removed: %s") % (record.product_id.display_name or "Unknown")
            )
        return super().unlink()

    def _log_appointment_change(self, body):
        if not body:
            return
        for record in self:
            if record.appointment_id:
                record.appointment_id.message_post(
                    body=Markup(f"<div class=\"o_mail_notification\"><p>{body}</p><hr/></div>"),
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
            body = _("%s: %s: %s -> %s") % (prefix, field_label, old_disp, new_disp)
            self._log_appointment_change(body)

    @staticmethod
    def _format_field_value(field, value):
        if field.type == 'many2one':
            return value.display_name if value else "None"
        if field.type in ('many2many', 'one2many'):
            return ", ".join(value.mapped('display_name')) if value else "None"
        if field.type == 'selection':
            if value in (False, None, ''):
                return "None"
            selection = dict(field.selection)
            return selection.get(value, value)
        if field.type == 'boolean':
            return "Yes" if value else "No"
        if field.type in ('date', 'datetime'):
            if not value:
                return "None"
            return fields.Date.to_string(value) if field.type == 'date' else fields.Datetime.to_string(value)
        return str(value) if value not in (False, None, '') else "None"
