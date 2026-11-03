"""Backend correction resets the booking status without reversing money."""
from lxml import etree

from odoo.exceptions import AccessError
from odoo.tests import tagged

from .test_appointment_auto_expire import TestAppointmentAutoExpire


@tagged('post_install', '-at_install')
class TestAppointmentResetDraft(TestAppointmentAutoExpire):
    def test_reset_from_each_non_draft_state(self):
        for state in ('confirmed', 'in_progress', 'completed', 'cancelled', 'refunded'):
            with self.subTest(state=state):
                appointment = self._appointment(state=state)
                self.assertTrue(appointment.action_reset_to_draft())
                self.assertEqual(appointment.state, 'draft')

    def test_draft_is_noop_and_mixed_recordsets_reset(self):
        draft = self._appointment()
        confirmed = self._appointment(state='confirmed')
        before = draft.write_date
        (draft | confirmed).action_reset_to_draft()
        self.assertEqual(draft.write_date, before)
        self.assertEqual((draft | confirmed).mapped('state'), ['draft', 'draft'])

    def test_reset_preserves_paid_order_payment_and_deposit(self):
        appointment = self._appointment(state='completed')
        session = self.env['pos.session'].create({
            'config_id': self.branch.pos_config_id.id,
            'user_id': self.env.user.id, 'state': 'opened',
        })
        order = self.env['pos.order'].create({
            'session_id': session.id, 'partner_id': self.partner.id,
            'company_id': self.env.company.id, 'state': 'paid',
            'amount_tax': 0, 'amount_total': 50, 'amount_paid': 50, 'amount_return': 0,
        })
        appointment.write({'pos_order_id': order.id, 'pos_order_paid': True})
        payment = self.env['salon.appointment.payment'].create({
            'appointment_id': appointment.id, 'payment_method': 'online',
            'payment_status': 'completed', 'payment_amount': 50,
        })
        deposit = self.env['beauty.customer.deposit'].create({
            'appointment_id': appointment.id, 'partner_id': self.partner.id,
            'branch_id': self.branch.id, 'company_id': self.env.company.id,
            'currency_id': self.env.company.currency_id.id, 'amount': 50, 'state': 'active',
        })
        before = (appointment.payment_status, appointment.total_amount,
                  appointment.actual_start_datetime, appointment.actual_end_datetime,
                  appointment.actual_duration_hours)
        appointment.action_reset_to_draft()
        self.assertEqual(appointment.state, 'draft')
        self.assertEqual((appointment.payment_status, appointment.total_amount,
                          appointment.actual_start_datetime, appointment.actual_end_datetime,
                          appointment.actual_duration_hours), before)
        self.assertEqual(appointment.pos_order_id, order)
        self.assertTrue(appointment.pos_order_paid)
        self.assertEqual((order.state, order.amount_total, order.amount_paid), ('paid', 50, 50))
        self.assertEqual((payment.payment_status, payment.payment_amount), ('completed', 50))
        self.assertEqual((deposit.state, deposit.amount), ('active', 50))

    def test_public_user_cannot_reset_backend_appointment(self):
        appointment = self._appointment(state='confirmed')
        with self.assertRaises(AccessError):
            appointment.with_user(self.env.ref('base.public_user')).action_reset_to_draft()
        self.assertEqual(appointment.state, 'confirmed')

    def test_backend_form_exposes_reset_button_only_outside_draft(self):
        view = self.env['salon.appointment'].get_view(
            view_id=self.env.ref('bb_salon_appoitments.view_salon_appointment_form').id,
            view_type='form')
        tree = etree.fromstring(view['arch'].encode())
        buttons = tree.xpath('//header/button[@name="action_reset_to_draft"]')
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0].get('string'), 'Reset to Draft')
        self.assertEqual(buttons[0].get('type'), 'object')
        self.assertEqual(buttons[0].get('invisible'), "state == 'draft'")
