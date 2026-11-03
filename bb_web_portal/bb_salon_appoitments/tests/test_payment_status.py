# -*- coding: utf-8 -*-
from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAppointmentPaymentStatus(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.branch = cls.env['beauty.branch'].search([
            ('company_id', '=', cls.env.company.id),
        ], limit=1)
        if not cls.branch:
            pos_config = cls.env['pos.config'].search([
                ('company_id', '=', cls.env.company.id),
            ], limit=1) or cls.env['pos.config'].create({
                'name': 'Payment Status Test POS',
                'company_id': cls.env.company.id,
            })
            website = cls.env['website'].search([
                ('company_id', '=', cls.env.company.id),
            ], limit=1) or cls.env['website'].create({
                'name': 'Payment Status Test Website',
                'company_id': cls.env.company.id,
            })
            cls.branch = cls.env['beauty.branch'].create({
                'name': 'Payment Status Test Branch',
                'company_id': cls.env.company.id,
                'pos_config_id': pos_config.id,
                'website_id': website.id,
            })
        cls.service = cls.env['product.product'].create({
            'name': 'Payment Status Test Service',
            'type': 'service',
            'list_price': 42.98,
        })

    def _create_appointment(self):
        appointment = self.env['salon.appointment'].create({
            'branch_id': self.branch.id,
            'appointment_date': fields.Date.from_string('2026-08-04'),
            'customer_first_name': 'Payment',
            'customer_last_name': 'Test',
        })
        self.env['salon.appointment.service'].create({
            'appointment_id': appointment.id,
            'service_id': self.service.id,
            'duration': 0.5,
            'start_hour': 17.0,
        })
        appointment.invalidate_recordset()
        return appointment

    def test_completed_full_online_payment_is_partial_with_full_receipt(self):
        appointment = self._create_appointment()
        self.env['salon.appointment.payment'].create({
            'appointment_id': appointment.id,
            'payment_method': 'online',
            'payment_option': 'full',
            'payment_amount': appointment.total_amount,
            'payment_status': 'completed',
        })

        self.assertEqual(appointment.payment_status, 'partial')
        self.assertTrue(appointment.is_online_booking)
        self.assertEqual(appointment.online_payment_receipt_status, 'full_received')
        self.assertEqual(appointment.state, 'draft')
        self.assertFalse(any(
            'Payment Status: Unpaid -&gt; Partial' in str(body)
            or 'Payment Status: Unpaid -> Partial' in str(body)
            for body in appointment.message_ids.mapped('body')
        ))

    def test_payment_views_disallow_manual_changes(self):
        for xmlid in ('view_salon_appointment_payment_form',
                      'view_salon_appointment_payment_tree'):
            arch = self.env.ref('bb_salon_appoitments.' + xmlid)._get_combined_arch()
            for operation in ('create', 'edit', 'delete'):
                self.assertEqual(arch.get(operation), '0', (xmlid, operation))
        form = self.env.ref(
            'bb_salon_appoitments.view_salon_appointment_payment_form'
        )._get_combined_arch()
        for name in ('payment_reference', 'transaction_id', 'payment_provider',
                     'payment_amount', 'billing_address', 'discount_amount',
                     'refunded_amount'):
            self.assertTrue(form.xpath("//field[@name='%s']" % name))

    def test_payment_tab_is_readonly_but_notes_remain_editable(self):
        arch = self.env.ref(
            'bb_salon_appoitments.view_salon_appointment_form'
        )._get_combined_arch()
        payment_fields = arch.xpath("//page[@name='payments']//field[@name='payment_line_ids']")
        self.assertTrue(payment_fields)
        for field in payment_fields:
            self.assertEqual(field.get('readonly'), '1')
            for listing in field.xpath('./list'):
                for operation in ('create', 'edit', 'delete'):
                    self.assertEqual(listing.get(operation), '0')
        for name in ('notes', 'special_note'):
            fields = arch.xpath("//group[@name='appointment_notes']/field[@name='%s']" % name)
            self.assertTrue(fields)
            self.assertTrue(all(field.get('readonly') in (None, '0') for field in fields))

    def test_system_can_still_record_payment_and_refund_updates(self):
        appointment = self._create_appointment()
        payment = self.env['salon.appointment.payment'].create({
            'appointment_id': appointment.id,
            'payment_method': 'online',
            'payment_amount': 0.5,
            'payment_status': 'pending',
        })
        payment.write({
            'payment_reference': 'SYSTEM-PAYMENT-001',
            'transaction_id': 'SYSTEM-TRANSACTION-001',
            'payment_provider': 'NAB Gateway - Card',
            'payment_status': 'completed',
        })
        self.assertEqual(payment.payment_reference, 'SYSTEM-PAYMENT-001')
        self.assertEqual(payment.transaction_id, 'SYSTEM-TRANSACTION-001')
        self.assertEqual(payment.payment_provider, 'NAB Gateway - Card')
        self.assertEqual(payment.payment_status, 'completed')
        payment.write({
            'refunded_amount': 0.5,
            'refund_reference': 'SYSTEM-REFUND-001',
            'payment_status': 'refunded',
        })
        self.assertEqual(payment.refunded_amount, 0.5)
        self.assertEqual(payment.refund_reference, 'SYSTEM-REFUND-001')
        self.assertEqual(payment.payment_status, 'refunded')

    def test_completed_half_online_payment_is_partial_with_half_receipt(self):
        appointment = self._create_appointment()
        self.env['salon.appointment.payment'].create({
            'appointment_id': appointment.id,
            'payment_method': 'online',
            'payment_option': 'half',
            'payment_amount': appointment.currency_id.round(appointment.total_amount / 2),
            'payment_status': 'completed',
        })

        self.assertEqual(appointment.payment_status, 'partial')
        self.assertTrue(appointment.is_online_booking)
        self.assertEqual(appointment.online_payment_receipt_status, 'half_received')
        self.assertEqual(appointment.state, 'draft')

    def test_payment_update_chatter_is_combined_and_currency_formatted(self):
        appointment = self._create_appointment()
        payment = self.env['salon.appointment.payment'].create({
            'appointment_id': appointment.id,
            'payment_method': 'online',
            'payment_option': 'half',
            'payment_amount': 0.5,
            'payment_status': 'pending',
        })
        previous_message_ids = set(appointment.message_ids.ids)

        payment.write({
            'transaction_id': 'TEST-TRANSACTION-001',
            'payment_status': 'completed',
        })

        new_bodies = appointment.message_ids.filtered(
            lambda message: message.id not in previous_message_ids
        ).mapped('body')
        combined_body = ' '.join(str(body) for body in new_bodies)
        self.assertIn('Online Payment updated', combined_body)
        self.assertIn('0.50', combined_body)
        self.assertIn('Pending', combined_body)
        self.assertIn('Completed', combined_body)
        self.assertIn('TEST-TRANSACTION-001', combined_body)
        self.assertNotIn('Payment updated: 0.5', combined_body)
