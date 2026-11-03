from odoo.tests.common import TransactionCase, tagged

from ..models.mail_mail import BLOCK_EXTERNAL_EMAILS_PARAM, SUPPRESSION_REASON


@tagged('post_install', '-at_install')
class TestExternalEmailSuppression(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.internal_email = 'employee-mail-test@example.com'
        cls.customer_email = 'customer-mail-test@example.net'
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Email Test Employee',
            'work_email': cls.internal_email,
        })
        cls.customer = cls.env['res.partner'].create({
            'name': 'Email Test Customer',
            'email': cls.customer_email,
            'customer_rank': 1,
        })
        cls.env['ir.config_parameter'].sudo().set_param(
            BLOCK_EXTERNAL_EMAILS_PARAM, 'True'
        )

    def _mail(self, **values):
        return self.env['mail.mail'].create({
            'subject': 'Recipient suppression test',
            'body_html': '<p>Test</p>',
            'email_from': 'notifications@example.org',
            **values,
        })

    def test_customer_only_email_is_cancelled_without_smtp(self):
        mail = self._mail(recipient_ids=[(6, 0, self.customer.ids)])
        self.assertTrue(mail.send(raise_exception=True))
        self.assertEqual(mail.state, 'cancel')
        self.assertEqual(mail.failure_reason, SUPPRESSION_REASON)

    def test_internal_and_customer_recipients_keep_only_internal_email(self):
        mail = self._mail(
            email_to='%s, %s' % (self.internal_email, self.customer_email)
        )
        allowed = mail._bb_internal_recipient_emails()
        outgoing = mail.with_context(
            bb_internal_recipient_emails=tuple(allowed)
        )._prepare_outgoing_list()
        self.assertEqual(len(outgoing), 1)
        self.assertIn(self.internal_email, outgoing[0]['email_to_normalized'])
        self.assertNotIn(self.customer_email, outgoing[0]['email_to_normalized'])

    def test_disabled_setting_leaves_customer_email_untouched(self):
        self.env['ir.config_parameter'].sudo().set_param(
            BLOCK_EXTERNAL_EMAILS_PARAM, 'False'
        )
        mail = self._mail(email_to=self.customer_email)
        outgoing = mail._prepare_outgoing_list()
        self.assertIn(self.customer_email, outgoing[0]['email_to_normalized'])
