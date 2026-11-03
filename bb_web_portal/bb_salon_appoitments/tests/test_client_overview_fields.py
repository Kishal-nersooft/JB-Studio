from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestClientOverviewFields(TransactionCase):
    """The customer's own record carries their latest and upcoming visit.

    Client overview opens the contacts rather than a report of its own, so
    these have to live on the contact where they can be shown as columns,
    filtered on and exported like any other field.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.context_today(cls.env['res.partner'])
        cls.customer = cls.env['res.partner'].create({'name': 'Overview Test Customer'})
        # Built rather than borrowed. Taking the first branch in the database
        # meant an empty recordset on a database with none, and every test in
        # the class then died on salon_appointment.branch_id being NOT NULL
        # instead of on an assertion.
        company = cls.env.company
        website = cls.env['website'].search([
            ('company_id', '=', company.id),
        ], limit=1) or cls.env['website'].create({
            'name': 'Overview Test Website',
            'company_id': company.id,
        })
        pos_config = cls.env['pos.config'].search([
            ('company_id', '=', company.id),
        ], limit=1) or cls.env['pos.config'].create({
            'name': 'Overview Test POS',
            'company_id': company.id,
        })
        cls.branch = cls.env['beauty.branch'].create({
            'name': 'Overview Test Branch',
            'company_id': company.id,
            'pos_config_id': pos_config.id,
            'website_id': website.id,
        })
        cls.staff = cls.env['hr.employee'].create({
            'name': 'Overview Test Beautician',
            'company_id': company.id,
            'is_beautician': True,
            'branch_id': cls.branch.id,
            # A beautician's main branch has to be among their working ones.
            'beautician_branch_ids': [(6, 0, cls.branch.ids)],
        })
        cls.service = cls.env['product.product'].search(
            [('type', '=', 'service')], limit=1
        ) or cls.env['product.product'].create({'name': 'Overview Test Service'})

    def _appointment(self, day, state='completed', channel='instore', service='A Service'):
        booking = self.env['salon.appointment'].create({
            'customer_id': self.customer.id,
            'branch_id': self.branch.id,
            'appointment_date': day,
            'state': state,
            'appointment_type': channel,
        })
        self.env['salon.appointment.service'].create({
            'appointment_id': booking.id,
            'service_id': self.service.id,
            'service_name': service,
            'beautician_id': self.staff.id,
            'start_hour': 9.0,
            'end_hour': 10.0,
        })
        return booking

    def test_latest_and_upcoming_visit_are_read_from_the_bookings(self):
        from datetime import timedelta
        self._appointment(self.today - timedelta(days=3), service='Earlier Service')
        self._appointment(self.today, service='Today Service')
        self._appointment(self.today + timedelta(days=5), state='confirmed',
                          service='Next Service')
        self.customer.invalidate_recordset()
        # The most recent visit up to today, not the earlier one.
        self.assertEqual(self.customer.last_appointment_date, self.today)
        self.assertEqual(self.customer.last_appointment_service, 'Today Service')
        self.assertEqual(self.customer.last_appointment_staff, self.staff.name)
        self.assertEqual(self.customer.weeks_absent, 0)
        # And the soonest one still to come.
        self.assertEqual(
            self.customer.next_appointment_date, self.today + timedelta(days=5)
        )
        self.assertEqual(self.customer.next_appointment_service, 'Next Service')

    def test_a_cancelled_booking_is_not_their_last_visit(self):
        """A visit that did not happen is not a visit."""
        self._appointment(self.today, state='cancelled', service='Cancelled Service')
        self.customer.invalidate_recordset()
        self.assertFalse(self.customer.last_appointment_date)

    def test_weeks_absent_counts_whole_weeks_since_the_last_visit(self):
        from datetime import timedelta
        self._appointment(self.today - timedelta(days=20))
        self.customer.invalidate_recordset()
        # Twenty days is two whole weeks, not three.
        self.assertEqual(self.customer.weeks_absent, 2)

    def test_bookings_counts_only_the_ones_made_online(self):
        """# of bookings is what the customer booked themselves."""
        self._appointment(self.today, channel='online')
        self._appointment(self.today, channel='instore')
        self._appointment(self.today, channel='callcenter')
        self.customer.invalidate_recordset()
        self.assertEqual(self.customer.online_booking_count, 1)
        self.assertEqual(self.customer.appointment_count, 3)

    def test_client_status_puts_blocked_ahead_of_vip(self):
        """A blocked customer must not read as a favoured one."""
        self.assertEqual(self.customer.client_status, 'active')
        self.customer.is_vip = True
        self.assertEqual(self.customer.client_status, 'vip')
        self.customer.is_blocked = True
        self.assertEqual(self.customer.client_status, 'blocked')

    def test_the_whole_list_is_read_in_one_pass(self):
        """There are tens of thousands of contacts on this list.

        Computing these one contact at a time would run a query per row and
        make the contact list slow to open, so the compute answers for the
        whole set at once.
        """
        import inspect
        source = inspect.getsource(
            type(self.env['res.partner'])._compute_appointment_activity
        )
        self.assertIn('self.env.cr.execute', source)
        self.assertIn('WHERE sa.customer_id IN %(partner_ids)s', source)
        # never a search inside the loop over contacts
        self.assertNotIn('for partner in self:\n            self.env[', source)


@tagged('post_install', '-at_install')
class TestArchivedCustomersReport(TransactionCase):
    """Archived, not deleted.

    Odoo keeps no deleted records, so a report of deleted customers could
    never have shown anything. Archiving is what actually happens to a
    customer taken out of use, and that is what this reports.
    """

    def test_the_report_lists_archived_customers_only(self):
        action = self.env.ref('bb_salon_appoitments.action_bnb_archived_customers')
        self.assertEqual(action.res_model, 'res.partner')
        domain = action.domain
        self.assertIn("('active', '=', False)", domain)
        self.assertIn("('customer_rank', '>', 0)", domain)

    def test_archived_records_are_actually_reachable(self):
        """Archived records are hidden from every view unless asked for.

        Without turning that off the report would open on an empty list
        however many archived customers there were.
        """
        action = self.env.ref('bb_salon_appoitments.action_bnb_archived_customers')
        self.assertIn('active_test', action.context)
        self.assertIn('False', action.context)

    def test_an_archived_customer_shows_and_an_active_one_does_not(self):
        Partner = self.env['res.partner']
        archived = Partner.create({'name': 'Archived Test Customer', 'customer_rank': 1})
        active = Partner.create({'name': 'Active Test Customer', 'customer_rank': 1})
        archived.active = False

        action = self.env.ref('bb_salon_appoitments.action_bnb_archived_customers')
        found = Partner.with_context(active_test=False).search(
            eval(action.domain)  # noqa: S307 - the action's own literal domain
        )
        self.assertIn(archived, found)
        self.assertNotIn(active, found)

    def test_it_opens_the_records_so_one_can_be_restored(self):
        """Looking at archived customers is usually a prelude to bringing one
        back, which can only be done on the record itself."""
        action = self.env.ref('bb_salon_appoitments.action_bnb_archived_customers')
        self.assertIn('list', action.view_mode)
        self.assertIn('form', action.view_mode)
