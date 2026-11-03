from odoo import models, fields


class BeautyLocationArea(models.Model):
    _name = 'beauty.location.area'
    _description = 'Beauty Location Area'

    name = fields.Char('Area Name', required=True)
    branch_id = fields.Many2one(
        'beauty.branch',
        string='Branch',
        required=True,
        ondelete='cascade',
        domain=lambda self: [('company_id', '=', self.env.company.id)],
    )
