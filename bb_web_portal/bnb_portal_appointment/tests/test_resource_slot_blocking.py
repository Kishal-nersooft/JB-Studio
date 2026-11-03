# -*- coding: utf-8 -*-

import unittest

from odoo import fields
from odoo.tests import TransactionCase, tagged
from odoo.addons.bb_salon_appoitments.tests.branch_fixture import ensure_branch

from ..controllers.booking_helpers import (
    _get_unavailable_resource_start_hours,
    _has_resource_conflict,
)


@tagged('post_install', '-at_install')
class TestOnlineResourceSlotBlocking(TransactionCase):

    def test_same_resource_overlap_is_blocked(self):
        requirements = [(0.0, 1.0, {10})]
        reservations = [(13.0, 14.0, {10})]

        self.assertTrue(_has_resource_conflict(12.25, requirements, reservations))
        self.assertTrue(_has_resource_conflict(13.0, requirements, reservations))

    def test_adjacent_and_different_resource_slots_remain_available(self):
        requirements = [(0.0, 1.0, {10})]

        self.assertFalse(_has_resource_conflict(12.0, requirements, [(13.0, 14.0, {10})]))
        self.assertFalse(_has_resource_conflict(13.0, requirements, [(13.0, 14.0, {11})]))

    def test_resource_offset_for_sequential_services_is_respected(self):
        requirements = [
            (0.0, 0.5, set()),
            (0.5, 0.5, {10}),
        ]
        reservations = [(13.0, 13.5, {10})]

        self.assertTrue(_has_resource_conflict(12.5, requirements, reservations))
        self.assertFalse(_has_resource_conflict(12.0, requirements, reservations))

    def test_calendar_hours_are_loaded_from_existing_appointments(self):
        if 'salon.equipment' not in self.env:
            raise unittest.SkipTest('Resource management is not installed.')
        branch = ensure_branch(self.env, name='Resource Slot Branch')

        equipment = self.env['salon.equipment'].create({
            'name': 'Online Calendar Test Resource',
            'branch_ids': [(6, 0, branch.ids)],
        })
        service = self.env['product.product'].create({
            'name': 'Online Calendar Resource Service',
            'type': 'service',
            'duration': 1.0,
            'branch_ids': [(6, 0, branch.ids)],
            'resource_ids': [(6, 0, equipment.ids)],
        })
        appointment_date = fields.Date.from_string('2026-08-10')
        appointment = self.env['salon.appointment'].create({
            'branch_id': branch.id,
            'company_id': branch.company_id.id,
            'appointment_date': appointment_date,
            'customer_first_name': 'Resource',
            'customer_last_name': 'Test',
        })
        self.env['salon.appointment.service'].create({
            'appointment_id': appointment.id,
            'service_id': service.id,
            'duration': 1.0,
            'start_hour': 13.0,
            'resource_ids': [(6, 0, equipment.ids)],
        })

        unavailable = _get_unavailable_resource_start_hours(
            self.env,
            fields.Date.to_string(appointment_date),
            branch,
            [service],
        )

        self.assertIn(12.25, unavailable)
        self.assertIn(13.0, unavailable)
        self.assertNotIn(12.0, unavailable)
        self.assertNotIn(14.0, unavailable)
