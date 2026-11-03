"""A gateway refund of an online booking payment reaches the booking and the books."""
import json
from unittest.mock import Mock, patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

from .test_payment_first_checkout import PaymentFirstFixture


@tagged('post_install', '-at_install')
class TestOnlineRefund(PaymentFirstFixture, TransactionCase):

    def setUp(self):
        super().setUp()
        self.service = self.env['bb.online.refund.service']
        intent = self._intent()
        self.tx = self._tx(intent, provider_reference='BANK-REQ-1')
        self.tx._set_done()
        self.appointment = intent._finalize(self.tx)
        self.assertTrue(self.appointment, intent.review_reason)
        self.payment = self.appointment.payment_line_ids
        self.paid = self.payment.payment_amount

        company = self.env.company
        receivable = self.env['account.account'].search(
            [('account_type', '=', 'asset_receivable')], limit=1)
        liability = self.env['account.account'].search(
            [('account_type', '=', 'liability_current')], limit=1)
        journal = self.env['account.journal'].search(
            [('type', '=', 'general'), ('company_id', '=', company.id)], limit=1)
        customer = self.appointment.customer_id
        self.reclass = self.env['account.move'].create({
            'journal_id': journal.id, 'ref': 'Online Deposit - X | Bank Ref: BANK-REQ-1',
            'partner_id': customer.id,
            'line_ids': [
                (0, 0, {'name': 'liability', 'account_id': liability.id, 'partner_id': customer.id,
                        'debit': 0.0, 'credit': self.paid}),
                (0, 0, {'name': 'receivable', 'account_id': receivable.id, 'partner_id': customer.id,
                        'debit': self.paid, 'credit': 0.0}),
            ],
        })
        self.reclass.action_post()
        self.deposit = self.env['beauty.customer.deposit'].sudo().create({
            'company_id': company.id, 'partner_id': customer.id, 'appointment_id': self.appointment.id,
            'amount': self.paid, 'credit_amount': self.paid, 'currency_id': company.currency_id.id,
            'move_id': self.reclass.id,
        })
        self.liability = liability

    def _refund(self, amount, reference):
        refund = self.tx._create_child_transaction(amount, is_refund=True)
        refund.provider_reference = reference
        refund._set_done()
        return refund

    def _reversals(self):
        return self.env['account.move'].search([('ref', 'like', 'Online deposit refund')])

    def test_full_refund_updates_booking_and_reverses_the_reclass(self):
        refund = self._refund(self.paid, 'REFUND-REQ-1')
        self.assertTrue(self.service.apply_refund(refund))

        self.assertEqual(self.payment.payment_status, 'refunded')
        self.assertEqual(self.payment.refunded_amount, self.paid)
        self.assertEqual(self.payment.refund_reference, 'REFUND-REQ-1')
        self.assertEqual(self.appointment.online_payment_receipt_status, 'refunded')
        self.assertEqual(self.appointment.online_refunded_amount, self.paid)
        self.assertEqual(self.deposit.state, 'refunded')
        reversal = self._reversals()
        self.assertEqual(len(reversal), 1)
        self.assertEqual(reversal.state, 'posted')
        self.assertEqual(sum(reversal.line_ids.filtered(
            lambda l: l.account_id == self.liability).mapped('debit')), self.paid)
        self.assertTrue(refund.bnb_refund_applied)

    def test_refund_is_applied_once(self):
        refund = self._refund(self.paid, 'REFUND-REQ-1')
        self.assertTrue(self.service.apply_refund(refund))
        self.assertFalse(self.service.apply_refund(refund))
        self.assertEqual(len(self._reversals()), 1)
        self.assertEqual(self.payment.refunded_amount, self.paid)

    def test_partial_refund_keeps_booking_paid_and_reduces_credit(self):
        refund = self._refund(30.0, 'REFUND-REQ-2')
        self.assertTrue(self.service.apply_refund(refund))

        self.assertEqual(self.payment.payment_status, 'completed')
        self.assertEqual(self.payment.refunded_amount, 30.0)
        self.assertEqual(self.appointment.online_payment_receipt_status, 'refunded')
        self.assertEqual(self.appointment.online_refunded_amount, 30.0)
        self.assertEqual(self.deposit.state, 'active')
        self.assertEqual(self.deposit.credit_amount, self.paid - 30.0)
        self.assertEqual(sum(self._reversals().line_ids.filtered(
            lambda l: l.account_id == self.liability).mapped('debit')), 30.0)

    def test_two_partial_refunds_then_the_rest_fully_refund(self):
        for amount, ref in ((30.0, 'R-A'), (self.paid - 30.0, 'R-B')):
            self.assertTrue(self.service.apply_refund(self._refund(amount, ref)))
        self.assertEqual(self.payment.payment_status, 'refunded')
        self.assertEqual(self.payment.refunded_amount, self.paid)
        self.assertEqual(self.appointment.online_payment_receipt_status, 'refunded')
        self.assertEqual(self.deposit.state, 'refunded')
        self.assertEqual(sum(self._reversals().line_ids.filtered(
            lambda l: l.account_id == self.liability).mapped('debit')), self.paid)

    def test_pending_refund_changes_nothing(self):
        refund = self.tx._create_child_transaction(self.paid, is_refund=True)
        self.assertFalse(self.service.apply_refund(refund))
        self.assertEqual(self.payment.payment_status, 'completed')
        self.assertFalse(self.payment.refunded_amount)

    def test_post_processing_applies_the_refund(self):
        refund = self._refund(self.paid, 'REFUND-REQ-3')
        with patch.object(type(refund), '_create_payment'):
            refund._post_process()
        self.assertTrue(refund.bnb_refund_applied)
        self.assertEqual(self.appointment.online_payment_receipt_status, 'refunded')
        self.assertEqual(fields.Date.today(), self._reversals().date)

    def test_nab_portal_void_updates_the_receipt_and_deposit_once(self):
        from odoo.addons.payment_nab_gateway import const
        from odoo.addons.payment_nab_gateway.models import payment_provider as nab_module
        self.provider.write({'code':'nab_gateway', 'nab_merchant_id':'testmerchant',
                             'nab_auth_type':'http_signature', 'nab_shared_secret_key':'dGVzdHNlY3JldA=='})
        def gateway(method, url, **kw):
            if url.endswith(const.NAB_SEARCH_PATH):
                self.assertEqual(kw['headers']['Accept'], const.NAB_SEARCH_ACCEPT)
                payload = {'_embedded':{'transactionSummaries':[{'id':'NAB-PORTAL-VOID'}]}}
            else:
                self.assertEqual(method, 'GET')
                self.assertTrue(url.endswith('/tss/v2/transactions/NAB-PORTAL-VOID'))
                payload = {'rootId':self.tx.provider_reference,
                    'applicationInformation':{'applications':[{'name':'ics_void'}]}}
            return Mock(status_code=200, text=json.dumps(payload), json=Mock(return_value=payload))
        with patch.object(nab_module.requests, 'request', side_effect=gateway) as send, \
                patch.object(type(self.tx), '_create_payment'):
            self.provider.action_nab_sync_refunds()
            self.provider.action_nab_sync_refunds()
        self.assertEqual(self.appointment.online_payment_receipt_status, 'refunded')
        self.assertEqual(self.payment.payment_status, 'refunded')
        self.assertEqual(self.payment.refunded_amount, self.paid)
        self.assertEqual(self.deposit.state, 'refunded')
        self.assertEqual(len(self.tx.child_transaction_ids), 1)
        self.assertEqual(len(self._reversals()), 1)
        self.assertEqual(send.call_count, 3)
