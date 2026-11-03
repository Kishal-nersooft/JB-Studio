from odoo import _, fields, models
from odoo.exceptions import UserError


class BeautyIssueCreditWizard(models.TransientModel):
    _name = 'beauty.issue.credit.wizard'
    _description = 'Issue Customer Credit Wizard'

    partner_id = fields.Many2one('res.partner', string='Customer', required=True, readonly=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    branch_id = fields.Many2one(
        'beauty.branch',
        string='Branch',
        required=True,
        domain="[('company_id', '=', company_id)]",
    )
    beautician_id = fields.Many2one(
        'hr.employee',
        string='Beautician',
        domain="[('is_beautician', '=', True), ('company_id', '=', company_id)]",
    )
    amount = fields.Monetary(string='Credit Amount', required=True)
    currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
        readonly=True,
    )
    reason = fields.Text(string='Reason', required=True)
    expiry_date = fields.Date(string='Expiry Date', default=False)

    def action_confirm(self):
        self.ensure_one()
        if self.amount <= 0:
            raise UserError(_('Credit amount must be greater than zero.'))

        credit_before = self.partner_id.account_credit_balance
        credit_line = self.env['beauty.credit.redemption'].create({
            'partner_id': self.partner_id.id,
            'branch_id': self.branch_id.id,
            'beautician_id': self.beautician_id.id if self.beautician_id else False,
            'amount': self.amount,
            'credit_before': credit_before,
            'company_id': self.company_id.id,
            'currency_id': self.currency_id.id if self.currency_id else self.env.company.currency_id.id,
            'redemption_date': fields.Datetime.now(),
            'expiry_date': self.expiry_date,
            'note': self.reason,
            'movement_type': 'credit',
            'state': 'credited',
        })
        if hasattr(credit_line, '_create_issue_credit_move'):
            credit_line._create_issue_credit_move()
        self.partner_id.invalidate_recordset(['account_credit_balance'])
        return {'type': 'ir.actions.act_window_close'}
