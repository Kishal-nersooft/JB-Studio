from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    bnb_gift_card_order = fields.Boolean(copy=False)
    bnb_gift_card_amount = fields.Monetary(currency_field='currency_id', copy=False)
    bnb_gift_recipient_name = fields.Char(copy=False)
    bnb_gift_recipient_email = fields.Char(copy=False)
    bnb_gift_send_to_recipient = fields.Boolean(copy=False)
    bnb_gift_personalized_message = fields.Text(copy=False)
    bnb_gift_from = fields.Char(copy=False)
    bnb_gift_purchaser_first_name = fields.Char(copy=False)
    bnb_gift_purchaser_last_name = fields.Char(copy=False)
    bnb_gift_purchaser_email = fields.Char(copy=False)
    bnb_gift_purchaser_mobile = fields.Char(copy=False)

    def _send_reward_coupon_mail(self):
        recipient_orders = self.filtered(
            lambda order: order.bnb_gift_card_order and order.bnb_gift_send_to_recipient
            and order.bnb_gift_recipient_email
        )
        normal_orders = self - recipient_orders
        if normal_orders:
            super(SaleOrder, normal_orders)._send_reward_coupon_mail()
        for order in recipient_orders:
            for card in order._get_reward_coupons():
                template = card._get_default_template()
                if template:
                    template.send_mail(
                        card.id, force_send=False,
                        email_layout_xmlid='mail.mail_notification_light',
                        email_values={'email_to': order.bnb_gift_recipient_email},
                    )
