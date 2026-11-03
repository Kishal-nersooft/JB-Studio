from odoo import models, fields, api


class BeauticianBulkAddWizard(models.TransientModel):
    _name = 'beautician.bulk.add.wizard'
    _description = 'Add Multiple Beauticians to Service'

    product_tmpl_id = fields.Many2one(
        'product.template',
        string="Service",
        required=True,
        readonly=True,
    )
    branch_ids = fields.Many2many(
        'beauty.branch',
        related='product_tmpl_id.branch_ids',
        string="Branches",
        readonly=True,
    )
    beautician_ids = fields.Many2many(
        'hr.employee',
        string="Beauticians",
        domain="[('is_beautician', '=', True), '|', ('branch_id', 'in', branch_ids), ('beautician_branch_ids', 'in', branch_ids)]",
    )
    default_duration = fields.Float(string="Default Duration (Hours)", default=0.0)
    default_price = fields.Float(string="Default Price", default=0.0)

    def action_add_beauticians(self):
        existing_beautician_ids = self.product_tmpl_id.beautician_line_ids.mapped('beautician_id').ids
        vals_list = []
        for beautician in self.beautician_ids:
            if beautician.id not in existing_beautician_ids:
                vals_list.append({
                    'product_tmpl_id': self.product_tmpl_id.id,
                    'beautician_id': beautician.id,
                    'duration': self.default_duration,
                    'price': self.default_price,
                })
        if vals_list:
            self.env['product.beautician.line'].create(vals_list)
        return {'type': 'ir.actions.act_window_close'}