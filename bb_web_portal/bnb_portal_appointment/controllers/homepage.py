# -*- coding: utf-8 -*-
import json

from odoo import fields, http
from odoo.http import request


class HomepageController(http.Controller):
    """Build the public homepage from website records without external feeds."""

    @http.route(['/', '/bnb-home'], type='http', auth='public', website=True, sitemap=True)
    def bnb_home(self, **kwargs):
        website = request.website
        company_ids = request.env.companies.ids or [request.env.company.id]
        Branch = request.env['beauty.branch'].sudo()
        Product = request.env['product.product'].sudo()
        BlogPost = request.env['blog.post'].sudo().with_context(website_id=website.id)

        branches = Branch.search([
            ('active', '=', True),
            ('company_id', 'in', company_ids),
        ], order='name')
        services = Product.search([
            ('active', '=', True),
            ('type', '=', 'service'),
            ('product_tmpl_id.is_appointment_service', '=', True),
            ('product_tmpl_id.branch_ids', '!=', False),
            ('product_tmpl_id.company_id', 'in', company_ids + [False]),
        ], order='sequence, name', limit=12)
        service_images = {
            'eyebrow threading': 'eyebroe_img.jpg',
            'hybrid tint': 'tint_henna_img.jpg',
            'brow lamination': 'brow_lam_img.jpg',
            'eyelash extension': 'ee_img.jpg',
            'body waxing': 'body_wax_img.jpg',
            'facials': 'facial_img.jpg',
            'spray tanning': 'spray_tan_img.jpg',
            'lash lift & tint': 'Lash-Lift-img.jpg',
            'henna tint': 'hbt_img.jpg',
        }
        service_data = []
        for service in services:
            service_name = service.name.strip().lower()
            image_name = next(
                (image for name, image in service_images.items() if name in service_name),
                '',
            )
            service_data.append({
                'record': service,
                'image_url': (
                    '/bnb_portal_appointment/static/img/%s' % image_name
                    if image_name else
                    '/web/image/product.product/%s/image_512' % service.id
                ),
            })

        posts = BlogPost.search([
            ('active', '=', True),
            ('website_published', '=', True),
            ('post_date', '<=', fields.Datetime.now()),
            '|', ('website_id', '=', False), ('website_id', '=', website.id),
        ], order='post_date desc, id desc', limit=50)

        def tagged(tag_name):
            return posts.filtered(
                lambda post: any(tag.name.strip().lower() == tag_name for tag in post.tag_ids)
            )[:6]

        def cover_url(post):
            try:
                cover = json.loads(post.cover_properties or '{}')
                image = cover.get('background-image', '')
                if image.startswith('url('):
                    return image[4:-1].strip('"\'')
            except (TypeError, ValueError):
                pass
            return ''

        def post_data(post):
            return {
                'title': post.name,
                'subtitle': post.subtitle or post.teaser or '',
                'url': post.website_url or '#',
                'image_url': cover_url(post),
                'content': post.content or '',
            }

        return request.render('bnb_portal_appointment.custom_home_view', {
            'homepage_data': {
                'branches': branches,
                'services': service_data,
                'promotions': [post_data(post) for post in tagged('promotion')],
                'testimonials': [post_data(post) for post in tagged('testimonial')],
                'gallery': [post_data(post) for post in tagged('gallery')],
            },
        })
