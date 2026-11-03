from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CustomerDeposit(models.Model):
    _name = 'beauty.customer.deposit'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Customer Deposit'
    _order = 'payment_date desc, id desc'

    company_id = fields.Many2one('res.company', string='Company', required=True,
                                  default=lambda self: self.env.company)
    partner_id = fields.Many2one('res.partner', string='Customer', required=True, ondelete='cascade')
    branch_id = fields.Many2one(
        'beauty.branch',
        string='Branch',
        ondelete='set null',
        domain="[('company_id', '=', company_id)]",
    )
    appointment_id = fields.Many2one('salon.appointment', string='Appointment')
    payment_date = fields.Datetime(string='Payment Date', default=fields.Datetime.now, required=True, tracking=True)
    amount = fields.Monetary(string='Amount', required=True, tracking=True)
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        required=True,
        default=lambda self: self.env.company.currency_id
    )
    pos_payment_method_id = fields.Many2one('pos.payment.method', string='Payment Method')
    pos_order_id = fields.Many2one('pos.order', string='POS Order')
    move_id = fields.Many2one('account.move', string='Journal Entry', readonly=True)
    appointment_ref = fields.Char(related='appointment_id.appointment_ref', string='Appointment', readonly=True)
    pos_order_ref = fields.Char(related='pos_order_id.name', string='POS Order', readonly=True)
    service_total = fields.Monetary(string='Service Total', tracking=True)
    service_total_display = fields.Monetary(
        string='Service Total',
        compute='_compute_service_total_display',
    )
    discount_amount = fields.Monetary(
        string='Discount',
        tracking=True,
        help='Discount already applied when this deposit/payment was taken '
             '(e.g. a promo code used at online checkout). service_total and '
             'balance_due are net of this amount, so the branch does not ask '
             'the customer to pay the discount back at checkout.',
    )
    balance_due = fields.Monetary(string='Balance Due', tracking=True)
    credit_amount = fields.Monetary(string='Credit Amount', tracking=True)
    state = fields.Selection([
        ('active', 'Active'),
        ('partial', 'Partial'),
        ('credited', 'Credited'),
        ('redeemed', 'Redeemed'),
        ('cancelled', 'Cancelled'),
        ('refunded', 'Refunded'),
        ('forfeited', 'Forfeited'),
    ], string='Status', default='active', required=True, tracking=True)
    action_reason = fields.Text(string='Reason', tracking=True)
    parent_deposit_id = fields.Many2one(
        'beauty.customer.deposit', string='Original Deposit',
        ondelete='cascade', index=True,
        help='Set on a "Redeemed" ledger line; points back to the deposit it was claimed from.',
    )

    @api.depends('service_total', 'appointment_id.services_total', 'appointment_id.total_amount')
    def _compute_service_total_display(self):
        for record in self:
            record.service_total_display = (
                record.service_total
                or record.appointment_id.services_total
                or record.appointment_id.total_amount
                or 0.0
            )

    def action_open_deposit_action_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Deposit Action'),
            'res_model': 'beauty.customer.deposit.action.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_deposit_id': self.id,
            },
        }

    def _get_used_amount(self):
        self.ensure_one()
        redeemed_children = self.env['beauty.customer.deposit'].search([
            ('parent_deposit_id', '=', self.id),
        ])
        if redeemed_children:
            return sum(redeemed_children.mapped('amount'))
        if not self.service_total:
            return 0.0
        return max(self.service_total - self.balance_due, 0.0)

    def _apply_partial_redemption(self, redeemed_amount):
        """Partially redeem this deposit.

        Keep the original line as 'partial' with the remaining balance in
        ``balance_due``, and maintain a single child 'redeemed' ledger line
        (linked via ``parent_deposit_id``) for the amount actually claimed.
        Both lines share the same appointment. Idempotent — re-running just
        updates the same child line instead of adding another.
        """
        self.ensure_one()
        if self.parent_deposit_id:
            # A redeemed child line is never itself partially redeemed.
            return
        redeemed_amount = max(redeemed_amount or 0.0, 0.0)
        remaining = max(self.amount - redeemed_amount, 0.0)
        self.write({
            'state': 'partial',
            'balance_due': remaining,
        })
        child = self.env['beauty.customer.deposit'].search(
            [('parent_deposit_id', '=', self.id)], limit=1
        )
        child_vals = {'amount': redeemed_amount, 'state': 'redeemed'}
        if child:
            child.write(child_vals)
        else:
            child = self.env['beauty.customer.deposit'].create({
                'parent_deposit_id': self.id,
                'company_id': self.company_id.id,
                'partner_id': self.partner_id.id,
                'branch_id': self.branch_id.id if self.branch_id else False,
                'appointment_id': self.appointment_id.id if self.appointment_id else False,
                'pos_order_id': self.pos_order_id.id if self.pos_order_id else False,
                'currency_id': self.currency_id.id,
                'payment_date': self.payment_date,
                **child_vals,
            })
        # Post the redemption journal entry for the claimed amount on the child
        # "Redeemed" line: Dr Deposit Liability / Cr Deposit Income.
        if (
            child
            and not child.move_id
            and not self.env.context.get('skip_deposit_redemption_move')
            and hasattr(child, '_create_redemption_move')
        ):
            redemption_move = child._create_redemption_move(redeemed_amount)
            if redemption_move:
                child.move_id = redemption_move.id

    def _post_detach_message(self, action_label, reason, amount=None):
        self.ensure_one()
        actor = self.env.user.display_name or self.env.user.name or _('Unknown User')
        amount_text = ''
        if amount is not None:
            amount_text = _('<br/><b>Amount:</b> %s') % (
                self.currency_id.symbol and f"{self.currency_id.symbol} {amount:.2f}" or f"{amount:.2f}"
            )
        body = _(
            "<b>Deposit Detach Action</b><br/>"
            "<b>User:</b> %s<br/>"
            "<b>Action:</b> %s%s<br/>"
            "<b>Reason:</b> %s"
        ) % (actor, action_label, amount_text, reason or '-')
        self.message_post(body=body)

    def action_move_to_credit(self, reason):
        self.ensure_one()
        remaining_amount = max(self.amount - self._get_used_amount(), 0.0)
        if remaining_amount <= 0.001:
            raise UserError(_('No remaining deposit amount is available to move to credit.'))

        credit_before = self.partner_id.account_credit_balance
        self.write({
            'credit_amount': remaining_amount,
            'state': 'credited',
            'action_reason': reason,
        })
        self.env['beauty.credit.redemption'].create({
            'partner_id': self.partner_id.id,
            'branch_id': self.branch_id.id if self.branch_id else False,
            'appointment_id': self.appointment_id.id if self.appointment_id else False,
            'pos_order_id': self.pos_order_id.id if self.pos_order_id else False,
            'amount': remaining_amount,
            'credit_before': credit_before,
            'company_id': self.company_id.id,
            'currency_id': self.currency_id.id,
            'redemption_date': fields.Datetime.now(),
            'note': reason,
            'movement_type': 'credit',
            'state': 'credited',
        })
        self._post_detach_message(_('Move to Credit'), reason, remaining_amount)

    def action_cancel_deposit(self, reason):
        self.ensure_one()
        if self.appointment_id and self.appointment_id.state != 'cancelled':
            self.appointment_id.write({'state': 'cancelled'})
        self.write({
            'state': 'cancelled',
            'action_reason': reason,
            'credit_amount': 0.0,
        })
        self._post_detach_message(_('Delete'), reason)

    def action_refund_deposit(self, reason):
        self.ensure_one()
        self.write({
            'state': 'refunded',
            'action_reason': reason,
            'credit_amount': 0.0,
        })
        self._post_detach_message(_('Refund'), reason)

    def action_forfeit_deposit(self, reason):
        self.ensure_one()
        self.write({
            'state': 'forfeited',
            'action_reason': reason,
            'credit_amount': 0.0,
        })
        self._post_detach_message(_('Forfeit'), reason)
