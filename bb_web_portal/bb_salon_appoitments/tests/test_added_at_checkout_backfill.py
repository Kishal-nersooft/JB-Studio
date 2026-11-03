from odoo.tests import TransactionCase, tagged

from .branch_fixture import (
    ensure_beautician, ensure_branch, ensure_pos_session, ensure_service_product,
)


@tagged('post_install', '-at_install')
class TestAddedAtCheckoutBackfill(TransactionCase):
    """Services added at checkout before the flag existed are flagged once.

    A checkout addition is written with zero duration, while a booked service
    has one, so on a settled appointment a zero-duration line next to a timed
    one is an addition. Nothing else may be swept in.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.branch = ensure_branch(cls.env)
        cls.session = ensure_pos_session(cls.env, branch=cls.branch)
        cls.beautician = ensure_beautician(cls.env, cls.branch)
        cls.service = ensure_service_product(cls.env, branch=cls.branch)
        cls.partner = cls.env['res.partner'].create({'name': 'Backfill Customer'})
        cls.params = cls.env['ir.config_parameter'].sudo()

    def setUp(self):
        super().setUp()
        self.params.set_param(
            self.env['salon.appointment.service']._BACKFILL_FLAG, '')

    def _appointment(self, settled=True):
        appointment = self.env['salon.appointment'].create({
            'company_id': self.env.company.id,
            'branch_id': self.branch.id,
            'customer_id': self.partner.id,
            'appointment_date': '2026-08-18',
            'state': 'confirmed',
        })
        if settled:
            appointment.pos_order_id = self.env['pos.order'].create({
                'company_id': self.env.company.id,
                'session_id': self.session.id,
                'partner_id': self.partner.id,
                'amount_tax': 0.0, 'amount_total': 0.0,
                'amount_paid': 0.0, 'amount_return': 0.0,
            })
        return appointment

    def _line(self, appointment, duration):
        return self.env['salon.appointment.service'].create({
            'appointment_id': appointment.id,
            'service_id': self.service.id,
            'beautician_id': self.beautician.id,
            'duration': duration,
            'start_hour': 10.0,
        })

    def _backfill(self):
        self.env['salon.appointment.service']._backfill_added_at_checkout()
        self.env['salon.appointment.service'].invalidate_model()

    def test_flag_is_off_by_default_and_not_copied(self):
        appointment = self._appointment()
        line = self._line(appointment, 1.0)
        self.assertFalse(line.added_at_checkout)
        line.added_at_checkout = True
        self.assertFalse(line.copy().added_at_checkout)

    def test_flag_can_be_ticked_by_hand_on_a_completed_appointment(self):
        # Older appointments the backfill could not identify are ticked by
        # hand, and a backfill run afterwards must not undo that.
        appointment = self._appointment()
        self._line(appointment, 1.0)
        older = self._line(appointment, 1.0)
        appointment.state = 'completed'

        older.write({'added_at_checkout': True})
        self._backfill()

        self.assertTrue(older.added_at_checkout)
        self.assertEqual(appointment.state, 'completed')

    def test_zero_duration_line_beside_a_timed_one_is_flagged(self):
        appointment = self._appointment()
        booked = self._line(appointment, 1.0)
        added = self._line(appointment, 0.0)

        self._backfill()

        self.assertTrue(added.added_at_checkout)
        self.assertFalse(booked.added_at_checkout)

    def test_unsettled_appointment_is_left_alone(self):
        appointment = self._appointment(settled=False)
        self._line(appointment, 1.0)
        added = self._line(appointment, 0.0)

        self._backfill()

        self.assertFalse(added.added_at_checkout)

    def test_appointment_with_no_timed_service_is_left_alone(self):
        appointment = self._appointment()
        only = self._line(appointment, 0.0)

        self._backfill()

        self.assertFalse(only.added_at_checkout)

    def test_backfill_runs_once(self):
        appointment = self._appointment()
        self._line(appointment, 1.0)
        self._backfill()
        later = self._line(appointment, 0.0)

        self._backfill()

        self.assertFalse(later.added_at_checkout)
