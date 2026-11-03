# -*- coding: utf-8 -*-

from datetime import timedelta
from urllib.parse import urlencode

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestFutureAppointmentBeauticianVisibility(HttpCase):
    """A service professional may work at a branch other than their main one.

    _get_online_booking_availability returns early for any date at or before
    today, so these dates have to stay in the future or the roster branch is
    never reached. They were once hardcoded to September 2026; when that month
    passed, the hidden case started failing and the visible case started
    passing for the wrong reason -- everyone is visible on a past date. Both
    are now anchored to a month two months out, the same way
    bb_appointment_pos/tests/test_online_booking_future_roster.py is.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        pos_config = cls.env['pos.config'].search([
            ('company_id', '=', cls.env.company.id),
        ], limit=1) or cls.env['pos.config'].create({
            'name': 'Ticket 8 Website Test POS',
            'company_id': cls.env.company.id,
        })
        website = cls.env['website'].search([
            ('company_id', '=', cls.env.company.id),
        ], limit=1) or cls.env['website'].search([], limit=1) or cls.env['website'].create({
            'name': 'Ticket 8 Website Test',
            'company_id': cls.env.company.id,
        })

        cls.main_branch = cls.env['beauty.branch'].create({
            'name': 'Ticket 8 Main Branch',
            'company_id': cls.env.company.id,
            'pos_config_id': pos_config.id,
            'website_id': website.id,
        })
        cls.future_branch = cls.env['beauty.branch'].create({
            'name': 'Ticket 8 Future Appointment Branch',
            'company_id': cls.env.company.id,
            'pos_config_id': pos_config.id,
            'website_id': website.id,
        })
        cls.beautician = cls.env['hr.employee'].create({
            'name': 'Ticket 8 Multi-Branch Beautician',
            'company_id': cls.env.company.id,
            'is_beautician': True,
            'branch_id': cls.main_branch.id,
            'beautician_branch_ids': [(6, 0, [
                cls.main_branch.id,
                cls.future_branch.id,
            ])],
        })
        cls.service = cls.env['product.product'].create({
            'name': 'Ticket 8 Online Service',
            'type': 'service',
            'is_appointment_service': True,
            'duration': 0.5,
            'branch_ids': [(6, 0, [cls.future_branch.id])],
            'company_id': cls.env.company.id,
        })
        cls.env['product.beautician.line'].create({
            'product_tmpl_id': cls.service.product_tmpl_id.id,
            'beautician_id': cls.beautician.id,
            'duration': 0.5,
            'price': 0.0,
        })
        # The first of a month two months out: comfortably in the future
        # whenever this runs, and both dates share one roster month.
        month_start = fields.Date.context_today(cls.beautician) + relativedelta(
            months=2, day=1,
        )
        cls.working_day = month_start
        cls.non_working_day = month_start + timedelta(days=4)

        if cls.env.registry.get('employee.roster'):
            roster = cls.env['employee.roster'].create({
                'employee_id': cls.beautician.id,
                'branch_id': cls.future_branch.id,
                'month': month_start.month,
                'year': month_start.year,
            })
            cls.env['employee.roster.line'].create([
                {
                    'roster_id': roster.id,
                    'date': cls.working_day,
                    'is_working': True,
                    'start_time': '09:00',
                    'end_time': '17:00',
                },
                {
                    'roster_id': roster.id,
                    'date': cls.non_working_day,
                    'is_working': False,
                    'start_time': '09:00',
                    'end_time': '17:00',
                },
            ])

    def test_working_branch_professional_is_visible_for_future_booking(self):
        query = urlencode({
            'branch_id': self.future_branch.id,
            'service_ids': str(self.service.id),
            'selected_date': self.working_day.isoformat(),
            'selected_time': '14:30',
        })
        response = self.url_open(
            f'/salon/get-beauticians-by-services?{query}',
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        visible_ids = {item['id'] for item in payload.get('beauticians', [])}
        self.assertIn(self.beautician.id, visible_ids)

    def test_non_working_future_roster_professional_is_hidden(self):
        if not self.env.registry.get('employee.roster'):
            self.skipTest('Future Roster extension is not installed.')
        query = urlencode({
            'branch_id': self.future_branch.id,
            'service_ids': str(self.service.id),
            'selected_date': self.non_working_day.isoformat(),
            'selected_time': '14:30',
        })
        response = self.url_open(
            f'/salon/get-beauticians-by-services?{query}',
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        visible_ids = {item['id'] for item in payload.get('beauticians', [])}
        self.assertNotIn(self.beautician.id, visible_ids)
