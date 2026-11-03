import json

from odoo.addons.http_routing.tests.common import MockRequest
from odoo.tests import HttpCase, TransactionCase, tagged
from odoo.addons.bb_salon_appoitments.tests.branch_fixture import ensure_branch


@tagged('post_install', '-at_install')
class TestWebsiteSnippetRendering(TransactionCase):

    def test_homepage_snippets_render_without_controller_context(self):
        website = self.env['website'].search([], limit=1)

        with MockRequest(self.env, website=website):
            snippets = self.env['ir.ui.view'].render_public_asset(
                'website.snippets'
            )

        self.assertIn('BnB Newsletter', snippets)
        self.assertIn('BnB Services', snippets)

    def test_newsletter_snippet_lists_branches_for_a_website(self):
        website = self.env['website'].search([], limit=1)
        branch = ensure_branch(
            self.env, name='Snippet Branch',
            company=website.company_id or self.env.company)

        # The snippet body, not the snippets panel: the panel only carries
        # names and thumbnails, so the branch <select> is not in it. Rendered
        # through ir.qweb because the snippet view itself is private.
        with MockRequest(self.env, website=website):
            rendered = self.env['ir.qweb'].sudo()._render(
                'bnb_portal_appointment.s_bnb_v2_newsletter'
            )

        self.assertIn('Select Store', rendered)
        # By id, not name: names are HTML-escaped in the markup.
        self.assertIn(f'value="{branch.id}"', rendered)


@tagged('post_install', '-at_install')
class TestWebsiteSnippetRenderingOverRpc(HttpCase):
    """The website editor renders snippets over jsonrpc.

    MockRequest cannot stand in for this: core guards the website branch of
    render_public_asset with hasattr(request, 'website'), and a Mock always
    has the attribute, so the mocked request takes a path the editor never
    takes. Only a real request on a non-website route reproduces it.
    """

    def test_newsletter_snippet_renders_with_no_website_on_the_request(self):
        self.authenticate('admin', 'admin')
        response = self.url_open(
            '/web/dataset/call_kw',
            data=json.dumps({
                'jsonrpc': '2.0',
                'method': 'call',
                'params': {
                    'model': 'ir.ui.view',
                    'method': 'render_public_asset',
                    'args': ['website.snippets'],
                    'kwargs': {},
                },
            }),
            headers={'Content-Type': 'application/json'},
        )
        payload = response.json()

        self.assertNotIn('error', payload, payload.get('error'))
        self.assertIn('Select Store', payload['result'])
