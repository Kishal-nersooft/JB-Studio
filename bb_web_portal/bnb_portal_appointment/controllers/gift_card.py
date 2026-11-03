from decimal import Decimal, InvalidOperation

from odoo import http
from odoo.http import request


class GiftCardController(http.Controller):
    FIXED_AMOUNTS = (Decimal('40'), Decimal('60'), Decimal('80'))

    def _gift_card_product(self):
        programs = request.env['loyalty.program'].sudo().search([
            ('active', '=', True), ('program_type', '=', 'gift_card'), ('ecommerce_ok', '=', True),
        ])
        for program in programs:
            product = program.trigger_product_ids.filtered(
                lambda item: item.active and item.sale_ok
            )[:1]
            if product:
                return program, product
        return request.env['loyalty.program'], request.env['product.product']

    @http.route('/gift-voucher', type='http', auth='public', website=True, sitemap=True)
    def gift_voucher(self, **kwargs):
        program, product = self._gift_card_product()
        if not product:
            return request.not_found()
        return request.render('bnb_portal_appointment.gift_voucher_page', {
            'gift_program': program, 'gift_product': product,
            'fixed_amounts': self.FIXED_AMOUNTS,
            'currency': request.website.currency_id or request.env.company.currency_id,
        })

    @http.route('/gift-voucher/submit', type='http', auth='public', website=True,
                methods=['POST'], csrf=True)
    def gift_voucher_submit(self, amount=None, send_to='self', recipient_name='',
                            recipient_email='', personalized_message='', gift_from='',
                            purchaser_first_name='', purchaser_last_name='', purchaser_email='',
                            purchaser_mobile='', **kwargs):
        program, product = self._gift_card_product()
        if not product:
            return request.not_found()
        try:
            gift_amount = Decimal(str(amount or '0')).quantize(Decimal('0.01'))
        except (InvalidOperation, ValueError):
            gift_amount = Decimal('0')
        if not gift_amount.is_finite() or gift_amount <= 0:
            return request.redirect('/gift-voucher?error=amount')
        if send_to not in ('self', 'recipient'):
            return request.redirect('/gift-voucher?error=recipient')
        recipient_email = (recipient_email or '').strip()
        if send_to == 'recipient' and ('@' not in recipient_email or '.' not in recipient_email.rsplit('@', 1)[-1]):
            return request.redirect('/gift-voucher?error=email')

        order = request.cart or request.website._create_cart()
        if not order:
            return request.redirect('/gift-voucher?error=cart')
        order_sudo = order.sudo()
        order_sudo.order_line.filtered(lambda line: line.product_id == product).unlink()
        order_sudo._cart_add(product.id, 1)
        gift_line = order_sudo.order_line.filtered(lambda line: line.product_id == product)[:1]
        if not gift_line:
            return request.redirect('/gift-voucher?error=cart')
        gift_line.write({'price_unit': float(gift_amount)})
        order_sudo.write({
            'bnb_gift_card_order': True,
            'bnb_gift_card_amount': float(gift_amount),
            'bnb_gift_recipient_name': (recipient_name or '').strip(),
            'bnb_gift_recipient_email': recipient_email if send_to == 'recipient' else False,
            'bnb_gift_send_to_recipient': send_to == 'recipient',
            'bnb_gift_personalized_message': (personalized_message or '').strip(),
            'bnb_gift_from': (gift_from or '').strip(),
            'bnb_gift_purchaser_first_name': (purchaser_first_name or '').strip(),
            'bnb_gift_purchaser_last_name': (purchaser_last_name or '').strip(),
            'bnb_gift_purchaser_email': (purchaser_email or '').strip(),
            'bnb_gift_purchaser_mobile': (purchaser_mobile or '').strip(),
        })
        return request.redirect('/shop/checkout')
