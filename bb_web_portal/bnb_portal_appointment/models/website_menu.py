from odoo import api, fields, models


class WebsiteMenu(models.Model):
    _inherit = 'website.menu'

    bnb_hide_from_navigation = fields.Boolean(
        string='Hide from navigation',
        help='Hide this menu and its submenu from website navigation without deleting the page.',
    )

    @api.depends('bnb_hide_from_navigation')
    def _compute_visible(self):
        super()._compute_visible()
        for menu in self.filtered('bnb_hide_from_navigation'):
            menu.is_visible = False
