# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

from .branch_fixture import ensure_pos_config, ensure_website


@tagged('post_install', '-at_install')
class TestBranchEmployee(TransactionCase):
    """Branch/beautician invariants of the core salon module."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.pos_config = ensure_pos_config(cls.env, name='Unit Test POS')
        cls.website = ensure_website(cls.env, name='Unit Test Website')
        cls.branch = cls.env['beauty.branch'].create({
            'name': 'Unit Test Branch',
            'company_id': cls.env.company.id,
            'pos_config_id': cls.pos_config.id,
            'website_id': cls.website.id,
        })

    def test_branch_defaults(self):
        self.assertEqual(self.branch.work_start_hour, 9.0)
        self.assertEqual(self.branch.work_end_hour, 18.0)
        self.assertTrue(self.branch.company_id)

    def test_beautician_main_branch_must_be_working_branch(self):
        with self.assertRaises(ValidationError):
            self.env['hr.employee'].create({
                'name': 'Invalid Beautician',
                'is_beautician': True,
                'company_id': self.env.company.id,
                'branch_id': self.branch.id,
                # no beautician_branch_ids -> main branch not in working set
            })

    def test_beautician_valid_create(self):
        emp = self.env['hr.employee'].create({
            'name': 'Valid Beautician',
            'is_beautician': True,
            'company_id': self.env.company.id,
            'branch_id': self.branch.id,
            'beautician_branch_ids': [(4, self.branch.id)],
        })
        self.assertTrue(emp.is_beautician)
        self.assertIn(self.branch, emp.beautician_branch_ids)

    def test_area_manager_autofill_on_create(self):
        manager = self.env['hr.employee'].create({
            'name': 'Area Manager',
            'is_beautician': False,
            'company_id': self.env.company.id,
        })
        self.branch.area_manager_id = manager
        beautician = self.env['hr.employee'].create({
            'name': 'Managed Beautician',
            'is_beautician': True,
            'company_id': self.env.company.id,
            'branch_id': self.branch.id,
            'beautician_branch_ids': [(4, self.branch.id)],
        })
        self.assertEqual(
            beautician.portal_manager_id, manager,
            'Beautician should inherit the branch area manager on create')

    def test_area_manager_does_not_overwrite_explicit(self):
        manager = self.env['hr.employee'].create({
            'name': 'Branch Area Manager',
            'is_beautician': False,
            'company_id': self.env.company.id,
        })
        explicit = self.env['hr.employee'].create({
            'name': 'Explicit Manager',
            'is_beautician': False,
            'company_id': self.env.company.id,
        })
        self.branch.area_manager_id = manager
        beautician = self.env['hr.employee'].create({
            'name': 'Beautician With Explicit Manager',
            'is_beautician': True,
            'company_id': self.env.company.id,
            'branch_id': self.branch.id,
            'beautician_branch_ids': [(4, self.branch.id)],
            'portal_manager_id': explicit.id,
        })
        self.assertEqual(beautician.portal_manager_id, explicit)