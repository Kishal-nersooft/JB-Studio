from odoo import api, models


class Website(models.Model):
    _inherit = 'website'

    @api.model
    def _cleanup_custom_home(self):
        home_url = '/bnb-home'
        old_home_url = '/custom-home'
        allowed_company_ids = self.env.companies.ids or [self.env.company.id]

        image_replace_map = {
            '/theme_custom/static/src/img/icon-beautician.png': '/bnb_portal_appointment/static/img/choose_ico.png',
            '/theme_custom/static/src/img/icon-service.png': '/bnb_portal_appointment/static/img/choose_ico2.png',
            '/theme_custom/static/src/img/icon-affordable.png': '/bnb_portal_appointment/static/img/choose_ico3.png',
            '/theme_custom/static/src/img/icon-products.png': '/bnb_portal_appointment/static/img/choose_ico4.png',
            '/theme_custom/static/src/img/loyalty-img.jpg': '/bnb_portal_appointment/static/img/loyalty_img.png',
        }

        def _sanitize_arch(arch):
            if not arch:
                return arch
            result = arch
            for source, target in image_replace_map.items():
                result = result.replace(source, target)
            result = result.replace('/theme_custom/static/src/img/', '/bnb_portal_appointment/static/img/')
            return result

        obsolete_view_xmlids = [
            'bnb_portal_appointment.s_bnb_hero',
            'bnb_portal_appointment.s_bnb_services',
            'bnb_portal_appointment.s_bnb_about',
            'bnb_portal_appointment.s_bnb_features',
            'bnb_portal_appointment.s_bnb_testimonials',
            'bnb_portal_appointment.s_bnb_loyalty',
            'bnb_portal_appointment.s_bnb_newsletter',
            'bnb_portal_appointment.s_bnb_social',
            'bnb_portal_appointment.bnb_snippets',
        ]
        obsolete_views = self.env['ir.ui.view']
        for xmlid in obsolete_view_xmlids:
            view = self.env.ref(xmlid, raise_if_not_found=False)
            if view:
                obsolete_views |= view
        if obsolete_views:
            obsolete_views.sudo().unlink()

        # Reset inherited page customizations for this homepage to avoid layered/duplicated
        # hero captions from previous editor sessions.
        custom_home_page = self.env.ref('bnb_portal_appointment.custom_home_page', raise_if_not_found=False)
        root_home_view = custom_home_page.view_id if custom_home_page else self.env['ir.ui.view']
        if root_home_view:
            inherited_home_views = self.env['ir.ui.view'].sudo().search([('inherit_id', '=', root_home_view.id)])
            if inherited_home_views:
                inherited_home_views.unlink()

        # Sanitize any remaining homepage view architecture that still references theme_custom assets.
        candidate_views = self.env['ir.ui.view'].sudo().search([('arch_db', 'ilike', 'theme_custom/static/src/img/')])
        for candidate_view in candidate_views:
            if (
                candidate_view == root_home_view
                or candidate_view.inherit_id == root_home_view
                or (candidate_view.key and 'custom_home' in candidate_view.key)
                or (candidate_view.name and 'custom home' in candidate_view.name.lower())
            ):
                candidate_view.write({'arch_db': _sanitize_arch(candidate_view.arch_db)})

        # Apply custom home only on one target website, not globally on all websites.
        target_website = self.env.company.website_id
        if target_website and target_website.company_id.id not in allowed_company_ids:
            target_website = self.env['website']
        if not target_website:
            target_website = self.sudo().search([
                ('company_id', 'in', allowed_company_ids),
            ], limit=1)
        if not target_website:
            return

        target_website.sudo().write({'homepage_url': home_url})
        # Roll back old global setup from previous versions: other websites
        # must keep their own homepage instead of sharing this module homepage.
        other_websites = self.sudo().search([
            ('id', '!=', target_website.id),
            ('company_id', 'in', allowed_company_ids),
        ])
        other_websites.filtered(lambda w: w.homepage_url in (old_home_url, home_url)).write({'homepage_url': '/'})

        menu_home = self.env['website.menu'].sudo().search([
            ('website_id', '=', target_website.id),
            ('url', '=', '/'),
        ], limit=1)
        if menu_home:
            menu_home.write({'url': home_url, 'page_id': False})

        custom_menu = self.env.ref('bnb_portal_appointment.menu_custom_home', raise_if_not_found=False)
        if custom_menu and custom_menu.website_id == target_website:
            custom_menu.sudo().unlink()

        main_menu = self.env['website.menu'].sudo().search([
            ('website_id', '=', target_website.id),
            ('url', '=', '/'),
            ('parent_id', '=', False),
        ], limit=1)
        if main_menu:
            home_menus = self.env['website.menu'].sudo().search([
                ('website_id', '=', target_website.id),
                ('name', '=', 'Home'),
                ('parent_id', '=', main_menu.id),
                ('url', 'in', (old_home_url, home_url)),
            ])
            if len(home_menus) > 1:
                keep = menu_home if menu_home and menu_home in home_menus else home_menus[0]
                (home_menus - keep).unlink()

        # Also fix top-level home menu URL for other websites if they still
        # point to this module homepage from old global configuration.
        other_home_menus = self.env['website.menu'].sudo().search([
            ('website_id', 'in', other_websites.ids),
            ('name', '=', 'Home'),
            ('url', 'in', (old_home_url, home_url)),
        ])
        if other_home_menus:
            other_home_menus.write({'url': '/', 'page_id': False})
