import logging

from odoo import models, tools


_logger = logging.getLogger(__name__)

BLOCK_EXTERNAL_EMAILS_PARAM = (
    'bb_salon_appoitments.block_external_emails_during_testing'
)
SUPPRESSION_REASON = (
    'Cancelled because customer/external email delivery is disabled during testing.'
)


class MailMail(models.Model):
    _inherit = 'mail.mail'

    def _bb_external_email_block_enabled(self):
        value = self.env['ir.config_parameter'].sudo().get_param(
            BLOCK_EXTERNAL_EMAILS_PARAM, 'False'
        )
        return str(value).strip().lower() in ('1', 'true', 'yes', 'on')

    def _bb_internal_recipient_emails(self):
        Users = self.env['res.users'].sudo().with_context(active_test=False)
        Employees = self.env['hr.employee'].sudo().with_context(active_test=False)
        users = Users.search([('active', '=', True), ('share', '=', False)])
        employees = Employees.search([('active', '=', True)])

        raw_emails = users.mapped('email') + users.mapped('partner_id.email')
        for field_name in ('work_email', 'private_email'):
            if field_name in Employees._fields:
                raw_emails += employees.mapped(field_name)
        if 'user_id' in Employees._fields:
            raw_emails += employees.mapped('user_id.email')

        return {
            normalized
            for email in raw_emails
            for normalized in tools.mail.email_normalize_all(email or '')
        }

    @staticmethod
    def _bb_filter_addresses(addresses, allowed_emails):
        return [
            address
            for address in addresses
            if set(tools.mail.email_normalize_all(address or '')) & allowed_emails
        ]

    def _bb_has_internal_recipient(self, allowed_emails):
        self.ensure_one()
        recipient_emails = []
        recipient_emails.extend(tools.mail.email_normalize_all(self.email_to or ''))
        recipient_emails.extend(tools.mail.email_normalize_all(self.email_cc or ''))
        for partner in self.recipient_ids:
            recipient_emails.extend(tools.mail.email_normalize_all(partner.email or ''))
        return bool(set(recipient_emails) & allowed_emails)

    def _bb_cancel_external_email(self):
        outgoing = self.filtered(lambda mail: mail.state == 'outgoing')
        if not outgoing:
            return
        outgoing.sudo().write({
            'state': 'cancel',
            'failure_type': False,
            'failure_reason': SUPPRESSION_REASON,
        })
        notifications = self.env['mail.notification'].sudo().search([
            ('mail_mail_id', 'in', outgoing.ids),
            ('notification_type', '=', 'email'),
            ('notification_status', 'not in', ('sent', 'canceled')),
        ])
        notifications.write({
            'notification_status': 'canceled',
            'failure_type': False,
            'failure_reason': SUPPRESSION_REASON,
        })
        _logger.info(
            'Cancelled %s customer/external email(s) while testing suppression is enabled.',
            len(outgoing),
        )

    def _bb_cancel_external_notifications(self, allowed_emails):
        notifications = self.env['mail.notification'].sudo().search([
            ('mail_mail_id', 'in', self.ids),
            ('notification_type', '=', 'email'),
            ('notification_status', 'not in', ('sent', 'canceled')),
        ])
        blocked = notifications.filtered(lambda notification: not (
            set(tools.mail.email_normalize_all(
                notification.mail_email_address
                or notification.res_partner_id.email
                or ''
            )) & allowed_emails
        ))
        blocked.write({
            'notification_status': 'canceled',
            'failure_type': False,
            'failure_reason': SUPPRESSION_REASON,
        })
        if blocked:
            _logger.info(
                'Cancelled %s external recipient notification(s) from mixed emails.',
                len(blocked),
            )

    def _prepare_outgoing_list(self, mail_server=False, doc_to_followers=None):
        email_list = super()._prepare_outgoing_list(
            mail_server=mail_server,
            doc_to_followers=doc_to_followers,
        )
        allowed_emails = self.env.context.get('bb_internal_recipient_emails')
        if allowed_emails is None:
            return email_list
        allowed_emails = set(allowed_emails)

        filtered_list = []
        for email_values in email_list:
            email_values = dict(email_values)
            email_values['email_to'] = self._bb_filter_addresses(
                email_values.get('email_to', []), allowed_emails
            )
            email_values['email_cc'] = self._bb_filter_addresses(
                email_values.get('email_cc', []), allowed_emails
            )
            normalized = []
            for address in email_values['email_to'] + email_values['email_cc']:
                normalized.extend(tools.mail.email_normalize_all(address or ''))
            email_values['email_to_normalized'] = normalized
            if email_values['email_to'] or email_values['email_cc']:
                filtered_list.append(email_values)
        return filtered_list

    def send(self, auto_commit=False, raise_exception=False, post_send_callback=None):
        if not self._bb_external_email_block_enabled():
            return super().send(
                auto_commit=auto_commit,
                raise_exception=raise_exception,
                post_send_callback=post_send_callback,
            )

        allowed_emails = self._bb_internal_recipient_emails()
        outgoing = self.filtered(lambda mail: mail.state == 'outgoing')
        blocked = outgoing.filtered(
            lambda mail: not mail._bb_has_internal_recipient(allowed_emails)
        )
        blocked._bb_cancel_external_email()

        sendable = self - blocked
        result = True
        if sendable:
            sendable._bb_cancel_external_notifications(allowed_emails)
            result = super(MailMail, sendable.with_context(
                bb_internal_recipient_emails=tuple(allowed_emails)
            )).send(
                auto_commit=auto_commit,
                raise_exception=raise_exception,
                post_send_callback=post_send_callback,
            )
        if blocked and post_send_callback:
            post_send_callback(blocked.ids)
        return result
