from odoo import fields, models


class MailingContact(models.Model):
    _inherit = 'mailing.contact'

    bnb_phone = fields.Char(string='Phone')
    bnb_store_id = fields.Many2one('beauty.branch', string='Preferred Store', ondelete='set null')
