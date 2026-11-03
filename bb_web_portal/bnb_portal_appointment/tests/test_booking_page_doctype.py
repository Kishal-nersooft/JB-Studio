import re

from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestBookingPageDoctype(HttpCase):
    """A tag ahead of the doctype puts the page in quirks mode, where
    document.scrollingElement is null and the website header throws
    "Cannot read properties of null (reading 'scrollTop')" on load."""

    def test_booking_page_starts_with_the_doctype(self):
        html = self.url_open('/book-online').text
        self.assertRegex(html, r'(?i)^\s*<!doctype html>')

    def test_font_awesome_link_is_inside_the_head(self):
        html = self.url_open('/book-online').text
        head = re.search(r'(?is)<head>(.*?)</head>', html)
        self.assertTrue(head, 'the page must have a <head>')
        self.assertIn('font-awesome/6.4.0', head.group(1))
