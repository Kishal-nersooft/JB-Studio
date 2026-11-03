from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    block_external_emails_during_testing = fields.Boolean(
        string='Block Customer Emails During Testing',
        config_parameter='bb_salon_appoitments.block_external_emails_during_testing',
        default=False,
        help=(
            'Cancel emails addressed only to customers or other external recipients. '
            'Active employees and Odoo users continue to receive email notifications.'
        ),
    )
