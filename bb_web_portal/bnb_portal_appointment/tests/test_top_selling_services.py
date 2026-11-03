"""Website popularity uses actual branch sales, without changing booking prices."""
from types import SimpleNamespace
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from .test_payment_first_checkout import PaymentFirstFixture
from ..controllers import portal_main


@tagged('post_install', '-at_install')
class TestTopSellingServices(PaymentFirstFixture, TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.session = cls.env['pos.session'].create({
            'config_id': cls.branch.pos_config_id.id, 'state': 'opened',
            'user_id': cls.env.user.id})
        cls.customer = cls.env['res.partner'].create({'name': 'Top selling client'})

    def _sale(self, qty=1, state='paid', session=None, company=None, product=None):
        product = product or self.product
        order = self.env['pos.order'].create({
            'session_id': (session or self.session).id,
            'company_id': (company or self.env.company).id,
            'partner_id': self.customer.id, 'state': state,
            'amount_tax': 0, 'amount_total': qty * 100,
            'amount_paid': qty * 100, 'amount_return': 0,
            'lines': [(0, 0, {'product_id': product.id, 'qty': qty,
                             'price_unit': 100, 'price_subtotal': qty * 100,
                             'price_subtotal_incl': qty * 100})],
        })
        return order

    def _quantities(self, products=None):
        return portal_main.MainController()._service_sales_quantities(
            self.env, self.branch, products if products is not None else self.product)

    def test_completed_sales_count_net_units_and_ignore_unpaid_or_cancelled(self):
        for state in ('paid', 'done'):
            self._sale(qty=3, state=state)
        self._sale(qty=-2)
        self._sale(qty=20, state='draft')
        self._sale(qty=20, state='cancel')
        self.assertEqual(self._quantities(), {self.product.id: 4})

    def test_fully_returned_or_unsold_services_have_no_ranking(self):
        self.assertEqual(self._quantities(), {})
        self._sale(qty=2)
        self._sale(qty=-2)
        self.assertEqual(self._quantities(), {})

    def test_other_branch_sales_do_not_influence_selected_branch(self):
        config = self.env['pos.config'].create({
            'name': 'Other top selling POS', 'company_id': self.env.company.id,
            'payment_method_ids': [(6, 0, [])]})
        other_session = self.env['pos.session'].create({
            'config_id': config.id, 'state': 'opened', 'user_id': self.env.user.id})
        self._sale(qty=100, session=other_session)
        self._sale(qty=2)
        self.assertEqual(self._quantities(), {self.product.id: 2})

    def test_ineligible_product_and_missing_pos_are_not_ranked(self):
        other = self.env['product.product'].create({
            'name': 'Service unavailable at selected branch', 'type': 'service',
            'company_id': self.env.company.id, 'is_appointment_service': True})
        self._sale(qty=50, product=other)
        self.assertEqual(self._quantities(self.product | other), {})
        self.branch.pos_config_id = False
        self.assertEqual(self._quantities(), {})

    def test_booking_page_passes_sales_quantity_and_retains_service_prices(self):
        parent = self.env['product.category'].create({'name': 'Top selling parent'})
        category = self.env['product.category'].create({
            'name': 'Top selling child', 'parent_id': parent.id})
        self.product.categ_id = category
        self.product.product_tmpl_id.beautician_line_ids = [(0, 0, {
            'beautician_id': self.staff.id, 'duration': 1, 'price': 100})]
        self._sale(qty=4)
        self.assertEqual(self.product.type, 'service')
        self.assertTrue(self.product.is_appointment_service)
        self.assertIn(self.branch, self.product.branch_ids)
        self.assertEqual(self.staff.company_id, self.branch.company_id)
        fake_request = SimpleNamespace(env=self.env, website=self.website,
                                       render=lambda template, values: values)
        with patch.object(portal_main, 'request', fake_request):
            values = portal_main.MainController.book_online.__wrapped__(
                portal_main.MainController(), branch_id=self.branch.id)
        products = [p for c in values['service_categories'] for p in c['product_ids']]
        product = next(p for p in products if p['id'] == self.product.id)
        self.assertEqual(product['sold_quantity'], 4)
        self.assertEqual(product['list_price'], self.product.list_price)
        self.assertEqual(product['formatted_price'], self.env.company.currency_id.format(100))
        rendered = self.env['ir.qweb']._render('bnb_portal_appointment.service_step', values)
        self.assertIn('data-sold-quantity="4.0"', str(rendered))
        self.assertIn('data-parent-id=', str(rendered))
