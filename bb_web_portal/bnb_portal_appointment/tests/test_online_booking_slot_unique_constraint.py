# -*- coding: utf-8 -*-

from psycopg2.errors import UniqueViolation

from odoo.tests import TransactionCase, tagged
from odoo.addons.bb_salon_appoitments.tests.branch_fixture import ensure_beautician, ensure_branch, ensure_service_product


@tagged('post_install', '-at_install')
class TestOnlineBookingSlotUniqueConstraint(TransactionCase):
    """Pin the 2026-08-09 fix: a live concurrent test found 5 simultaneous
    /salon/complete-booking requests for the identical beautician+date+slot
    -- 4 succeeded and created 4 overlapping appointments. Two advisory-lock
    based fixes (transaction-scoped, then session-scoped) were tried and
    both proved unreliable in this specific hosting environment (Postgres
    itself was confirmed correct via a direct manual test; something in
    Odoo's own request/connection handling here doesn't hold either lock
    variant reliably across the whole request).

    The actual, database-enforced fix is a partial unique index on
    salon.appointment.service: (beautician_id, appointment_date, start_hour)
    WHERE appointment_booked_online IS TRUE AND beautician_id IS NOT NULL --
    scoped to online bookings only, since in-store POS deliberately allows
    overlapping/parallel bookings with staff confirmation (a separate,
    pre-existing, intentional business rule that must not be affected)."""

    def _branch(self):
        return ensure_branch(self.env, name='Slot Constraint Branch')

    def _beautician(self, branch):
        return ensure_beautician(self.env, branch, name='Slot Constraint Beautician')

    def _service(self):
        return ensure_service_product(self.env, name='Slot Constraint Service')

    def _make_appointment(self, branch, booked_online):
        return self.env['salon.appointment'].create({
            'branch_id': branch.id,
            'company_id': branch.company_id.id,
            'appointment_date': '2026-11-03',
            'customer_first_name': 'Unique',
            'customer_last_name': 'ConstraintTest',
            'booked_online': booked_online,
        })

    def test_second_online_booking_for_identical_slot_is_rejected(self):
        branch = self._branch()
        beautician = self._beautician(branch)
        service = self._service()

        appt1 = self._make_appointment(branch, booked_online=True)
        self.env['salon.appointment.service'].create({
            'appointment_id': appt1.id,
            'service_id': service.id,
            'beautician_id': beautician.id,
            'start_hour': 10.0,
            'duration': 1.0,
        })

        appt2 = self._make_appointment(branch, booked_online=True)
        with self.assertRaises(UniqueViolation):
            with self.env.cr.savepoint():
                self.env['salon.appointment.service'].create({
                    'appointment_id': appt2.id,
                    'service_id': service.id,
                    'beautician_id': beautician.id,
                    'start_hour': 10.0,
                    'duration': 1.0,
                })

    def test_in_store_pos_duplicate_slot_is_still_allowed(self):
        # Confirms the constraint's WHERE clause correctly leaves the
        # existing, intentional in-store "parallel appointment" business
        # rule untouched: booked_online defaults to False for POS-created
        # appointments, so the partial index does not apply to these rows
        # at all.
        branch = self._branch()
        beautician = self._beautician(branch)
        service = self._service()

        appt1 = self._make_appointment(branch, booked_online=False)
        self.env['salon.appointment.service'].create({
            'appointment_id': appt1.id,
            'service_id': service.id,
            'beautician_id': beautician.id,
            'start_hour': 11.0,
            'duration': 1.0,
        })

        appt2 = self._make_appointment(branch, booked_online=False)
        # Must NOT raise -- this is the same in-store overlap the POS
        # frontend allows with a user-confirmed override.
        self.env['salon.appointment.service'].create({
            'appointment_id': appt2.id,
            'service_id': service.id,
            'beautician_id': beautician.id,
            'start_hour': 11.0,
            'duration': 1.0,
        })

    def test_different_start_hours_do_not_collide(self):
        branch = self._branch()
        beautician = self._beautician(branch)
        service = self._service()

        appt1 = self._make_appointment(branch, booked_online=True)
        self.env['salon.appointment.service'].create({
            'appointment_id': appt1.id,
            'service_id': service.id,
            'beautician_id': beautician.id,
            'start_hour': 14.0,
            'duration': 1.0,
        })

        appt2 = self._make_appointment(branch, booked_online=True)
        # Must NOT raise -- a different start_hour is a different slot as
        # far as this exact-match partial index is concerned (genuine
        # overlap-but-different-start-time collisions are a separate,
        # narrower gap not covered by this pass -- see the model comment).
        self.env['salon.appointment.service'].create({
            'appointment_id': appt2.id,
            'service_id': service.id,
            'beautician_id': beautician.id,
            'start_hour': 15.0,
            'duration': 1.0,
        })

    def test_appointment_date_and_booked_online_stay_in_sync_with_parent(self):
        branch = self._branch()
        appt = self._make_appointment(branch, booked_online=True)
        service = self._service()
        line = self.env['salon.appointment.service'].create({
            'appointment_id': appt.id,
            'service_id': service.id,
            'start_hour': 16.0,
            'duration': 1.0,
        })
        self.assertEqual(str(line.appointment_date), '2026-11-03')
        self.assertTrue(line.appointment_booked_online)