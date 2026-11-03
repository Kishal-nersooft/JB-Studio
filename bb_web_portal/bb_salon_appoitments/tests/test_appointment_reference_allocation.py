"""How appointment references are handed out.

References come from the global APPT sequence and only ever go forwards. A
deleted appointment does not give its number back, and emptying the table does
not restart the numbering -- unlink() says as much: it deletes through the ORM
cascades "without mutating the live sequence".

That is a deliberate change from the earlier behaviour, where a deletion freed
its number for the next booking to pick up. Rewinding a live sequence is a race
between two people booking at once, and a reference that can be reused is a
poor thing to put on a document that settles money. These tests pin the rule
that replaced it.

Nothing here asserts an absolute reference like 'APPT00001'. The sequence is a
database object that does not roll back with the test transaction, so its
value depends on everything that ran before; what is worth pinning is that
references are unique, ordered, and never handed out twice.
"""

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAppointmentReferenceAllocation(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        company = cls.env.company
        website = cls.env['website'].search([
            ('company_id', '=', company.id),
        ], limit=1) or cls.env['website'].create({
            'name': 'Appointment Reference Test Website',
            'company_id': company.id,
        })
        pos_config = cls.env['pos.config'].search([
            ('company_id', '=', company.id),
        ], limit=1) or cls.env['pos.config'].create({
            'name': 'Appointment Reference Test POS',
            'company_id': company.id,
        })
        cls.branch = cls.env['beauty.branch'].create({
            'name': 'Appointment Reference Test Branch',
            'company_id': company.id,
            'pos_config_id': pos_config.id,
            'website_id': website.id,
        })
        cls.service = cls.env['product.product'].create({
            'name': 'Appointment Reference Test Service',
            'type': 'service',
            'list_price': 25.0,
        })

    def _values(self, appointment_date='2026-08-20'):
        return {
            'branch_id': self.branch.id,
            'company_id': self.env.company.id,
            'appointment_date': fields.Date.from_string(appointment_date),
        }

    def _number(self, appointment):
        """The numeric part of a reference, as the model reads it."""
        return self.env['salon.appointment']._appointment_reference_number(
            appointment.appointment_ref,
        )

    def test_references_are_unique_and_ordered(self):
        appointments = self.env['salon.appointment'].create([
            self._values('2026-08-20'),
            self._values('2026-08-21'),
            self._values('2026-08-22'),
        ])
        references = appointments.mapped('appointment_ref')
        self.assertTrue(all(ref.startswith('APPT') for ref in references))
        self.assertEqual(len(set(references)), 3, 'references must be unique')

        numbers = [self._number(appointment) for appointment in appointments]
        self.assertEqual(numbers, sorted(numbers))
        self.assertEqual(numbers[1], numbers[0] + 1)
        self.assertEqual(numbers[2], numbers[1] + 1)

    def test_a_deleted_reference_is_not_handed_out_again(self):
        """The gap a deletion leaves stays a gap."""
        appointments = self.env['salon.appointment'].create([
            self._values('2026-08-20'),
            self._values('2026-08-21'),
            self._values('2026-08-22'),
        ])
        issued = set(appointments.mapped('appointment_ref'))
        highest = max(self._number(appointment) for appointment in appointments)

        appointments[1].unlink()
        replacement = self.env['salon.appointment'].create(
            self._values('2026-08-23'),
        )

        self.assertNotIn(
            replacement.appointment_ref, issued,
            'a deleted appointment must not give its reference back',
        )
        self.assertGreater(self._number(replacement), highest)

    def test_emptying_the_table_does_not_restart_numbering(self):
        appointments = self.env['salon.appointment'].create([
            self._values('2026-08-20'),
            self._values('2026-08-21'),
            self._values('2026-08-22'),
        ])
        issued = set(appointments.mapped('appointment_ref'))
        highest = max(self._number(appointment) for appointment in appointments)
        appointments.unlink()
        self.assertFalse(self.env['salon.appointment'].search([
            ('appointment_ref', 'in', list(issued)),
        ]))

        first_after = self.env['salon.appointment'].create(
            self._values('2026-08-25'),
        )

        self.assertNotIn(first_after.appointment_ref, issued)
        self.assertGreater(self._number(first_after), highest)

    def test_owned_service_payment_and_duplicate_records_are_cascaded(self):
        parent = self.env['salon.appointment'].create(self._values())
        child_values = self._values('2026-08-21')
        child_values['duplicate_parent_id'] = parent.id
        child = self.env['salon.appointment'].create(child_values)
        service_line = self.env['salon.appointment.service'].create({
            'appointment_id': parent.id,
            'service_id': self.service.id,
            'duration': 0.5,
            'start_hour': 10.0,
        })
        payment_line = self.env['salon.appointment.payment'].create({
            'appointment_id': parent.id,
            'payment_method': 'cash',
            'payment_amount': 25.0,
            'payment_status': 'pending',
        })
        parent_reference = parent.appointment_ref
        parent_number = self._number(parent)

        parent.unlink()

        self.assertFalse(parent.exists())
        self.assertFalse(child.exists())
        self.assertFalse(service_line.exists())
        self.assertFalse(payment_line.exists())

        replacement = self.env['salon.appointment'].create(
            self._values('2026-08-22'),
        )
        self.assertNotEqual(replacement.appointment_ref, parent_reference)
        self.assertGreater(self._number(replacement), parent_number)
