# -*- coding: utf-8 -*-

from odoo.tests import TransactionCase, tagged

from ..controllers.booking_helpers import (
    _lock_beauticians_for_booking,
    _unlock_beauticians_for_booking,
)


@tagged('post_install', '-at_install')
class TestBeauticianBookingLock(TransactionCase):
    """Pin the 2026-08-09 fix: /salon/complete-booking validated beautician
    availability with a plain SELECT and no locking, so two near-simultaneous
    requests for the identical beautician+date+slot could both pass the
    check before either committed its own reservation. Confirmed exploitable
    via a real concurrent test: 5 simultaneous requests for the same
    beautician and slot, 4 succeeded and created 4 overlapping appointments.

    Fixed with a SESSION-scoped Postgres advisory lock (`pg_advisory_lock`,
    explicitly released via `_unlock_beauticians_for_booking` in a `finally`
    block), not a transaction-scoped one -- a transaction-scoped lock was
    tried first and was not sufficient, since something in the booking
    request's own create() chain issues an intermediate commit that ends
    the transaction (and releases a transaction-scoped lock) before the
    reservation it was meant to protect is actually made. Confirmed via
    direct concurrent testing plus a manual two-terminal `psql` check that
    ruled out Postgres's own advisory-lock mechanism as the cause.

    These tests pin the helpers' own parsing/no-crash/lock-release behavior
    -- the actual concurrency property (that a second real HTTP request now
    blocks until the first commits and releases) is proven live, not
    re-derived here, since a single TransactionCase runs on one connection/
    transaction and cannot exercise a genuine cross-request/cross-connection
    race. Every test unlocks what it locks: these are SESSION-scoped locks,
    not auto-released at transaction rollback, so leaving one held would
    leak past this test onto whatever later reuses the same pooled
    connection."""

    def test_lock_skips_any_and_invalid_values_without_error(self):
        # Must not raise for a mix of a real id, 'any', and a garbage value.
        locked = _lock_beauticians_for_booking(
            self.env, '2026-09-20', {'1': '342', '2': 'any', '3': 'not-an-id'},
        )
        self.assertEqual(locked, [(342, self._date_key('2026-09-20'))])
        _unlock_beauticians_for_booking(self.env, locked)

    def test_lock_handles_invalid_date_without_error(self):
        locked = _lock_beauticians_for_booking(self.env, 'not-a-date', {'1': '342'})
        self.assertEqual(locked, [])
        _unlock_beauticians_for_booking(self.env, locked)

    def test_lock_handles_empty_selection_without_error(self):
        locked = _lock_beauticians_for_booking(self.env, '2026-09-20', {})
        self.assertEqual(locked, [])
        locked = _lock_beauticians_for_booking(self.env, '2026-09-20', None)
        self.assertEqual(locked, [])
        _unlock_beauticians_for_booking(self.env, locked)

    def test_lock_can_be_acquired_twice_in_the_same_session(self):
        # A single request may name the same beautician for more than one
        # service (selected_beauticians is keyed per service_id) -- Postgres
        # advisory locks are re-entrant/reference-counted within one
        # session, so re-acquiring the same key must not block or raise,
        # and must be released once per acquisition.
        locked = _lock_beauticians_for_booking(self.env, '2026-09-20', {'1': '342', '2': '342'})
        self.assertEqual(locked, [(342, self._date_key('2026-09-20'))])
        _unlock_beauticians_for_booking(self.env, locked)

    def test_unlock_with_empty_list_does_not_raise(self):
        _unlock_beauticians_for_booking(self.env, [])
        _unlock_beauticians_for_booking(self.env, None)

    @staticmethod
    def _date_key(date_str):
        from datetime import datetime
        return datetime.strptime(date_str, '%Y-%m-%d').date().toordinal()