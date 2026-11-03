from lxml import html

from odoo.addons.http_routing.tests.common import MockRequest
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPaymentNavigation(TransactionCase):
    def test_payment_links_and_regular_menu_are_rendered_separately(self):
        website = self.env['website'].search([], limit=1)
        targets = {
            '/bnb-home': 'https://browzandbeauty.com.au/',
            '/shop': 'https://browzandbeauty.com.au/products/',
            '/blog': 'https://browzandbeauty.com.au/beauty-blog/',
            '/helpdesk': 'https://browzandbeauty.com.au/contact/',
            '/contactus': 'https://browzandbeauty.com.au/contact/',
            '/book-online': 'https://browzandbeauty.com.au/book-online/',
            '/jobs': None,
            '/slides': None,
        }
        with MockRequest(self.env, website=website, url_root='http://localhost/'):
            for url, target in targets.items():
                menu = self.env['website.menu'].create({
                    'name': 'Navigation test', 'url': url,
                    'website_id': website.id, 'parent_id': website.menu_id.id,
                })
                for mobile in (False, True):
                    # A regular page has no payment-specific QWeb variable.
                    regular = str(self.env['ir.qweb']._render(
                        'website.submenu', {'submenu': menu, 'is_mobile': mobile}))
                    payment = str(self.env['ir.qweb']._render(
                        'website.submenu', {'submenu': menu, 'is_mobile': mobile,
                                            'bnb_payment_navigation': True}))
                    self.assertEqual(html.fromstring(regular).xpath('//a/@href'), [url])
                    links = html.fromstring('<ul>' + payment + '</ul>').xpath('//a/@href')
                    self.assertEqual(links, [target] if target else [])

    def test_payment_logo_returns_to_live_site(self):
        website = self.env['website'].search([], limit=1)
        with MockRequest(self.env, website=website, url_root='http://localhost/'):
            for payment, expected in (
                (False, '/'), (True, 'https://browzandbeauty.com.au/'),
            ):
                rendered = str(self.env['ir.qweb']._render(
                    'website.placeholder_header_brand', {
                        'website': website, 'bnb_payment_navigation': payment,
                    }))
                self.assertEqual(html.fromstring(rendered).xpath('//a/@href'), [expected])

    def test_payment_contact_button_uses_live_contact_page(self):
        website = self.env['website'].search([], limit=1)
        with MockRequest(self.env, website=website, url_root='http://localhost/'):
            for payment, expected in (
                (False, '/contactus'), (True, 'https://browzandbeauty.com.au/contact/'),
            ):
                rendered = str(self.env['ir.qweb']._render(
                    'website.placeholder_header_call_to_action', {
                        'website': website, 'bnb_payment_navigation': payment,
                    }))
                self.assertEqual(html.fromstring(rendered).xpath('//a/@href'), [expected])

    def test_hide_checkbox_controls_desktop_and_mobile_navigation(self):
        website = self.env['website'].search([], limit=1)
        Menu = self.env['website.menu']
        public = website.user_id
        for url in ('/jobs', '/slides', '/custom-menu'):
            menu = Menu.create({'name': 'Visibility test', 'url': url,
                               'website_id': website.id, 'parent_id': website.menu_id.id})
            self.assertFalse(menu.bnb_hide_from_navigation)
            for user in (self.env.user, public):
                env = self.env(user=user)
                visible_menu = menu.with_env(env)
                with MockRequest(env, website=website.with_env(env), url_root='http://localhost/'):
                    for mobile in (False, True):
                        menu.bnb_hide_from_navigation = True
                        self.assertFalse(visible_menu.is_visible)
                        rendered = str(env['ir.qweb']._render('website.submenu', {
                            'submenu': visible_menu, 'is_mobile': mobile,
                        }))
                        self.assertEqual(html.fromstring('<ul>' + rendered + '</ul>').xpath('//a'), [])
                        menu.bnb_hide_from_navigation = False
                        self.assertTrue(visible_menu.is_visible)
                        rendered = str(env['ir.qweb']._render('website.submenu', {
                            'submenu': visible_menu, 'is_mobile': mobile,
                        }))
                        self.assertEqual(html.fromstring(rendered).xpath('//a/@href'), [url])
            self.assertTrue(menu.exists())

    def test_hide_checkbox_hides_dropdown_and_hidden_children(self):
        website = self.env['website'].search([], limit=1)
        Menu = self.env['website.menu']
        parent = Menu.create({'name': 'Dropdown test', 'url': '#',
                             'website_id': website.id, 'parent_id': website.menu_id.id})
        child = Menu.create({'name': 'Child test', 'url': '/custom-child',
                            'website_id': website.id, 'parent_id': parent.id})
        with MockRequest(self.env, website=website, url_root='http://localhost/'):
            for mobile in (False, True):
                parent.bnb_hide_from_navigation = True
                rendered = str(self.env['ir.qweb']._render('website.submenu', {
                    'submenu': parent, 'is_mobile': mobile, 'is_vertical_nav': mobile,
                }))
                self.assertEqual(html.fromstring('<ul>' + rendered + '</ul>').xpath('//a'), [])
                parent.bnb_hide_from_navigation = False
                child.bnb_hide_from_navigation = True
                rendered = str(self.env['ir.qweb']._render('website.submenu', {
                    'submenu': parent, 'is_mobile': mobile, 'is_vertical_nav': mobile,
                }))
                self.assertEqual(html.fromstring('<ul>' + rendered + '</ul>').xpath('//a'), [])
                child.bnb_hide_from_navigation = False
                rendered = str(self.env['ir.qweb']._render('website.submenu', {
                    'submenu': parent, 'is_mobile': mobile, 'is_vertical_nav': mobile,
                }))
                self.assertIn('Child test', rendered)

    def test_unhiding_does_not_publish_a_private_page(self):
        website = self.env['website'].search([], limit=1)
        page = self.env['website.page'].create({
            'name': 'Private navigation test', 'url': '/private-navigation-test',
            'is_published': False, 'website_id': website.id,
            'type': 'qweb', 'arch': '<t name="Private navigation test">Private</t>',
        })
        menu = self.env['website.menu'].create({
            'name': 'Private page', 'page_id': page.id, 'website_id': website.id,
            'parent_id': website.menu_id.id,
        }).with_user(website.user_id)
        self.assertFalse(menu.is_visible)
