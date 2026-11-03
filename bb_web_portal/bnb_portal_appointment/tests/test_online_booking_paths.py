"""Both public entry points must enter payment checkout without creating contacts."""
import json
import re
from urllib.parse import urlparse, parse_qs

from odoo.tests import HttpCase, tagged
from .test_payment_first_checkout import PaymentFirstFixture


@tagged('post_install', '-at_install')
class TestOnlineBookingPaths(PaymentFirstFixture, HttpCase):
    def _post_booking(self, route, **updates):
        page = self.url_open('/web/login')
        token = re.search(r'csrf_token["\'\s:=]+([0-9a-zA-Z]{20,})', page.text)
        self.assertTrue(token)
        return self.url_open(route, data={**self._form(**updates), 'csrf_token': token.group(1)})

    def test_pay_now_returns_checkout_without_creating_business_records(self):
        before = self._counts()
        response = self._post_booking('/salon/create-booking-payment')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body.get('success'), body)
        self.assertIn('/salon/secure-checkout/', body['redirect_url'])
        self.assertNotIn('appointment_id', body)
        self.assertEqual(self._counts(), before)
        checkout = self.url_open(body['redirect_url'])
        self.assertEqual(checkout.status_code, 200, checkout.text[:1000])
        self.assertIn('Complete your booking', checkout.text)

    def test_checkout_result_page_renders_waiting_then_paid(self):
        intent = self._intent()
        result_url = '/salon/checkout-result/%s?access_token=%s' % (intent.id, intent.access_token)

        waiting = self.url_open(result_url)
        self.assertEqual(waiting.status_code, 200, waiting.text[:1000])
        self.assertIn('Waiting for payment confirmation', waiting.text)
        self.assertIn(self.branch.name, waiting.text)

        tx = self._tx(intent)
        tx._set_done()
        appointment = intent._finalize(tx)
        self.assertTrue(appointment, intent.review_reason)

        paid = self.url_open(result_url)
        self.assertEqual(paid.status_code, 200, paid.text[:1000])
        self.assertIn('Booking Confirmed', paid.text)
        self.assertIn(appointment.appointment_ref, paid.text)

    def test_legacy_pay_later_cannot_bypass_payment(self):
        before = self._counts()
        response = self._post_booking('/salon/complete-booking')
        body = response.json()
        self.assertTrue(body.get('success'), body)
        self.assertIn('/salon/secure-checkout/', body['redirect_url'])
        self.assertEqual(self._counts(), before)

    def test_wrong_token_cannot_open_checkout_or_result(self):
        body = self._post_booking('/salon/create-booking-payment').json()
        self.assertTrue(body.get('success'), body)
        path = urlparse(body['redirect_url']).path
        self.assertEqual(self.url_open(path + '?access_token=wrong').status_code, 404)
        result = path.replace('/secure-checkout/', '/checkout-result/')
        self.assertEqual(self.url_open(result + '?access_token=wrong').status_code, 404)

    def test_fake_payment_completion_route_is_closed(self):
        self.assertEqual(self.url_open('/salon/payment/test-complete/1?access_token=anything').status_code, 404)

    def test_missing_terms_does_not_create_checkout(self):
        before = self.Intent.search_count([])
        body = self._post_booking('/salon/create-booking-payment', agree_policy='off').json()
        self.assertFalse(body['success'])
        self.assertEqual(self.Intent.search_count([]), before)

    def test_professional_endpoint_marks_any_unavailable_when_no_assignment_exists(self):
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
        response = self.url_open(
            '/salon/get-beauticians-by-services'
            f'?branch_id={self.branch.id}'
            f'&service_ids={self.product.id}'
            f'&selected_date={self.day}'
            '&selected_time=10:00'
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['any_professional_available'])

    def test_professional_endpoint_marks_any_available_for_a_valid_assignment(self):
        response = self.url_open(
            '/salon/get-beauticians-by-services'
            f'?branch_id={self.branch.id}'
            f'&service_ids={self.product.id}'
            f'&selected_date={self.day}'
            '&selected_time=10:00'
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['any_professional_available'])

    def test_professional_endpoint_allows_any_to_split_services_between_staff(self):
        _second_staff, second_service = self._second_staff_service()
        response = self.url_open(
            '/salon/get-beauticians-by-services'
            f'?branch_id={self.branch.id}'
            f'&service_ids={self.product.id},{second_service.id}'
            f'&selected_date={self.day}'
            '&selected_time=10:00'
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['any_professional_available'])
        self.assertFalse(payload['beauticians'])

    def _transaction_request(self, checkout_url, **overrides):
        parsed = urlparse(checkout_url)
        intent_id = int(parsed.path.rsplit('/', 1)[1])
        params = {'access_token': parse_qs(parsed.query)['access_token'][0],
            'provider_id': self.provider.id, 'payment_method_id': self.env.ref('payment.payment_method_card').id,
            'flow': 'direct', 'token_id': None, 'tokenization_requested': False}
        params.update(overrides)
        response = self.url_open('/salon/checkout-transaction/%s' % intent_id,
            data=json.dumps({'jsonrpc': '2.0', 'method': 'call', 'params': params, 'id': 1}),
            headers={'Content-Type': 'application/json'})
        return response.json()

    def test_transaction_ignores_browser_price_and_keeps_customer_unsaved(self):
        self.provider.write({'state': 'enabled', 'is_published': True})
        before = self._counts()
        body = self._post_booking('/salon/create-booking-payment', payment_option='half').json()
        self.assertTrue(body.get('success'), body)
        result = self._transaction_request(body['redirect_url'], amount=0.01, partner_id=self.env.user.partner_id.id)
        self.assertNotIn('error', result, result)
        tx = self.env['payment.transaction'].search([('provider_id', '=', self.provider.id)], limit=1)
        self.assertEqual(tx.amount, 65)
        self.assertEqual(tx.partner_id, self.website.user_id.partner_id)
        self.assertEqual(tx.partner_email, 'payment.first@example.invalid')
        self.assertEqual(tx.partner_name, 'Payment Customer')
        self.assertEqual(self._counts(), before)
        replay = self._transaction_request(body['redirect_url'])
        self.assertIn('error', replay)
        self.assertEqual(len(tx.bnb_booking_intent_id.transaction_ids), 1)

    def test_disabled_provider_cannot_be_forced(self):
        self.provider.state = 'disabled'
        body = self._post_booking('/salon/create-booking-payment').json()
        self.assertTrue(body.get('success'), body)
        result = self._transaction_request(body['redirect_url'])
        self.assertIn('error', result)
        self.assertFalse(self.env['payment.transaction'].search([('provider_id', '=', self.provider.id)]))

    def test_wrong_token_cannot_create_payment_transaction(self):
        self.provider.write({'state': 'enabled', 'is_published': True})
        body = self._post_booking('/salon/create-booking-payment').json()
        self.assertTrue(body.get('success'), body)
        result = self._transaction_request(body['redirect_url'], access_token='wrong')
        self.assertIn('error', result)
        self.assertFalse(self.env['payment.transaction'].search([('provider_id', '=', self.provider.id)]))
