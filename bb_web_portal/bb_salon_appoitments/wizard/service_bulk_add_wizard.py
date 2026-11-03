from odoo import models, fields, api


class ServiceBulkAddWizard(models.TransientModel):
    _name = 'service.bulk.add.wizard'
    _description = 'Add Multiple Services to Beautician'

    beautician_id = fields.Many2one(
        'hr.employee',
        string="Beautician",
        required=True,
        readonly=True,
    )
    branch_ids = fields.Many2many(
        'beauty.branch',
        string="Branches",
        compute='_compute_branch_ids',
        readonly=True,
        help="Branches this beautician works at. Only services offered at "
             "these branches can be assigned.",
    )
    service_ids = fields.Many2many(
        'product.template',
        string="Services",
        domain="[('is_appointment_service', '=', True), ('branch_ids', 'in', branch_ids)]",
    )
    default_duration = fields.Float(string="Default Duration (Hours)", default=0.0)
    default_price = fields.Float(string="Default Price", default=0.0)

    @api.depends('beautician_id')
    def _compute_branch_ids(self):
        # A beautician works at their main branch plus any additional ones,
        # mirroring the branch domain used when picking beauticians on a service.
        for wizard in self:
            branches = wizard.beautician_id.beautician_branch_ids
            if wizard.beautician_id.branch_id:
                branches |= wizard.beautician_id.branch_id
            wizard.branch_ids = branches

    def action_add_services(self):
        """Create one beautician line per newly selected service.

        Services the beautician already performs are skipped, so running the
        wizard twice cannot produce duplicate lines.
        """
        self.ensure_one()
        existing_template_ids = self.env['product.beautician.line'].search([
            ('beautician_id', '=', self.beautician_id.id),
        ]).mapped('product_tmpl_id').ids
        vals_list = [{
            'product_tmpl_id': service.id,
            'beautician_id': self.beautician_id.id,
            'duration': self.default_duration,
            'price': self.default_price,
        } for service in self.service_ids if service.id not in existing_template_ids]
        if vals_list:
            self.env['product.beautician.line'].create(vals_list)
        return {'type': 'ir.actions.act_window_close'}
