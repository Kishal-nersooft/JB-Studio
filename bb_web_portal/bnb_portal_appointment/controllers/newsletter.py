from odoo import http, tools
from odoo.http import request
from odoo.addons.website_mass_mailing.controllers.main import MassMailController


class NewsletterController(http.Controller):
    @http.route('/bnb/newsletter/subscribe', type='http', auth='public', website=True,
                methods=['POST'], csrf=True)
    def subscribe(self, name='', email='', phone='', branch_id='', **kwargs):
        email = (email or '').strip()
        name = (name or '').strip()
        phone = (phone or '').strip()
        if not email or not tools.single_email_re.match(email):
            return request.redirect('/bnb-home?newsletter=invalid')

        mailing_list = request.env['mailing.list'].sudo().search([
            ('active', '=', True),
        ], order='id', limit=1)
        if not mailing_list:
            return request.redirect('/bnb-home?newsletter=unavailable')

        try:
            branch = request.env['beauty.branch'].sudo().browse(int(branch_id or 0)).exists()
        except (TypeError, ValueError):
            branch = request.env['beauty.branch']
        if branch and (not branch.active or branch.company_id not in (request.website.company_id, request.env.company, False)):
            branch = request.env['beauty.branch']
        contact = request.env['mailing.contact'].sudo().search([
            ('email', '=ilike', email),
        ], limit=1)
        if not contact:
            MassMailController.subscribe_to_newsletter('email', email, mailing_list.id, 'email', name)
            contact = request.env['mailing.contact'].sudo().search([
                ('email', '=ilike', email),
            ], limit=1)
        if contact:
            values = {}
            if name:
                values['name'] = name
            if phone:
                values['bnb_phone'] = phone
            if branch:
                values['bnb_store_id'] = branch.id
            if values:
                contact.write(values)
            subscription = request.env['mailing.subscription'].sudo().search([
                ('contact_id', '=', contact.id), ('list_id', '=', mailing_list.id),
            ], limit=1)
            if subscription:
                subscription.opt_out = False
            else:
                request.env['mailing.subscription'].sudo().create({
                    'contact_id': contact.id, 'list_id': mailing_list.id,
                })
        return request.redirect('/bnb-home?newsletter=success')
