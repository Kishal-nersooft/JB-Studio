from odoo import _, api, fields, models
from odoo.exceptions import UserError


class BeautyCustomerDepositActionWizard(models.TransientModel):
    _name = 'beauty.customer.deposit.action.wizard'
    _description = 'Customer Deposit Action Wizard'

    deposit_id = fields.Many2one('beauty.customer.deposit', required=True, ondelete='cascade')
    appointment_ref = fields.Char(string='Appointment', readonly=True)
    branch_id = fields.Many2one('beauty.branch', string='Branch', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)
    action_type = fields.Selection([
        ('move_to_credit', 'Move to Credit'),
        ('cancel', 'Delete'),
        ('refund', 'Refund'),
        ('forfeit', 'Forfeit'),
    ], string='Action', required=True, default='move_to_credit')
    reason = fields.Text(string='Reason', required=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        deposit_id = res.get('deposit_id') or self.env.context.get('default_deposit_id')
        if deposit_id:
            deposit = self.env['beauty.customer.deposit'].browse(deposit_id)
            if deposit.exists():
                res.update({
                    'appointment_ref': deposit.appointment_ref,
                    'branch_id': deposit.branch_id.id if deposit.branch_id else False,
                    'company_id': deposit.company_id.id if deposit.company_id else False,
                })
        return res

    def action_confirm(self):
        self.ensure_one()
        deposit = self.deposit_id
        if not deposit:
            raise UserError(_('Deposit record not found.'))

        if self.action_type == 'move_to_credit':
            deposit.action_move_to_credit(self.reason)
        elif self.action_type == 'cancel':
            deposit.action_cancel_deposit(self.reason)
        elif self.action_type == 'refund':
            deposit.action_refund_deposit(self.reason)
        elif self.action_type == 'forfeit':
            deposit.action_forfeit_deposit(self.reason)
        return {'type': 'ir.actions.act_window_close'}
