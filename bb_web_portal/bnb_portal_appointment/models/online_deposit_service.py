import logging
from odoo import fields, models
from odoo.exceptions import ValidationError
_logger = logging.getLogger(__name__)


class OnlineDepositService(models.AbstractModel):
    _name = "bb.online.deposit.service"
    _description = "Verified online booking deposits"

    def _create_online_deposit(self, appointment, payment_record, transaction):
        """Create beauty.customer.deposit and accounting journal entry
        for online payments — mirrors POS action_create_customer_deposits()"""

        customer = appointment.customer_id
        if not customer:
            return
        if payment_record and payment_record.payment_status != 'completed':
            return
        if transaction and transaction.state != 'done':
            return

        # Serialize confirmation requests for this appointment. The existing
        # deposit check is not sufficient when two gateway callbacks arrive at
        # the same time on separate database cursors.
        self.env.cr.execute(
            'SELECT id FROM salon_appointment WHERE id = %s FOR UPDATE',
            (appointment.id,),
        )

        # Check for existing deposit to avoid duplicates
        existing = self.env['beauty.customer.deposit'].sudo().search([
            ('appointment_id', '=', appointment.id),
            ('appointment_id.company_id', '=', appointment.company_id.id),
        ], limit=1)
        if existing:
            # A previous accounting attempt may have failed while the deposit
            # itself was preserved. Retry only the missing move.
            if not existing.move_id and transaction and transaction.state == 'done':
                deposit_product = self.env['product.product'].sudo().search([
                    ('product_tmpl_id.is_deposit_product', '=', True),
                    '|',
                    ('company_id', '=', False),
                    ('company_id', '=', appointment.company_id.id),
                ], limit=1)
                if deposit_product and existing.amount > 0:
                    try:
                        with self.env.cr.savepoint():
                            self._create_online_deposit_move(
                                existing,
                                appointment,
                                deposit_product,
                                existing.amount,
                                transaction,
                            )
                    except Exception:
                        if self.env.context.get('require_online_booking_accounting'):
                            raise
                        _logger.exception(
                            "[Online Deposit] Accounting move retry failed for deposit %s "
                            "(appointment %s)",
                            existing.id,
                            appointment.id,
                        )
            return

        deposit_amount = payment_record.payment_amount
        discount_amount = payment_record.discount_amount or 0
        # service_total stays the RAW/gross service price for display (so
        # staff see the real service value, not something already net of
        # discount). Balance/credit math uses net_service_total (gross minus
        # discount) instead — using the raw total there made balance_due
        # overstate what's owed by exactly the discount, so the POS checkout
        # screen asked the customer to pay the discount a second time.
        service_total = appointment.total_amount or 0
        deposit_product = self.env['product.product'].sudo().search([
            ('product_tmpl_id.is_deposit_product', '=', True),
            '|',
            ('company_id', '=', False),
            ('company_id', '=', appointment.company_id.id),
        ], limit=1)
        if not deposit_product or deposit_amount <= 0:
            if self.env.context.get('require_online_booking_accounting'):
                raise ValidationError('Configure an online deposit product and a positive deposit amount.')
            return

        payment_date = fields.Datetime.now()
        if transaction and transaction.create_date:
            payment_date = transaction.create_date

        allocation = self.env[
            'bb.appointment.pricing.service'
        ].calculate_deposit_allocation(
            service_total=service_total,
            discount_amount=discount_amount,
            deposit_amount=deposit_amount,
            payment_option=payment_record.payment_option,
        )

        deposit_vals = {
            'company_id': (appointment.branch_id.company_id or self.env.company).id,
            'branch_id': appointment.branch_id.id if appointment.branch_id else False,
            'partner_id': customer.id,
            'appointment_id': appointment.id,
            'payment_date': payment_date,
            'amount': deposit_amount,
            'currency_id': (appointment.branch_id.company_id.currency_id
                           or self.env.company.currency_id).id,
            'service_total': service_total,
            'discount_amount': discount_amount,
            'balance_due': allocation['balance_due'],
            'credit_amount': allocation['credit_amount'],
        }

        deposit = self.env['beauty.customer.deposit'].sudo().create(deposit_vals)

        # Create accounting journal entry (same as POS _create_deposit_move).
        # Use a savepoint so that accounting errors do not roll back the deposit record itself.
        try:
            with self.env.cr.savepoint():
                self._create_online_deposit_move(deposit, appointment, deposit_product, deposit_amount, transaction)
        except Exception:
            if self.env.context.get('require_online_booking_accounting'):
                raise
            _logger.exception(
                "[Online Deposit] Accounting move failed for deposit %s (appointment %s), "
                "deposit record preserved",
                deposit.id, appointment.id,
            )

        # An in-store deposit is a POS sale of the Deposit product, which is how
        # it reaches the register; the service order settles it later with a
        # matching negative line. Ring the online one in the same way so the two
        # behave alike. If the branch register is closed there is no session to
        # book it against, so it waits with no POS order and the session-open
        # hook picks it up.
        try:
            deposit._bb_post_to_session()
        except Exception:
            _logger.exception(
                "[Online Deposit] Could not post deposit %s to a POS session; "
                "it stays queued for the next one",
                deposit.id,
            )

    def _create_online_deposit_move(self, deposit, appointment, deposit_product, deposit_total, transaction=None):
        """Create accounting journal entry for online deposit payment
        Mirrors PosOrder._create_deposit_move().

        The gateway/bank transaction reference (transaction.provider_reference) is
        stamped onto the move ref and line labels so the entry can be identified
        and reconciled against the bank statement by that reference.
        """

        if deposit.move_id:
            return

        bank_ref = transaction.provider_reference if transaction else ''

        company = appointment.branch_id.company_id or self.env.company

        # The gateway's account.payment already records:
        #   Dr Outstanding Receipts / Cr Accounts Receivable.
        # Reclassify that customer credit as an advance-payment liability:
        #   Dr Accounts Receivable / Cr Customer Deposits.
        customer = deposit.partner_id or appointment.customer_id
        receivable_account = customer.with_company(company).property_account_receivable_id
        deposit_liability_account = self.env['account.account'].sudo().search(
            [
                ('is_deposit_liability_account', '=', True),
                '|',
                ('company_ids', '=', False),
                ('company_ids', 'in', company.id),
            ],
            limit=1
        )
        if not deposit_liability_account:
            deposit_liability_account = self.env['account.account'].sudo().search(
                [
                    ('is_customer_account', '=', True),
                    '|',
                    ('company_ids', '=', False),
                    ('company_ids', 'in', company.id),
                ],
                limit=1
            )

        if not receivable_account or not deposit_liability_account:
            if self.env.context.get('require_online_booking_accounting'):
                raise ValidationError('Configure customer receivable and deposit liability accounts.')
            return

        # Find journal
        journal = self.env['account.journal'].sudo().search(
            [('type', '=', 'sale'), ('company_id', '=', company.id)],
            limit=1
        )

        if not journal:
            if self.env.context.get('require_online_booking_accounting'):
                raise ValidationError('Configure a sales journal for online deposits.')
            return

        move_ref = f'Online Deposit - {appointment.appointment_ref or appointment.id}'
        line_suffix = ''
        if bank_ref:
            move_ref = f'{move_ref} | Bank Ref: {bank_ref}'
            line_suffix = f' - {bank_ref}'

        move = self.env['account.move'].sudo().create({
            'journal_id': journal.id,
            'date': fields.Date.context_today(self.env.user),
            'ref': move_ref,
            'partner_id': deposit.partner_id.id,
            'company_id': company.id,
            'line_ids': [
                (0, 0, {
                    'name': f'Customer Deposit Liability{line_suffix}',
                    'account_id': deposit_liability_account.id,
                    'partner_id': deposit.partner_id.id,
                    'debit': 0.0,
                    'credit': deposit_total,
                }),
                (0, 0, {
                    'name': f'Customer Receivable Reclassification{line_suffix}',
                    'account_id': receivable_account.id,
                    'partner_id': deposit.partner_id.id,
                    'debit': deposit_total,
                    'credit': 0.0,
                }),
            ],
        })
        move.action_post()
        deposit.sudo().write({'move_id': move.id})
