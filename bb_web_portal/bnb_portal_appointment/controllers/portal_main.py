# -*- coding: utf-8 -*-
import base64
from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.http import request, route
from odoo.addons.portal.controllers import portal

from .booking_helpers import (
    _safe_int,
)


class MainController(portal.CustomerPortal):
    def _service_sales_quantities(self, env, branch, products):
        """Net sold units for eligible services at this branch's POS only."""
        if not branch or not branch.pos_config_id or not products:
            return {}
        products = products.filtered(lambda p:
            branch in p.product_tmpl_id.branch_ids
            and (not p.company_id or p.company_id == branch.company_id))
        rows = env['pos.order.line'].sudo()._read_group([
            ('product_id', 'in', products.ids),
            ('order_id.config_id', '=', branch.pos_config_id.id),
            ('order_id.company_id', '=', branch.company_id.id),
            ('order_id.state', 'in', ['paid', 'done', 'invoiced']),
        ], ['product_id'], ['qty:sum'])
        return {product.id: quantity for product, quantity in rows if quantity > 0}

    @route('/custom-home', type='http', auth='public', website=True, sitemap=False)
    def redirect_custom_home(self, **kw):
        return request.redirect('/bnb-home')

    @route(['/book-online', '/book-online/<int:website_id>', '/book-online/<string:step>', '/book-online/<int:website_id>/<string:step>'], type='http', auth="public", website=True)
    def book_online(self, website_id=None, step=None, branch_id=None, **kw):
        current_website = None
        social_auth_ok = kw.get('social_auth') == 'success'
        branch_id = _safe_int(branch_id)
        allowed_company_ids = request.env.companies.ids or [request.env.company.id]
        allowed_steps = ['location', 'service', 'date', 'beautician', 'customer', 'payment', 'confirmation']
        if step and step not in allowed_steps:
            base_url = f"/book-online/{website_id}" if website_id else "/book-online"
            if branch_id:
                return request.redirect(f"{base_url}?branch_id={branch_id}")
            return request.redirect(base_url)
        if step in ['service', 'date', 'beautician', 'customer', 'payment', 'confirmation'] and not branch_id:
            base_url = f"/book-online/{website_id}" if website_id else "/book-online"
            return request.redirect(base_url)

        if website_id:
            current_website = request.env['website'].sudo().search(
                [
                    ('id', '=', website_id),
                    '|',
                    ('company_id', '=', False),
                    ('company_id', 'in', allowed_company_ids),
                ],
                limit=1,
            )
            if not current_website:
                current_website = None
            else:
                # Keep website context stable on localhost/single-domain setups.
                current_website._force()

        if branch_id and not current_website:
            branch = request.env['beauty.branch'].sudo().search([
                ('id', '=', branch_id),
                ('company_id', 'in', allowed_company_ids),
            ], limit=1)
            if branch and branch.website_id and (
                not branch.website_id.company_id
                or branch.website_id.company_id.id in allowed_company_ids
            ):
                current_website = branch.website_id
            elif branch and branch.company_id:
                company_website = request.env['website'].sudo().search([
                    ('company_id', '=', branch.company_id.id),
                    ('company_id', 'in', allowed_company_ids),
                ], limit=1)
                if company_website:
                    current_website = company_website

        if not current_website:
            fallback_website = request.website
            if fallback_website and (
                not fallback_website.company_id
                or fallback_website.company_id.id in allowed_company_ids
            ):
                current_website = fallback_website
            else:
                current_website = request.env['website'].sudo().search([
                    '|',
                    ('company_id', '=', False),
                    ('company_id', 'in', allowed_company_ids),
                ], limit=1)
                if not current_website:
                    current_website = request.env['website'].sudo()

        branch_domain = [
            ('company_id', 'in', allowed_company_ids),
            ('active', '=', True),
        ]
        if current_website and current_website.company_id:
            branch_domain.append(('company_id', '=', current_website.company_id.id))
        branches = request.env['beauty.branch'].sudo().search(branch_domain)

        branches_data = []
        for branch in branches:
            branch_image_url = None
            if branch.image:
                try:
                    image_data = base64.b64decode(branch.image)
                    image_b64 = base64.b64encode(image_data).decode('utf-8')
                    branch_image_url = f'data:image/png;base64,{image_b64}'
                except:
                    branch_image_url = None

            branches_data.append({
                'id': branch.id,
                'name': branch.name,
                'city': branch.city,
                'state_id': branch.state_id,
                'image_url': branch_image_url,
                'saturday_surcharge_percent': branch.saturday_surcharge_percent or 0.0,
                'sunday_surcharge_percent': branch.sunday_surcharge_percent or 0.0,
            })

        # NEW: Get parent and child categories
        parent_categories = []
        service_categories = []
        selected_branch = None
        selected_branch_image_url = None
        show_services = False
        booking_fee = 0.0
        branch_tz = None
        today = fields.Date.today()
        today_count = request.env['salon.appointment'].sudo().search_count([
            ('create_date', '>=', today),
            ('create_date', '<', today + relativedelta(days=1)),
            ('company_id', 'in', allowed_company_ids),
        ])

        if branch_id:
            show_services = True
            selected_branch_domain = [
                ('id', '=', branch_id),
                ('company_id', 'in', allowed_company_ids),
            ]
            if current_website and current_website.company_id:
                selected_branch_domain.append(('company_id', '=', current_website.company_id.id))
            selected_branch = request.env['beauty.branch'].sudo().search(
                selected_branch_domain,
                limit=1,
            )

            if selected_branch:
                booking_fee = selected_branch.booking_fee or 0.0
                branch_tz = selected_branch.tz
                branch_company = selected_branch.company_id or (current_website.company_id if current_website and current_website.company_id else request.env.company)

                if selected_branch.image:
                    try:
                        image_data = base64.b64decode(selected_branch.image)
                        image_b64 = base64.b64encode(image_data).decode('utf-8')
                        selected_branch_image_url = f'data:image/png;base64,{image_b64}'
                    except:
                        selected_branch_image_url = None

                currency = branch_company.currency_id or request.env.company.currency_id

                all_products = request.env['product.product'].sudo().search([
                    ('type', '=', 'service'),
                    ('product_tmpl_id.is_appointment_service', '=', True),
                    ('product_tmpl_id.branch_ids', 'in', [branch_id]),
                    ('product_tmpl_id.company_id', 'in', [branch_company.id, False]),
                    ('active', '=', True)
                ])

                categories = all_products.mapped('categ_id')
                sales_quantities = self._service_sales_quantities(
                    request.env, selected_branch, all_products)
                parent_set = categories.mapped('parent_id')

                for sub_parent in parent_set:
                    if sub_parent:
                        parent_categories.append({
                            'id': sub_parent.id,
                            'name': sub_parent.name
                        })

                for category in categories:
                    # Only get SERVICE type products with is_appointment_service = True
                    products = all_products.filtered(lambda p: p.categ_id.id == category.id)

                    valid_products = []
                    for p in products:
                        if hasattr(p.product_tmpl_id, 'beautician_line_ids') and p.product_tmpl_id.beautician_line_ids:
                            company_beauticians = p.product_tmpl_id.beautician_line_ids.filtered(
                                lambda l: l.beautician_id.company_id.id == branch_company.id
                            )
                            if company_beauticians:
                                valid_products.append(p)

                    if valid_products:
                        service_categories.append({
                            'id': category.id,
                            'name': category.name,
                            'parent_id': category.parent_id.id,
                            'product_ids': [{
                                'id': p.id,
                                'sold_quantity': sales_quantities.get(p.id, 0),
                                'name': p.name,
                                'list_price': p.list_price,
                                'formatted_price': currency.format(p.list_price),
                                'service_duration_display': getattr(p, 'service_duration_display', '1h'),
                                'description_sale': p.description_sale or 'No description available.'
                            } for p in valid_products]
                        })

        # Get Stripe publishable key for inline payment
        stripe_publishable_key = ''
        stripe_company = current_website.company_id if current_website and current_website.company_id else request.env.company
        stripe_provider = request.env['payment.provider'].sudo().search([
            ('code', '=', 'stripe'),
            ('state', 'in', ['enabled', 'test']),
            '|',
            ('company_id', '=', False),
            ('company_id', '=', stripe_company.id),
        ], limit=1)
        if stripe_provider:
            stripe_publishable_key = stripe_provider.stripe_publishable_key or ''

        return request.render("bnb_portal_appointment.salon_booking_main", {
            'branches': branches_data,
            'parent_categories': parent_categories,
            'service_categories': service_categories,
            'selected_branch_id': branch_id if branch_id else None,
            'selected_branch': selected_branch,
            'selected_branch_image_url': selected_branch_image_url,
            'show_services': show_services,
            'today_appointments_count': today_count,
            'booking_fee': booking_fee,
            'branch_tz': branch_tz,
            'current_website': current_website,
            'stripe_publishable_key': stripe_publishable_key,
        })
