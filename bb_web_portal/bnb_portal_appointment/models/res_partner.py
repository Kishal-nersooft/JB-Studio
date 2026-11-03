from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    apple_signin_sub = fields.Char(
        string='Apple Sign-In User ID',
        index=True,
        copy=False,
        help='Stable, app-scoped user identifier returned by Sign in with Apple.',
    )
    apple_signin_first_name = fields.Char(copy=False)
    apple_signin_last_name = fields.Char(copy=False)

    _apple_signin_sub_unique = models.Constraint(
        'UNIQUE(apple_signin_sub)',
        'This Apple Sign-In account is already linked to another customer.',
    )
