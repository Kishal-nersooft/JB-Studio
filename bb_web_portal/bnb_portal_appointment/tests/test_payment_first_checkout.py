"""Payment-first acceptance tests. Provider calls are mocked; no real charges."""
import json
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged


class PaymentFirstFixture:
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.website = cls.env['website'].search([('company_id', '=', cls.env.company.id)], limit=1)
        config = cls.env['pos.config'].create({'name': 'Payment first test POS', 'company_id': cls.env.company.id,
                                              'payment_method_ids': [(6, 0, [])]})
        cls.branch = cls.env['beauty.branch'].create({
            'name': 'Payment first test branch', 'company_id': cls.env.company.id,
            'website_id': cls.website.id, 'pos_config_id': config.id, 'tz': 'UTC',
            'work_start_hour': 8, 'work_end_hour': 20, 'booking_fee': 10,
            'saturday_surcharge_percent': 0.1, 'sunday_surcharge_percent': 0.15,
        })
        cls.staff = cls.env['hr.employee'].create({'name': 'Payment first professional',
            'company_id': cls.env.company.id, 'is_beautician': True,
            'branch_id': cls.branch.id, 'beautician_branch_ids': [(6, 0, cls.branch.ids)]})
        cls.product = cls.env['product.product'].create({'name': 'Payment first service', 'type': 'service',
            'is_appointment_service': True, 'duration': 1, 'list_price': 100,
            'company_id': cls.env.company.id, 'branch_ids': [(6, 0, cls.branch.ids)]})
        cls.env['product.beautician.line'].create({'product_tmpl_id': cls.product.product_tmpl_id.id,
            'beautician_id': cls.staff.id, 'duration': 1, 'price': 20})
        cls.day = fields.Date.today() + timedelta(days=7)
        while cls.day.weekday() != 0:
            cls.day += timedelta(days=1)
        if 'employee.roster' in cls.env:
            roster = cls.env['employee.roster'].create({'employee_id': cls.staff.id, 'branch_id': cls.branch.id,
                'month': cls.day.month, 'year': cls.day.year})
            cls.env['employee.roster.line'].create({'roster_id': roster.id, 'date': cls.day,
                'is_working': True, 'start_time': '08:00', 'end_time': '20:00'})
        cls.provider = cls.env['payment.provider'].create({'name': 'Payment first test provider',
            'code': 'none', 'state': 'test', 'company_id': cls.env.company.id,
            'payment_method_ids': [(6, 0, cls.env.ref('payment.payment_method_card').ids)]})
        # Card ships inactive; a real provider module's post_init_hook turns it
        # on once it links a provider to it. Nothing does that for this dummy
        # test provider, so activate it ourselves -- now that cls.provider
        # above links to it, core's own guard (needs a non-disabled provider)
        # is satisfied -- or the compatibility check never finds a method.
        cls.env.ref('payment.payment_method_card').sudo().active = True
        cls.env.ref('payment.payment_method_card').active = True
        cls.Intent = cls.env['bb.online.booking.intent'].sudo()

    def _form(self, **updates):
        values = {'first_name': 'Payment', 'last_name': 'Customer', 'email': 'payment.first@example.invalid',
            'mobile_phone': '+61400000991', 'pronouns': '', 'salon_id': str(self.branch.id),
            'appointment_date': str(self.day), 'selected_services': json.dumps([self.product.id]),
            'selected_beauticians': json.dumps({str(self.product.id): self.staff.id}),
            'selected_timeslots': json.dumps({'slot': {'start_hour': 10}}),
            'payment_option': 'full', 'agree_policy': 'on', 'remember_me': 'on',
            'billing_address': '1 Test Street', 'city': 'Sydney', 'postcode': '2000'}
        values.update(updates)
        return values

    def _intent(self, **updates):
        return self.Intent.create(self.Intent._prepare(self._form(**updates), self.branch, self.website))

    def _tx(self, intent, **updates):
        values = {'provider_id': self.provider.id, 'payment_method_id': self.env.ref('payment.payment_method_card').id,
            'reference': intent.name, 'amount': intent.amount, 'currency_id': intent.currency_id.id,
            'partner_id': self.website.user_id.partner_id.id, 'operation': 'online_direct',
            'bnb_booking_intent_id': intent.id}
        values.update(updates)
        return self.env['payment.transaction'].sudo().create(values)

    def _second_staff_service(self):
        staff = self.env['hr.employee'].create({
            'name': 'Payment first second professional',
            'company_id': self.env.company.id,
            'is_beautician': True,
            'branch_id': self.branch.id,
            'beautician_branch_ids': [(6, 0, self.branch.ids)],
        })
        service = self.env['product.product'].create({
            'name': 'Payment first second service',
            'type': 'service',
            'is_appointment_service': True,
            'duration': 0.5,
            'list_price': 50,
            'company_id': self.env.company.id,
            'branch_ids': [(6, 0, self.branch.ids)],
        })
        self.env['product.beautician.line'].create({
            'product_tmpl_id': service.product_tmpl_id.id,
            'beautician_id': staff.id,
            'duration': 0.5,
            'price': 0,
        })
        if 'employee.roster' in self.env:
            roster = self.env['employee.roster'].create({
                'employee_id': staff.id,
                'branch_id': self.branch.id,
                'month': self.day.month,
                'year': self.day.year,
            })
            self.env['employee.roster.line'].create({
                'roster_id': roster.id,
                'date': self.day,
                'is_working': True,
                'start_time': '08:00',
                'end_time': '20:00',
            })
        return staff, service

    def _counts(self):
        return (self.env['res.partner'].search_count([]), self.env['salon.appointment'].search_count([]))


@tagged('post_install', '-at_install')
class TestPaymentFirstCheckout(PaymentFirstFixture, TransactionCase):
    def test_checkout_creates_neither_customer_nor_appointment(self):
        before = self._counts()
        intent = self._intent()
        self._tx(intent)
        self.assertEqual(self._counts(), before)
        self.assertFalse(intent.appointment_id)

    def test_half_and_full_amounts_are_server_calculated(self):
        for option, expected in [('half', 65), ('full', 130)]:
            quote = self.Intent._prepare(self._form(payment_option=option, amount_to_pay='0.01', discount_amount='9999'), self.branch, self.website)
            self.assertEqual(quote['amount'], expected)
            self.assertEqual(quote['payload']['totals']['total_after_discount'], 130)

    def test_weekend_totals_preserve_existing_pricing(self):
        pricing = self.env['bb.appointment.pricing.service']
        for offset, surcharge, expected in [(5, .1, 142), (6, .15, 148)]:
            day = self.day + timedelta(days=offset)
            values = pricing.calculate_service_totals(120, day, .1, .15)
            self.assertEqual(values['total_amount'], 120 * (1 + surcharge))
            self.assertAlmostEqual(pricing.calculate_checkout_totals(values['total_amount'], 10)['payment_amount'], expected)

    def test_full_payment_creates_one_customer_and_one_booking(self):
        intent = self._intent()
        before = self._counts()
        tx = self._tx(intent)
        tx._set_done()
        appointment = intent._finalize(tx)
        self.assertTrue(appointment, intent.review_reason)
        self.assertEqual(self._counts(), (before[0] + 1, before[1] + 1))
        self.assertEqual(appointment.state, 'draft')  # Staff still confirm arrival manually.
        self.assertTrue(appointment.booked_online)
        self.assertEqual(appointment.customer_id, tx.partner_id)
        self.assertEqual(appointment.total_amount, 120)
        self.assertEqual(appointment.payment_line_ids.payment_amount, 130)
        self.assertEqual(appointment.payment_line_ids.payment_status, 'completed')
        self.assertEqual(appointment.payment_line_ids.payment_option, 'full')
        # The payment source is the real provider and method, not the legacy default.
        self.assertEqual(appointment.payment_line_ids.payment_provider,
                         'Payment first test provider - Card')

    def test_half_payment_creates_booking_with_half_paid(self):
        intent = self._intent(payment_option='half')
        tx = self._tx(intent)
        tx._set_done()
        appointment = intent._finalize(tx)
        self.assertTrue(appointment, intent.review_reason)
        self.assertEqual(appointment.payment_line_ids.payment_amount, 65)
        self.assertEqual(appointment.payment_line_ids.payment_option, 'half')

    def test_pending_payment_cannot_create_records(self):
        intent = self._intent()
        tx = self._tx(intent)
        tx._set_pending()
        before = self._counts()
        with self.assertRaises(ValidationError):
            intent._finalize(tx)
        self.assertEqual(self._counts(), before)

    def test_cancelled_payment_cannot_create_records(self):
        intent = self._intent()
        tx = self._tx(intent)
        tx._set_canceled()
        before = self._counts()
        with self.assertRaises(ValidationError):
            intent._finalize(tx)
        self.assertEqual(self._counts(), before)

    def test_declined_payment_cannot_create_records(self):
        intent = self._intent()
        tx = self._tx(intent)
        tx._set_error('Declined')
        before = self._counts()
        with self.assertRaises(ValidationError):
            intent._finalize(tx)
        self.assertEqual(self._counts(), before)

    def test_wrong_amount_cannot_create_records(self):
        intent = self._intent()
        tx = self._tx(intent, amount=1)
        tx._set_done()
        before = self._counts()
        with self.assertRaises(ValidationError):
            intent._finalize(tx)
        self.assertEqual(self._counts(), before)

    def test_wrong_currency_cannot_create_records(self):
        intent = self._intent()
        other = self.env['res.currency'].with_context(active_test=False).search([('id', '!=', intent.currency_id.id)], limit=1)
        tx = self._tx(intent, currency_id=other.id)
        tx._set_done()
        with self.assertRaises(ValidationError):
            intent._finalize(tx)
        self.assertFalse(intent.appointment_id)

    def test_unrelated_transaction_cannot_finalize_checkout(self):
        intent = self._intent()
        tx = self._tx(intent, bnb_booking_intent_id=False)
        tx._set_done()
        with self.assertRaises(ValidationError):
            intent._finalize(tx)

    def test_repeated_success_is_idempotent(self):
        intent = self._intent()
        tx = self._tx(intent)
        tx._set_done()
        appointment = intent._finalize(tx)
        self.assertTrue(appointment, intent.review_reason)
        before = self._counts()
        self.assertEqual(intent._finalize(tx), appointment)
        self.assertEqual(self._counts(), before)
        self.assertEqual(len(appointment.payment_line_ids), 1)

    def test_existing_customer_reused_without_overwriting_details(self):
        customer = self.env['res.partner'].create({'name': 'Existing Name', 'email': 'payment.first@example.invalid',
            'phone': 'Original phone', 'company_id': self.env.company.id})
        intent = self._intent()
        tx = self._tx(intent)
        before = self._counts()[0]
        tx._set_done()
        appointment = intent._finalize(tx)
        self.assertTrue(appointment, intent.review_reason)
        self.assertEqual(appointment.customer_id, customer)
        self.assertEqual(self._counts()[0], before)
        self.assertEqual(customer.name, 'Existing Name')
        self.assertEqual(customer.phone, 'Original phone')

    def test_expired_checkout_without_payment_is_removed(self):
        intent = self._intent()
        before = self._counts()
        intent.write({'expires_at': fields.Datetime.now() - timedelta(days=2)})
        self.Intent._cron_checkout_maintenance()
        self.assertFalse(intent.exists())
        self.assertEqual(self._counts(), before)

    def test_payment_evidence_is_never_deleted_by_cleanup(self):
        intent = self._intent()
        self._tx(intent)._set_error('Declined')
        intent.write({'expires_at': fields.Datetime.now() - timedelta(days=2)})
        self.Intent._cron_checkout_maintenance()
        self.assertTrue(intent.exists())
        self.assertTrue(intent.transaction_ids)
        self.assertEqual(intent.state, 'expired')

    def test_live_checkout_holds_staff_slot(self):
        self._intent()
        with self.assertRaises(ValidationError):
            self._intent(email='another@example.invalid')

    def test_hold_by_another_customer_says_so(self):
        self._intent()
        with self.assertRaises(ValidationError) as caught:
            self._intent(email='another@example.invalid')
        self.assertIn('held by another customer', str(caught.exception))

    def test_failed_payment_releases_the_slot_for_anyone(self):
        intent = self._intent()
        self._tx(intent)._set_error('declined')
        self.assertTrue(self._intent(email='another@example.invalid'))

    def test_cancelled_payment_releases_the_slot(self):
        intent = self._intent()
        self._tx(intent)._set_canceled()
        self.assertTrue(self._intent(email='another@example.invalid'))

    def test_same_customer_can_retry_after_an_unstarted_attempt(self):
        # e.g. the first page was abandoned and the retry comes from a new session.
        self._intent()
        retry = self._intent()
        self.assertTrue(retry)
        retry._validate_slot()

    def test_same_customer_retry_after_a_transaction_that_never_reached_the_gateway(self):
        first = self._intent()
        self._tx(first)  # draft transaction, no gateway submission
        retry = self._intent()
        retry._validate_slot()

    def test_payment_in_flight_still_holds_the_slot_for_the_same_customer(self):
        first = self._intent()
        self._tx(first)._set_pending()
        with self.assertRaises(ValidationError):
            self._intent()

    def test_submitted_payment_still_holds_the_slot_for_the_same_customer(self):
        first = self._intent()
        tx = self._tx(first)
        # _claim() writes through its own cursor, which cannot see this test's
        # uncommitted transaction; create the same record directly.
        self.env['bb.online.gateway.submission'].create({'transaction_id': tx.id})
        with self.assertRaises(ValidationError):
            self._intent()

    def test_expired_checkout_releases_staff_slot(self):
        intent = self._intent()
        intent.write({'expires_at': fields.Datetime.now() - timedelta(minutes=1)})
        self.assertTrue(self._intent(email='another@example.invalid'))

    def test_paid_late_conflict_is_visible_without_orphan_customer(self):
        intent = self._intent()
        tx = self._tx(intent)
        intent.write({'expires_at': fields.Datetime.now() - timedelta(minutes=1)})
        self._intent(email='another@example.invalid')
        tx._set_done()
        before = self._counts()
        self.assertFalse(intent._finalize(tx))
        self.assertEqual(intent.state, 'review')
        self.assertEqual(self._counts(), before)
        self.assertEqual(tx.state, 'done')

    def test_paid_late_without_conflict_can_still_book(self):
        intent = self._intent()
        tx = self._tx(intent)
        intent.write({'expires_at': fields.Datetime.now() - timedelta(minutes=1)})
        tx._set_done()
        self.assertTrue(intent._finalize(tx), intent.review_reason)

    def test_post_processing_works_without_browser_return(self):
        intent = self._intent()
        tx = self._tx(intent)
        tx._set_done()
        with patch.object(type(tx), '_create_payment'), patch.object(type(self.env['bb.online.deposit.service']), '_create_online_deposit') as deposit:
            tx._post_process()
        self.assertTrue(intent.appointment_id, intent.review_reason)
        self.assertEqual(tx.partner_id, intent.appointment_id.customer_id)
        deposit.assert_called_once()

    def test_invalid_inputs_never_create_records(self):
        before = self._counts()
        for values in [{'agree_policy': 'off'}, {'email': 'invalid'}, {'payment_option': 'later'},
                       {'selected_services': '[]'}, {'selected_services': '{}'},
                       {'selected_timeslots': '{"slot": {"start_hour": "NaN"}}'},
                       {'appointment_date': 'not-a-date'}]:
            with self.subTest(values=values), self.assertRaises(ValidationError):
                self._intent(**values)
        self.assertEqual(self._counts(), before)

    def test_free_booking_is_not_a_payment_bypass(self):
        self.product.list_price = 0
        self.product.beautician_line_ids.price = 0
        self.branch.booking_fee = 0
        with self.assertRaises(ValidationError):
            self._intent()

    def test_wrong_professional_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._intent(selected_beauticians=json.dumps({str(self.product.id): 99999999}))

    def test_any_professional_is_resolved_before_checkout(self):
        intent = self._intent(selected_beauticians=json.dumps({str(self.product.id): None}))
        self.assertEqual(intent.payload['lines'][0]['beautician_id'], self.staff.id)

    def test_any_professional_can_split_sequential_services_between_staff(self):
        second_staff, second_service = self._second_staff_service()
        intent = self._intent(
            selected_services=json.dumps([self.product.id, second_service.id]),
            selected_beauticians=json.dumps({
                str(self.product.id): None,
                str(second_service.id): None,
            }),
        )
        self.assertEqual(
            [line['beautician_id'] for line in intent.payload['lines']],
            [self.staff.id, second_staff.id],
        )

    def test_any_professional_reports_complete_selection_unavailable(self):
        appointment = self.env['salon.appointment'].create({
            'branch_id': self.branch.id,
            'company_id': self.env.company.id,
            'appointment_date': self.day,
            'customer_first_name': 'Existing',
            'customer_last_name': 'Booking',
        })
        self.env['salon.appointment.service'].create({
            'appointment_id': appointment.id,
            'service_id': self.product.id,
            'beautician_id': self.staff.id,
            'start_hour': 10,
            'duration': 1,
        })
        with self.assertRaisesRegex(ValidationError, 'No professional is available for the complete service selection'):
            self._intent(selected_beauticians=json.dumps({str(self.product.id): None}))

    def test_wrong_branch_service_is_rejected(self):
        self.product.branch_ids = [(5, 0, 0)]
        with self.assertRaises(ValidationError):
            self._intent()

    def test_checkout_token_is_specific_and_unpredictable(self):
        intent = self._intent()
        self.assertTrue(intent._check_token(intent.access_token))
        self.assertFalse(intent._check_token('wrong'))
        self.assertFalse(intent._check_token(None))
        self.assertGreaterEqual(len(intent.access_token), 40)

    def test_public_user_cannot_read_checkout_records(self):
        intent = self._intent()
        with self.assertRaises(AccessError):
            intent.with_user(self.website.user_id).read(['name'])

    def test_authorized_but_not_captured_is_not_payment(self):
        intent = self._intent()
        tx = self._tx(intent)
        # Core's own @api.constrains rejects 'authorized' for a provider that
        # doesn't support manual capture; patching the method has no effect
        # because the constraint list is memoized on the class the first time
        # any payment.transaction is validated. Go around the ORM write.
        self.env.cr.execute("UPDATE payment_transaction SET state = 'authorized' WHERE id = %s", (tx.id,))
        tx.invalidate_recordset()
        with self.assertRaises(ValidationError):
            intent._finalize(tx)
        self.assertFalse(intent.appointment_id)

    def test_refund_stops_late_automatic_booking(self):
        intent = self._intent()
        tx = self._tx(intent)
        tx._set_done()
        refund = self._tx(intent, bnb_booking_intent_id=False, reference=intent.name + '-refund',
            operation='refund', source_transaction_id=tx.id, amount=-intent.amount)
        refund._set_pending()
        before = self._counts()
        self.assertFalse(intent._finalize(tx))
        self.assertEqual(intent.state, 'refunded')
        self.assertEqual(self._counts(), before)

    def test_model_guard_rejects_second_transaction(self):
        from psycopg2.errors import UniqueViolation
        intent = self._intent()
        self._tx(intent)
        with self.assertRaises(UniqueViolation), self.env.cr.savepoint():
            self._tx(intent, reference=intent.name + '-second')

    def test_failed_finalization_rolls_back_new_customer(self):
        intent = self._intent()
        tx = self._tx(intent)
        tx._set_done()
        before = self._counts()
        with patch.object(type(self.env['salon.appointment.service']), 'create', side_effect=ValidationError('Test service failure')):
            self.assertFalse(intent._finalize(tx))
        self.assertEqual(self._counts(), before)
        self.assertEqual(intent.state, 'review')
        self.assertTrue(intent.activity_ids)

    def test_existing_other_company_customer_is_not_modified(self):
        other = self.env['res.company'].create({'name': 'Payment first other company'})
        contact = self.env['res.partner'].create({'name': 'Other company customer',
            'email': 'payment.first@example.invalid', 'company_id': other.id})
        intent = self._intent()
        tx = self._tx(intent)
        tx._set_done()
        appointment = intent._finalize(tx)
        self.assertTrue(appointment, intent.review_reason)
        self.assertNotEqual(appointment.customer_id, contact)
        self.assertEqual(contact.name, 'Other company customer')

    def test_accounting_failure_keeps_paid_booking_and_flags_recovery(self):
        intent = self._intent()
        tx = self._tx(intent)
        tx._set_done()
        with patch.object(type(tx), '_create_payment', side_effect=ValidationError('Accounting not configured')):
            tx._post_process()
        self.assertTrue(intent.appointment_id)
        self.assertEqual(intent.state, 'review')
        self.assertFalse(tx.is_post_processed)
        self.assertTrue(intent.activity_ids)
        appointment = intent.appointment_id
        before = self._counts()
        with patch.object(type(tx), '_create_payment'), patch.object(type(self.env['bb.online.deposit.service']), '_create_online_deposit'):
            tx._post_process()
        self.assertEqual(intent.state, 'paid')
        self.assertEqual(intent.appointment_id, appointment)
        self.assertEqual(self._counts(), before)
        self.assertFalse(intent.activity_ids)

    def test_deposit_amount_balance_and_move_are_not_duplicated(self):
        Account = self.env['account.account']
        Account.search([('is_deposit_liability_account', '=', True)]).write({'is_deposit_liability_account': False})
        receivable = Account.create({'name': 'Checkout receivable', 'code': 'PFR001', 'account_type': 'asset_receivable',
            'reconcile': True, 'company_ids': [(6, 0, self.env.company.ids)]})
        liability = Account.create({'name': 'Checkout deposits', 'code': 'PFL001', 'account_type': 'liability_current',
            'is_deposit_liability_account': True, 'company_ids': [(6, 0, self.env.company.ids)]})
        self.env['account.journal'].create({'name': 'Checkout sales', 'code': 'PFSL', 'type': 'sale',
            'company_id': self.env.company.id})
        self.env['product.product'].create({'name': 'Checkout deposit', 'type': 'service',
            'is_deposit_product': True, 'company_id': self.env.company.id})
        intent = self._intent(payment_option='half')
        tx = self._tx(intent)
        tx._set_done()
        appointment = intent._finalize(tx)
        self.assertTrue(appointment, intent.review_reason)
        appointment.customer_id.property_account_receivable_id = receivable
        service = self.env['bb.online.deposit.service'].with_context(require_online_booking_accounting=True)
        service._create_online_deposit(appointment, appointment.payment_line_ids, tx)
        service._create_online_deposit(appointment, appointment.payment_line_ids, tx)
        deposits = self.env['beauty.customer.deposit'].search([('appointment_id', '=', appointment.id)])
        self.assertEqual(len(deposits), 1)
        self.assertEqual(deposits.amount, 65)
        # Existing allocation deliberately excludes the separate booking fee.
        self.assertEqual(deposits.balance_due, 55)
        self.assertEqual(deposits.credit_amount, 0)
        self.assertEqual(deposits.move_id.state, 'posted')
        self.assertEqual(sum(deposits.move_id.line_ids.mapped('debit')), 65)
        self.assertEqual(sum(deposits.move_id.line_ids.mapped('credit')), 65)
        self.assertIn(liability, deposits.move_id.line_ids.account_id)

    def _nab_checkout(self):
        if 'nab_merchant_id' not in self.provider._fields:
            self.skipTest('NAB provider is not installed')
        self.provider.write({'code': 'nab_gateway', 'nab_merchant_id': 'ticket-test-merchant'})
        intent = self._intent()
        tx = self._tx(intent)
        tx.write({'partner_name': 'Payment Customer', 'partner_email': 'payment.first@example.invalid'})
        return intent, tx

    def test_nab_success_and_duplicate_submission(self):
        from types import SimpleNamespace
        from odoo.addons.payment_nab_gateway.controllers import main as nab
        intent, tx = self._nab_checkout()
        mocked_request = SimpleNamespace(env=self.env, session={'bnb_checkout': {'id': intent.id, 'token': intent.access_token}})
        response = {'id': 'ticket-bank-reference', 'status': 'ACCEPT',
            'processorInformation': {'responseCode': '000'},
            'orderInformation': {'amountDetails': {'totalAmount': str(tx.amount), 'currency': tx.currency_id.name}}}
        before = self._counts()
        with patch.object(nab, 'request', mocked_request), \
             patch.object(type(self.env['bb.online.gateway.submission']), '_claim', return_value=True), \
             patch.object(type(self.provider), '_nab_send_request', return_value=response) as charge:
            result = nab.NabGatewayController().nab_process_payment(reference=tx.reference, payment_type='card', token_data='mock-card-token')
            self.assertTrue(result['success'], result)
            self.assertEqual(tx.state, 'done')
            self.assertEqual(self._counts(), before)  # Created by post-processing, not the charge route.
            repeated = nab.NabGatewayController().nab_process_payment(reference=tx.reference, payment_type='card', token_data='mock-card-token')
            self.assertFalse(repeated['success'])
            charge.assert_called_once()
            payload = charge.call_args.args[2]
            self.assertEqual(payload['orderInformation']['billTo']['firstName'], 'Payment')

    def test_nab_uncertain_outcome_is_flagged_and_not_recharged(self):
        from types import SimpleNamespace
        from odoo.addons.payment_nab_gateway.controllers import main as nab
        intent, tx = self._nab_checkout()
        mocked_request = SimpleNamespace(env=self.env, session={'bnb_checkout': {'id': intent.id, 'token': intent.access_token}})
        before = self._counts()
        with patch.object(nab, 'request', mocked_request), \
             patch.object(type(self.env['bb.online.gateway.submission']), '_claim', return_value=True), \
             patch.object(type(self.provider), '_nab_send_request', side_effect=ValidationError('Gateway timeout')) as charge:
            result = nab.NabGatewayController().nab_process_payment(reference=tx.reference, payment_type='card', token_data='mock-card-token')
            self.assertFalse(result['success'])
            self.assertEqual(intent.state, 'review')
            self.assertTrue(intent.activity_ids)
            self.assertEqual(self._counts(), before)
            nab.NabGatewayController().nab_process_payment(reference=tx.reference, payment_type='card', token_data='mock-card-token')
            charge.assert_called_once()

    def test_nab_rejects_foreign_checkout_session(self):
        from types import SimpleNamespace
        from odoo.addons.payment_nab_gateway.controllers import main as nab
        intent, tx = self._nab_checkout()
        with patch.object(nab, 'request', SimpleNamespace(env=self.env, session={})), \
             patch.object(type(self.provider), '_nab_send_request') as charge:
            result = nab.NabGatewayController().nab_process_payment(reference=tx.reference, token_data='mock-card-token')
            self.assertFalse(result['success'])
            charge.assert_not_called()
            self.assertEqual(tx.state, 'draft')
