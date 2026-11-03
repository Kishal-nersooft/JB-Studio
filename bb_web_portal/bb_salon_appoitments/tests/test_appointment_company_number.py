from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAppointmentCompanyNumber(TransactionCase):
    """Real appointments carry a number of their own, per company.

    Every record on the calendar takes the APPT reference, leave and break
    slots included, so that run cannot be used to search or follow trade. This
    second number is drawn per company and only by real bookings, whatever
    channel they came through.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls._company('Number Test Company A')
        cls.company_b = cls._company('Number Test Company B')
        cls.branch_a = cls._branch(cls.company_a, 'Number Test Branch A')
        cls.branch_b = cls._branch(cls.company_b, 'Number Test Branch B')

    @classmethod
    def _company(cls, name):
        """A company able to hold a branch of its own.

        A branch needs a POS configuration, which needs journals, so the new
        company is given a chart of accounts before anything is hung off it.
        """
        company = cls.env['res.company'].create({'name': name})
        cls.env['account.chart.template'].try_loading(
            'generic_coa', company=company, install_demo=False)
        return company

    @classmethod
    def _branch(cls, company, name):
        # Created in the company's own name, so the defaults behind the POS
        # configuration are drawn from its journals rather than another's.
        pos_config = cls.env['pos.config'].with_company(company).create({
            'name': f'{name} POS',
            'company_id': company.id,
            # A new company has no payment method yet, and POS refuses one
            # belonging to somebody else.
            'payment_method_ids': [(5, 0, 0)],
        })
        website = cls.env['website'].create({
            'name': f'{name} Site', 'company_id': company.id})
        return cls.env['beauty.branch'].with_company(company).create({
            'name': name,
            'company_id': company.id,
            'pos_config_id': pos_config.id,
            'website_id': website.id,
        })

    def _values(self, branch, appointment_type=None, day='2026-09-04'):
        values = {
            'branch_id': branch.id,
            'company_id': branch.company_id.id,
            'appointment_date': fields.Date.from_string(day),
        }
        if appointment_type:
            values['appointment_type'] = appointment_type
        return values

    def _create(self, branch, appointment_type=None, day='2026-09-04'):
        return self.env['salon.appointment'].with_company(branch.company_id).create(
            self._values(branch, appointment_type, day))

    def test_each_company_counts_its_own_appointments(self):
        first_a = self._create(self.branch_a)
        first_b = self._create(self.branch_b)
        second_a = self._create(self.branch_a)
        second_b = self._create(self.branch_b)
        # Each company starts at one and is untouched by the other's bookings.
        self.assertEqual(
            (first_a + second_a).mapped('appointment_no'),
            ['APP/00001', 'APP/00002'])
        self.assertEqual(
            (first_b + second_b).mapped('appointment_no'),
            ['APP/00001', 'APP/00002'])
        # The shared calendar reference still runs across both companies, so
        # nothing about the existing sequence has changed.
        booked = first_a + first_b + second_a + second_b
        self.assertEqual(len(set(booked.mapped('appointment_ref'))), 4)

    def test_every_booking_channel_is_numbered(self):
        for channel in self.env['salon.appointment'].BOOKING_APPOINTMENT_TYPES:
            appointment = self._create(self.branch_a, channel)
            self.assertTrue(
                appointment.appointment_no,
                f'a {channel} booking should be given a company number')

    def test_leave_and_break_take_the_calendar_reference_only(self):
        for blocking in ('leave', 'break'):
            appointment = self._create(self.branch_a, blocking)
            self.assertFalse(
                appointment.appointment_no,
                f'{blocking} blocks calendar time and is not a booking')
            self.assertTrue(
                appointment.appointment_ref,
                f'{blocking} still belongs on the calendar')

    def test_leave_does_not_consume_a_company_number(self):
        # The point of the ticket: a leave slot in between two bookings must
        # not break the company's run the way it breaks the calendar run.
        before = self._create(self.branch_a)
        self._create(self.branch_a, 'leave')
        after = self._create(self.branch_a)
        self.assertEqual(
            self._number_of(after), self._number_of(before) + 1,
            'a leave slot must not take a number out of the company run')

    def _number_of(self, appointment):
        return int(appointment.appointment_no.rsplit('/', 1)[-1])

    def test_a_number_cannot_be_chosen_by_the_caller(self):
        # Like the calendar reference, the number is the system's to give.
        appointment = self.env['salon.appointment'].with_company(
            self.company_a).create(
            dict(self._values(self.branch_a), appointment_no='APP/09999'))
        self.assertNotEqual(appointment.appointment_no, 'APP/09999')

    def test_a_new_company_needs_no_sequence_set_up_by_hand(self):
        company = self._company('Number Test Company C')
        branch = self._branch(company, 'Number Test Branch C')
        self.assertEqual(self._create(branch).appointment_no, 'APP/00001')

    def test_the_prefix_can_be_set_per_company_without_a_code_change(self):
        sequence = self.env['salon.appointment']._company_appointment_sequence(
            self.company_a)
        sequence.prefix = 'BB/'
        self.assertEqual(self._create(self.branch_a).appointment_no[:3], 'BB/')
