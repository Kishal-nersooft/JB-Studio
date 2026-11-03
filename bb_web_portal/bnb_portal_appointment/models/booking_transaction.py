import logging
import psycopg2
from odoo import api, fields, models, SUPERUSER_ID
from odoo.modules.registry import Registry

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    bnb_booking_intent_id = fields.Many2one(
        'bb.online.booking.intent', readonly=True, copy=False, index=True, ondelete='restrict')
    _bnb_checkout_transaction_unique = models.Constraint(
        'unique(bnb_booking_intent_id)', 'This checkout already has a payment transaction.')
    bnb_refund_applied = fields.Boolean(
        string='Refund applied to booking', readonly=True, copy=False,
        help='Set once this refund has updated the booking payment and deposit.')

    def _post_process(self):
        # Accounting must use the real customer, never the public partner.
        checkout_txs = self.filtered('bnb_booking_intent_id')
        result = super(PaymentTransaction, self - checkout_txs)._post_process()
        for tx in checkout_txs:
            if tx.state != 'done':
                super(PaymentTransaction, tx)._post_process()
                continue
            intent = tx.bnb_booking_intent_id
            try:
                with self.env.cr.savepoint():
                    appointment = intent._finalize(tx)
            except psycopg2.OperationalError:
                raise
            except Exception:
                _logger.exception('Verified payment %s could not be finalized', tx.reference)
                intent._mark_review('Payment received but verification or booking failed. Check the transaction before arranging a booking or refund.')
                continue
            if not appointment:
                continue
            try:
                with self.env.cr.savepoint():
                    super(PaymentTransaction, tx)._post_process()
                    payment = appointment.payment_line_ids.filtered(lambda p: p.payment_status == 'completed')[:1]
                    self.env['bb.online.deposit.service'].with_company(tx.company_id).with_context(require_online_booking_accounting=True)._create_online_deposit(appointment, payment, tx)
            except psycopg2.OperationalError:
                raise
            except Exception:
                # Keep the paid booking and transaction. Recovery retries the
                # missing accounting without making another customer or booking.
                _logger.exception('Accounting deferred for paid checkout %s', intent.name)
                tx.is_post_processed = False
                intent._mark_review('Booking saved and payment received; accounting needs attention. Please review this transaction.')
                continue
            if intent.state != 'paid':
                intent.write({'state': 'paid', 'review_reason': False})
                intent.activity_ids.action_feedback(feedback='Payment processing recovered.')
        for refund_tx in self.filtered(lambda t: t.operation == 'refund' and t.state == 'done'):
            self.env['bb.online.refund.service'].apply_refund(refund_tx)
        return result


class OnlineGatewaySubmission(models.Model):
    _name = 'bb.online.gateway.submission'
    _description = 'Online payment submission safeguard'

    transaction_id = fields.Many2one('payment.transaction', required=True, ondelete='restrict', index=True)
    _transaction_unique = models.Constraint('unique(transaction_id)', 'Payment has already been submitted.')

    @api.model
    def _claim(self, transaction_id):
        """Persist the at-most-once claim before an irreversible gateway call.

        Use a separate cursor deliberately: request retries must not roll this
        marker back and submit a second charge. This record contains no payer
        data and is kept with the financial transaction for reconciliation.
        """
        with Registry(self.env.cr.dbname).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            try:
                with cr.savepoint():
                    env[self._name].create({'transaction_id': transaction_id})
            except psycopg2.IntegrityError:
                return False
        return True
