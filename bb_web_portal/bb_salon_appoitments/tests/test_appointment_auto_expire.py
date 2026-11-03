from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAppointmentAutoExpire(TransactionCase):
    """A tentative booking releases itself if it is never confirmed.

    Only Draft appointments expire: once confirmed the hold is real, so a
    passed expiry time must not cancel a booking someone is relying on.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        company = cls.env.company
        website = cls.env['website'].search(
            [('company_id', '=', company.id)], limit=1)
        cls.branch = cls.env['beauty.branch'].create({
            'name': 'Auto Expire Branch',
            'company_id': company.id,
            'pos_config_id': cls.env['pos.config'].create({
                'name': 'Auto Expire POS', 'company_id': company.id,
            }).id,
            'website_id': website.id,
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Auto Expire Customer'})

    def _appointment(self, state='draft', expires_in=None, auto_expire=True):
        values = {
            'company_id': self.env.company.id,
            'branch_id': self.branch.id,
            'customer_id': self.partner.id,
            'appointment_date': '2026-08-21',
            'state': state,
        }
        if expires_in is not None:
            values['auto_expire'] = auto_expire
            values['auto_expire_datetime'] = fields.Datetime.now() + expires_in
        return self.env['salon.appointment'].create(values)

    def _run_cron(self):
        return self.env['salon.appointment']._cron_expire_draft_appointments()

    def test_draft_past_its_expiry_is_cancelled(self):
        appointment = self._appointment(expires_in=timedelta(hours=-1))

        self._run_cron()

        self.assertEqual(appointment.state, 'cancelled')

    def test_the_reason_is_recorded_in_the_chatter(self):
        appointment = self._appointment(expires_in=timedelta(hours=-1))

        self._run_cron()

        bodies = ' '.join(appointment.message_ids.mapped('body'))
        self.assertIn(
            'expiry time passed', bodies,
            "staff must be able to see why the appointment was cancelled",
        )

    def test_draft_before_its_expiry_is_left_alone(self):
        appointment = self._appointment(expires_in=timedelta(hours=2))

        self._run_cron()

        self.assertEqual(appointment.state, 'draft')

    def test_confirmed_appointment_never_expires(self):
        """Confirming makes the hold real; a passed deadline must not cancel it."""
        appointment = self._appointment(
            state='confirmed', expires_in=timedelta(hours=-5))

        self._run_cron()

        self.assertEqual(appointment.state, 'confirmed')

    def test_appointment_without_the_option_is_untouched(self):
        appointment = self._appointment()

        self._run_cron()

        self.assertEqual(appointment.state, 'draft')

    def test_option_requires_a_time(self):
        with self.assertRaises(ValidationError):
            self._appointment(expires_in=None).write({'auto_expire': True})

    def test_turning_the_option_off_clears_the_time(self):
        appointment = self._appointment(expires_in=timedelta(hours=2))
        appointment.auto_expire = False
        appointment._onchange_auto_expire()

        self.assertFalse(appointment.auto_expire_datetime)

    def test_cron_reports_how_many_it_expired(self):
        self._appointment(expires_in=timedelta(hours=-1))
        self._appointment(expires_in=timedelta(hours=-2))
        self._appointment(expires_in=timedelta(hours=3))

        self.assertEqual(self._run_cron(), 2)
