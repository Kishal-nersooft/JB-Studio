from odoo import _, fields, models


class BeautyCreditRedemption(models.Model):
    _name = 'beauty.credit.redemption'
    _description = 'Customer Account Credit Redemption'
    _order = 'redemption_date desc'

    company_id = fields.Many2one(
        'res.company', required=True,
        default=lambda self: self.env.company,
    )
    partner_id = fields.Many2one(
        'res.partner', required=True,
        ondelete='cascade', index=True,
        string='Customer',
    )
    beautician_id = fields.Many2one('hr.employee', string='Beautician')
    branch_id = fields.Many2one(
        'beauty.branch', string='Branch',
        domain="[('company_id', '=', company_id)]",
    )
    appointment_id = fields.Many2one(
        'salon.appointment', string='Appointment',
        ondelete='set null',
    )
    appointment_ref = fields.Char(related='appointment_id.appointment_ref', string='Appointment', readonly=True)
    pos_order_id = fields.Many2one(
        'pos.order', string='POS Order',
        ondelete='set null',
    )
    pos_order_ref = fields.Char(related='pos_order_id.name', string='POS Order', readonly=True)
    move_id = fields.Many2one('account.move', string='Journal Entry', readonly=True)
    amount = fields.Monetary(required=True, string='Amount Redeemed')
    credit_before = fields.Monetary(string='Credit Balance Before')
    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.company.currency_id,
    )
    redemption_date = fields.Datetime(
        string='Date',
        default=fields.Datetime.now,
        required=True,
    )
    expiry_date = fields.Date(string='Expiry Date')
    expiry_display = fields.Char(string='Expiry Date', compute='_compute_expiry_display')
    note = fields.Char(string='Note')
    movement_type = fields.Selection([
        ('redeem', 'Redeem'),
        ('credit', 'Credit'),
    ], string='Movement Type', default='redeem', required=True)
    state = fields.Selection([
        ('active', 'Active'),
        ('partial', 'Partial'),
        ('redeemed', 'Redeemed'),
        ('credited', 'Credited'),
    ], string='Status', default='redeemed', required=True)

    def _compute_expiry_display(self):
        for record in self:
            record.expiry_display = record.expiry_date or _('Never Expires')
