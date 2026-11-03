from odoo import api, models


class Website(models.Model):
    _inherit = 'website'

    def _control_third_party_trackers_in_html(self, html_content):
        """Keep website templates compatible across Odoo 19 build levels."""
        parent_method = getattr(
            super(), '_control_third_party_trackers_in_html', None
        )
        if parent_method:
            return parent_method(html_content)
        return html_content


class IrUiView(models.Model):
    _inherit = 'ir.ui.view'

    @api.readonly
    @api.model
    def render_public_asset(self, template, values=None):
        """Supply homepage-only data when the website editor renders snippets."""
        render_values = dict(values or {})
        render_values.setdefault('homepage_data', {})
        return super().render_public_asset(template, values=render_values)
