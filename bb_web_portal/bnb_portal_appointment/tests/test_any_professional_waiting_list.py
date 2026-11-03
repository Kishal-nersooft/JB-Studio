"""'Any professional' with nobody rostered and free joins the waiting list.

Only when the customer accepted it on the professional step: a paid booking
must never fall onto the waiting list by surprise.
"""
import json
from datetime import datetime, time, timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import HttpCase, TransactionCase, tagged

from .test_payment_first_checkout import PaymentFirstFixture


class WaitingListMixin(PaymentFirstFixture):
    def _any(self, **updates):
        form = {'selected_beauticians': json.dumps({str(self.product.id): None})}
        form.update(updates)
        return form

    def _busy_the_only_professional(self):
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


@tagged('post_install', '-at_install')
class TestAnyProfessionalWaitingList(WaitingListMixin, TransactionCase):
    def _paid_tomorrow_waiting_booking(self):
        """Book tomorrow at 04:00 today, before any roster covers tomorrow."""
        self.day = fields.Date.today() + timedelta(days=1)
        self.assertFalse(self.staff._get_online_booking_availability(
            self.branch, self.day, start_hour=10, duration=1)['available'])
        booking_time = datetime.combine(self.day - timedelta(days=1), time(4))
        with patch.object(fields.Datetime, 'now', return_value=booking_time):
            intent = self._intent(**self._any(accept_waiting_list='on'))
            tx = self._tx(intent)
            tx._set_done()
            appointment = intent._finalize(tx)
        self.assertTrue(appointment, intent.review_reason)
        self.assertTrue(appointment.booked_online)
        self.assertTrue(appointment.is_waiting_list)
        self.assertFalse(appointment.service_line_ids.beautician_id)
        return appointment

    def _assert_roster_does_not_assign_waiting_booking(self, appointment, before):
        self.env.flush_all()
        appointment.invalidate_recordset()
        appointment.service_line_ids.invalidate_recordset()
        self.assertTrue(self.staff._get_online_booking_availability(
            self.branch, self.day, start_hour=10, duration=1)['available'])
        self.assertTrue(appointment.is_waiting_list)
        self.assertTrue(appointment.bb_needs_beautician)
        self.assertFalse(appointment.service_line_ids.beautician_id)
        self.assertEqual((appointment.state, appointment.total_amount,
                          appointment.payment_line_ids.payment_amount,
                          appointment.payment_line_ids.payment_status), before)
        # The published roster applies to new requests, without moving the
        # previously paid request out of the staff-managed waiting list.
        quote = self.Intent._prepare(self._form(**self._any()), self.branch, self.website)
        self.assertFalse(quote['payload']['waiting_list'])
        self.assertEqual(quote['payload']['lines'][0]['beautician_id'], self.staff.id)

    def test_waiting_booking_remains_after_roster_added_at_0800(self):
        appointment = self._paid_tomorrow_waiting_booking()
        before = (appointment.state, appointment.total_amount,
                  appointment.payment_line_ids.payment_amount,
                  appointment.payment_line_ids.payment_status)
        roster_time = datetime.combine(self.day - timedelta(days=1), time(8))
        with patch.object(fields.Datetime, 'now', return_value=roster_time):
            roster = self.env['employee.roster'].search([
                ('employee_id', '=', self.staff.id), ('branch_id', '=', self.branch.id),
                ('month', '=', self.day.month), ('year', '=', self.day.year),
            ], limit=1) or self.env['employee.roster'].create({
                'employee_id': self.staff.id, 'branch_id': self.branch.id,
                'month': self.day.month, 'year': self.day.year,
            })
            self.env['employee.roster.line'].create({
                'roster_id': roster.id, 'date': self.day, 'is_working': True,
                'start_time': '09:00', 'end_time': '17:00',
            })
            self._assert_roster_does_not_assign_waiting_booking(appointment, before)

    def test_waiting_booking_remains_after_draft_shift_published_at_0800(self):
        appointment = self._paid_tomorrow_waiting_booking()
        before = (appointment.state, appointment.total_amount,
                  appointment.payment_line_ids.payment_amount,
                  appointment.payment_line_ids.payment_status)
        roster_time = datetime.combine(self.day - timedelta(days=1), time(8))
        with patch.object(fields.Datetime, 'now', return_value=roster_time):
            slot = self.env['planning.slot'].create({
                'resource_id': self.staff.resource_id.id,
                'company_id': self.branch.company_id.id,
                'start_datetime': datetime.combine(self.day, time(9)),
                'end_datetime': datetime.combine(self.day, time(17)),
                'planning_type': 'shift', 'state': 'draft',
            })
            self.assertFalse(self.staff._get_online_booking_availability(
                self.branch, self.day, start_hour=10, duration=1)['available'])
            self.assertTrue(appointment.is_waiting_list)
            slot.write({'state': 'published'})
            self._assert_roster_does_not_assign_waiting_booking(appointment, before)

    def test_busy_slot_without_accepting_is_still_refused(self):
        self._busy_the_only_professional()
        with self.assertRaisesRegex(ValidationError, 'No professional is available'):
            self._intent(**self._any())

    def test_busy_slot_accepted_becomes_a_waiting_list_booking(self):
        self._busy_the_only_professional()
        intent = self._intent(**self._any(accept_waiting_list='on'))
        self.assertTrue(intent.payload['waiting_list'])
        line = intent.payload['lines'][0]
        self.assertFalse(line['beautician_id'])
        self.assertEqual(line['resource_ids'], [])

        tx = self._tx(intent)
        tx._set_done()
        appointment = intent._finalize(tx)
        self.assertTrue(appointment, intent.review_reason)
        self.assertTrue(appointment.is_waiting_list)
        self.assertFalse(appointment.service_line_ids.beautician_id)
        # It lands in the POS waiting list, for staff to place by hand.
        self.assertTrue(appointment.bb_needs_beautician)
        self.assertEqual(appointment.payment_line_ids.payment_status, 'completed')

    def test_waiting_list_booking_holds_nothing_for_other_customers(self):
        self._busy_the_only_professional()
        intent = self._intent(**self._any(accept_waiting_list='on'))
        self.assertFalse(self.Intent._held(
            self.branch.company_id, self.day, self.staff.id, [], 10, 11))
        self.assertTrue(intent)

    def test_unrostered_day_accepted_joins_the_waiting_list(self):
        if 'employee.roster' not in self.env:
            self.skipTest('Future Roster extension is not installed.')
        unrostered = self.day + timedelta(days=7)
        intent = self._intent(**self._any(
            appointment_date=str(unrostered), accept_waiting_list='on'))
        self.assertTrue(intent.payload['waiting_list'])

    def test_unrostered_day_not_accepted_is_refused(self):
        if 'employee.roster' not in self.env:
            self.skipTest('Future Roster extension is not installed.')
        unrostered = self.day + timedelta(days=7)
        with self.assertRaisesRegex(ValidationError, 'No professional is available'):
            self._intent(**self._any(appointment_date=str(unrostered)))

    def test_outside_opening_hours_is_never_queued(self):
        self._busy_the_only_professional()
        # Branch hours are 08:00-20:00 and the service takes an hour.
        with self.assertRaisesRegex(ValidationError, 'No professional is available'):
            self._intent(**self._any(
                accept_waiting_list='on',
                selected_timeslots=json.dumps({'slot': {'start_hour': 19.5}})))

    def test_accepting_does_not_stop_a_free_professional_being_assigned(self):
        intent = self._intent(**self._any(accept_waiting_list='on'))
        self.assertFalse(intent.payload['waiting_list'])
        self.assertEqual(intent.payload['lines'][0]['beautician_id'], self.staff.id)

    def test_named_professional_busy_is_never_queued(self):
        self._busy_the_only_professional()
        with self.assertRaises(ValidationError):
            self._intent(accept_waiting_list='on')

    def test_waiting_list_prices_match_a_normal_any_booking(self):
        free = self._intent(**self._any())
        self.assertFalse(free.payload['waiting_list'])
        self._busy_the_only_professional()
        queued = self._intent(**self._any(accept_waiting_list='on'))
        self.assertEqual(queued.payload['totals'], free.payload['totals'])
        self.assertEqual(queued.amount, free.amount)


@tagged('post_install', '-at_install')
class TestProfessionalEndpointWaitingList(WaitingListMixin, HttpCase):
    def _professionals(self, hour='10:00'):
        response = self.url_open(
            '/salon/get-beauticians-by-services'
            f'?branch_id={self.branch.id}&service_ids={self.product.id}'
            f'&selected_date={self.day}&selected_time={hour}')
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_free_slot_does_not_offer_the_waiting_list(self):
        payload = self._professionals()
        self.assertTrue(payload['any_professional_available'])
        self.assertFalse(payload['waiting_list_available'])

    def test_busy_slot_offers_the_waiting_list(self):
        self._busy_the_only_professional()
        payload = self._professionals()
        self.assertFalse(payload['any_professional_available'])
        self.assertTrue(payload['waiting_list_available'])

    def test_slot_past_closing_is_not_offered_the_waiting_list(self):
        payload = self._professionals('19:30')
        self.assertFalse(payload['waiting_list_available'])
