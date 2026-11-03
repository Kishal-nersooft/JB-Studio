"""Explicit booking origins survive imports and ordinary appointment edits."""
from odoo.tests import TransactionCase, tagged
from .test_payment_first_checkout import PaymentFirstFixture


@tagged('post_install', '-at_install')
class TestBookingSourcePreservation(PaymentFirstFixture, TransactionCase):
    def _appointment(self, **updates):
        vals = {'customer_first_name': 'Source', 'customer_last_name': 'Test',
                'branch_id': self.branch.id, 'appointment_date': self.day}
        vals.update(updates)
        return self.env['salon.appointment'].with_context(
            skip_mobile_message_sms=True, skip_auto_consultation_forms=True).create(vals)

    def test_explicit_online_type_normalizes_imported_flags(self):
        appt = self._appointment(appointment_type='online', is_walk_in=True)
        self.assertTrue(appt.booked_online)
        self.assertFalse(appt.is_walk_in)

    def test_online_origin_survives_counter_edits(self):
        appt = self._appointment(booked_online=True)
        appt.write({'is_walk_in': True, 'notes': 'Updated at POS'})
        self.assertTrue(appt.booked_online)
        self.assertEqual(appt.appointment_type, 'online')
        self.assertFalse(appt.is_walk_in)

    def test_import_update_to_online_type_preserves_origin(self):
        appt = self._appointment(is_walk_in=True)
        appt.write({'appointment_type': 'online'})
        self.assertTrue(appt.booked_online)
        self.assertFalse(appt.is_walk_in)

    def test_manual_booking_with_online_payment_stays_manual(self):
        appt = self._appointment(appointment_type='instore', is_walk_in=True)
        self.env['salon.appointment.payment'].create({
            'appointment_id': appt.id, 'payment_method': 'online',
            'payment_status': 'completed', 'payment_amount': 10,
        })
        self.assertTrue(appt.is_online_booking)
        self.assertFalse(appt.booked_online)
        self.assertTrue(appt.is_walk_in)
        self.assertEqual(appt.appointment_type, 'instore')

    def test_mixed_recordset_edit_preserves_each_origin(self):
        online = self._appointment(booked_online=True)
        manual = self._appointment(is_walk_in=True)
        (online | manual).write({'is_walk_in': True})
        self.assertFalse(online.is_walk_in)
        self.assertTrue(manual.is_walk_in)

    def test_odoo_import_preserves_explicit_online_source(self):
        result = self.env['salon.appointment'].with_context(
            skip_mobile_message_sms=True, skip_auto_consultation_forms=True).load(
                ['customer_first_name', 'customer_last_name', 'branch_id/.id',
                 'appointment_date', 'appointment_type', 'is_walk_in'],
                [['Imported', 'Online', str(self.branch.id), str(self.day), 'online', 'True']])
        self.assertTrue(result['ids'], result['messages'])
        appt = self.env['salon.appointment'].browse(result['ids'])
        self.assertTrue(appt.booked_online)
        self.assertFalse(appt.is_walk_in)
