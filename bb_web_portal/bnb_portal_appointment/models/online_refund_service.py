import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class OnlineRefundService(models.AbstractModel):
    """Carry a gateway refund/void of an online booking payment into Odoo.

    The refund itself is a child ``payment.transaction`` (operation ``refund``).
    Core already turns it into the outbound ``account.payment``; this service
    adds what core does not know about the booking: the payment line status,
    the refunded amounts shown on the appointment list, and the reversal of the
    customer-deposit reclassification entry.
    """
    _name = 'bb.online.refund.service'
    _description = 'Online booking refund handling'

    @api.model
    def apply_refund(self, refund_tx):
        """Apply one done refund transaction. Idempotent; returns True if applied."""
        refund_tx = refund_tx.sudo()
        refund_tx.ensure_one()
        source = refund_tx.source_transaction_id
        if (
            refund_tx.operation != 'refund'
            or refund_tx.state != 'done'
            or refund_tx.bnb_refund_applied
            or not source.bnb_booking_intent_id
        ):
            return False
        appointment = source.bnb_booking_intent_id.appointment_id
        if not appointment:
            return False

        currency = refund_tx.currency_id
        refund_amount = -refund_tx.amount
        bank_ref = source.provider_reference or ''
        payment = appointment.payment_line_ids.filtered(
            lambda p: p.payment_method == 'online'
            and p.transaction_id in (source.provider_reference, source.reference)
        )[:1]
        if not payment or currency.compare_amounts(refund_amount, 0) <= 0:
            return False

        try:
            with self.env.cr.savepoint():
                already = payment.refunded_amount or 0.0
                refunded = min(already + refund_amount, payment.payment_amount)
                fully_refunded = currency.compare_amounts(refunded, payment.payment_amount) >= 0
                # Only the amount this refund really added is reversed below.
                applied_amount = refunded - already
                vals = {
                    'refunded_amount': refunded,
                    'refund_date': fields.Datetime.now(),
                    'refund_reference': refund_tx.provider_reference or refund_tx.reference,
                }
                if fully_refunded:
                    vals['payment_status'] = 'refunded'
                payment.write(vals)
                self._reverse_deposit(appointment, bank_ref, applied_amount, fully_refunded, refund_tx)
                refund_tx.bnb_refund_applied = True
                appointment._update_payment_status()
                appointment.message_post(body=_(
                    "Online payment %(kind)s: %(amount).2f %(currency)s (gateway reference %(ref)s).",
                    kind=_("refunded") if fully_refunded else _("partially refunded"),
                    amount=applied_amount, currency=currency.name,
                    ref=vals['refund_reference'],
                ))
        except Exception:
            _logger.exception('Refund %s could not be applied to appointment %s',
                              refund_tx.reference, appointment.id)
            appointment.message_post(body=_(
                "A refund of %(amount).2f was made at the gateway (%(ref)s) but Odoo could not "
                "apply it to the booking. It will be retried automatically; if this message "
                "repeats, review the payment and deposit by hand.",
                amount=refund_amount, ref=refund_tx.provider_reference or refund_tx.reference,
            ))
            return False
        return True

    @api.model
    def _reverse_deposit(self, appointment, bank_ref, amount, fully_refunded, refund_tx):
        """Undo the deposit-liability reclassification for the refunded amount.

        Booking:  Dr Receivable / Cr Customer Deposit liability (the reclass).
        Refund:   the gateway refund payment credits the bank and debits
                  Receivable, so the reclass is reversed by Dr Deposit
                  liability / Cr Receivable.
        """
        Deposit = self.env['beauty.customer.deposit'].sudo()
        deposits = Deposit.search([
            ('appointment_id', '=', appointment.id),
            ('move_id', '!=', False),
        ])
        deposit = deposits.filtered(lambda d: bank_ref and bank_ref in (d.move_id.ref or ''))[:1]
        if not deposit and len(deposits) == 1:
            deposit = deposits
        if not deposit or deposit.currency_id.compare_amounts(amount, 0) <= 0:
            return
        move = deposit.move_id
        liability_line = move.line_ids.filtered(lambda l: l.credit > 0)[:1]
        receivable_line = move.line_ids.filtered(lambda l: l.debit > 0)[:1]
        if not liability_line or not receivable_line:
            return
        label = _("Online deposit refund - %s", refund_tx.provider_reference or refund_tx.reference)
        reversal = self.env['account.move'].sudo().create({
            'journal_id': move.journal_id.id,
            'date': fields.Date.context_today(self),
            'ref': label,
            'partner_id': deposit.partner_id.id,
            'company_id': move.company_id.id,
            'line_ids': [
                (0, 0, {
                    'name': label,
                    'account_id': liability_line.account_id.id,
                    'partner_id': deposit.partner_id.id,
                    'debit': amount,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'name': label,
                    'account_id': receivable_line.account_id.id,
                    'partner_id': deposit.partner_id.id,
                    'debit': 0.0,
                    'credit': amount,
                }),
            ],
        })
        reversal.action_post()
        if fully_refunded:
            deposit.action_refund_deposit(_("Online payment refunded at the gateway."))
        else:
            deposit.write({'credit_amount': max(0.0, deposit.credit_amount - amount)})
            deposit.message_post(body=_(
                "Partial online refund of %(amount).2f: usable credit reduced accordingly.",
                amount=amount,
            ))
        if 'online_refunded_amount' in deposit._fields:
            # The deposit was also rung into the register as a sale; queue the
            # matching negative order (posted now if the register is open).
            deposit.online_refunded_amount += amount
            deposit._bb_post_refunds_to_session()

    @api.model
    def _cron_apply_pending(self):
        """Retry refunds that were received but could not be applied."""
        pending = self.env['payment.transaction'].sudo().search([
            ('operation', '=', 'refund'),
            ('state', '=', 'done'),
            ('bnb_refund_applied', '=', False),
            ('source_transaction_id.bnb_booking_intent_id', '!=', False),
        ], limit=100)
        for refund_tx in pending:
            self.apply_refund(refund_tx)
