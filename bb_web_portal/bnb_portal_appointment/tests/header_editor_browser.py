"""Header layout regression fixture using the addon's actual stylesheet.

Run with Python providing libsass and Playwright (Chromium and WebKit).
This does not require a database or exercise the live website builder.
"""
import argparse
import json
from pathlib import Path

import sass
from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
addon = Path(__file__).resolve().parents[1]
# Bootstrap display utilities used by Odoo's desktop/mobile header templates.
utilities = '.d-block{display:block!important}.d-none{display:none!important}@media(min-width:992px){.d-lg-block{display:block!important}.d-lg-none{display:none!important}}'
css = utilities + sass.compile(filename=str(addon / 'static/src/scss/homepage_snippets.scss'))
markup = '<div id="wrapwrap"><header><nav id="desktop" class="d-none d-lg-block"><a href="/">Home</a><a href="/shop">Shop</a></nav><nav id="mobile" class="o_header_mobile d-block d-lg-none"><button aria-label="Toggle navigation">☰</button></nav></header><footer></footer></div>'
results = []
with sync_playwright() as ctx:
    for engine in ('chromium', 'webkit'):
        browser = getattr(ctx, engine).launch(headless=True)
        for footer in (False, True):
            for width in (1440, 1200, 1199, 1098, 992, 991, 390):
                page = browser.new_page(viewport={'width': width, 'height': 800})
                page.set_content('<style>' + css + '</style>' + markup)
                if footer:
                    page.locator('footer').evaluate("el => el.classList.add('bb_footer')")
                # Enter and leave edit mode in the same document to catch leaks.
                for editing in (False, True, False):
                    page.locator('body').evaluate('(el, edit) => el.classList.toggle("editor_enable", edit)', editing)
                    breakpoint = 992 if editing or not footer else 1200
                    desktop = page.locator('#desktop').is_visible()
                    mobile = page.locator('#mobile').is_visible()
                    assert (desktop, mobile) == (width >= breakpoint, width < breakpoint), (engine, width, footer, editing)
                    if desktop:
                        assert page.get_by_role('link', name='Home').is_visible()
                    else:
                        assert page.get_by_role('button', name='Toggle navigation').is_visible()
                    results.append(dict(browser=engine, width=width, bnb_footer=footer, editing=editing, desktop_visible=desktop, mobile_visible=mobile))
                page.close()
        browser.close()
args.out.mkdir(parents=True, exist_ok=True)
(args.out / 'header_results.json').write_text(json.dumps(results, indent=2))
print(f'{len(results)} header layout checks passed; live builder interaction not tested.')
