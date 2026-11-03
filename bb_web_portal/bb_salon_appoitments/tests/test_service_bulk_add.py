from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestServiceBulkAddToBeautician(TransactionCase):
    """Services can be assigned to a beautician in bulk.

    The link records are the same ones edited from the service form, so both
    directions must stay in agreement and neither may create duplicates.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        company = cls.env.company
        cls.branch = cls.env['beauty.branch'].create({
            'name': 'Bulk Services Branch',
            'company_id': company.id,
            'pos_config_id': cls.env['pos.config'].create({
                'name': 'Bulk Services POS', 'company_id': company.id,
            }).id,
            'website_id': (
                cls.env['website'].search([('company_id', '=', company.id)], limit=1)
                or cls.env['website'].create({
                    'name': 'Bulk Services Website', 'company_id': company.id,
                })
            ).id,
        })
        cls.other_branch = cls.env['beauty.branch'].create({
            'name': 'Bulk Services Other Branch',
            'company_id': company.id,
            'pos_config_id': cls.env['pos.config'].create({
                'name': 'Bulk Services Other POS', 'company_id': company.id,
            }).id,
            'website_id': cls.branch.website_id.id,
        })
        cls.beautician = cls.env['hr.employee'].create({
            'name': 'Bulk Services Beautician',
            'company_id': company.id,
            'is_beautician': True,
            'beautician_branch_ids': [(6, 0, [cls.branch.id])],
        })
        cls.service_a, cls.service_b, cls.service_c = [
            cls.env['product.template'].create({
                'name': 'Bulk Service %s' % suffix,
                'type': 'service',
                'is_appointment_service': True,
                'list_price': 50.0,
                'branch_ids': [(6, 0, [cls.branch.id])],
            }) for suffix in ('A', 'B', 'C')
        ]

    def _wizard(self, services, price=0.0, duration=0.0):
        return self.env['service.bulk.add.wizard'].create({
            'beautician_id': self.beautician.id,
            'service_ids': [(6, 0, [s.id for s in services])],
            'default_price': price,
            'default_duration': duration,
        })

    def test_bulk_add_creates_one_line_per_service(self):
        self._wizard([self.service_a, self.service_b]).action_add_services()

        self.assertEqual(
            set(self.beautician.beautician_service_line_ids.mapped('product_tmpl_id')),
            {self.service_a, self.service_b},
        )

    def test_defaults_are_applied_to_every_new_line(self):
        self._wizard([self.service_a, self.service_b],
                     price=12.5, duration=1.5).action_add_services()

        lines = self.beautician.beautician_service_line_ids
        self.assertEqual(set(lines.mapped('price')), {12.5})
        self.assertEqual(set(lines.mapped('duration')), {1.5})

    def test_running_twice_does_not_duplicate(self):
        self._wizard([self.service_a, self.service_b]).action_add_services()
        self._wizard([self.service_a, self.service_b, self.service_c]).action_add_services()

        lines = self.beautician.beautician_service_line_ids
        self.assertEqual(len(lines), 3)
        self.assertEqual(len(lines.filtered(
            lambda l: l.product_tmpl_id == self.service_a)), 1)

    def test_assignment_is_visible_from_the_service_side(self):
        """Both directions edit the same records."""
        self._wizard([self.service_a]).action_add_services()

        self.assertIn(
            self.beautician,
            self.service_a.beautician_line_ids.mapped('beautician_id'),
        )

    def test_service_added_from_the_service_side_is_not_duplicated(self):
        # Pre-existing line created the old way, then the same service picked
        # in the new wizard: it must be skipped, not added again.
        self.env['product.beautician.line'].create({
            'product_tmpl_id': self.service_a.id,
            'beautician_id': self.beautician.id,
            'price': 9.0,
            'duration': 0.5,
        })

        self._wizard([self.service_a, self.service_b]).action_add_services()

        lines = self.beautician.beautician_service_line_ids
        self.assertEqual(len(lines), 2)
        kept = lines.filtered(lambda l: l.product_tmpl_id == self.service_a)
        self.assertEqual(kept.price, 9.0, "an existing line must not be overwritten")

    def test_wizard_branches_follow_the_beautician(self):
        wizard = self._wizard([])

        self.assertIn(self.branch, wizard.branch_ids)
        self.assertNotIn(self.other_branch, wizard.branch_ids)

    def test_main_branch_is_included_in_the_selectable_branches(self):
        # The model requires a main branch to also sit in the working
        # branches, so set both together as the form does.
        self.beautician.write({
            'beautician_branch_ids': [(6, 0, [self.branch.id, self.other_branch.id])],
            'branch_id': self.other_branch.id,
        })
        wizard = self._wizard([])

        # A beautician's main branch counts as somewhere they work, matching
        # the domain used when picking beauticians on a service.
        self.assertIn(self.other_branch, wizard.branch_ids)
        self.assertIn(self.branch, wizard.branch_ids)

    def test_empty_selection_creates_nothing(self):
        self._wizard([]).action_add_services()

        self.assertFalse(self.beautician.beautician_service_line_ids)
