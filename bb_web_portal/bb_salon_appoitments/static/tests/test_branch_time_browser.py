"""Run: .venv/bin/python <this-file> (local Chromium/Playwright required)."""
from pathlib import Path
import re
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[4]
luxon = (root / 'odoo/addons/web/static/lib/luxon/luxon.js').read_text()
source = (Path(__file__).parents[1] / 'src/js/branch_time_views.js').read_text()
# Exercise the production coordinate adapters in real browser timezone contexts.
helpers = source[source.index('export function wallBoundary'):source.index('export class BranchCalendarModel')].replace('export ', '')
preamble = '''
const { DateTime } = luxon;
function serializeDateTime(value) { return value.setZone('UTC').toFormat('yyyy-MM-dd HH:mm:ss'); }
function deserializeDateTime(value, options={}) { return DateTime.fromSQL(value, {zone:'UTC'}).setZone(options.tz || 'default'); }
'''
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    for zone in ['Asia/Colombo', 'Australia/Sydney', 'Australia/Perth', 'UTC']:
        ctx = browser.new_context(timezone_id=zone)
        page = ctx.new_page()
        page.add_script_tag(content=luxon)
        page.add_script_tag(content=preamble + helpers)
        result = page.evaluate('''() => {
            const raw={start:'2026-09-18 10:30:00',end:'2026-09-18 11:40:00'};
            const parsed=displayRecord(raw,'start','end');
            const start=deserializeDateTime(parsed.start).toFormat('yyyy-MM-dd HH:mm');
            const end=deserializeDateTime(parsed.end).toFormat('yyyy-MM-dd HH:mm');
            const midnight=wallBoundary(luxon.DateTime.local(2026,9,18).startOf('day'));
            const next=deserializeDateTime(wallForBrowser('2026-09-19 00:30:00')).toFormat('yyyy-MM-dd HH:mm');
            return {start,end,midnight,next,unchanged:raw.start==='2026-09-18 10:30:00'};
        }''')
        assert result == dict(start='2026-09-18 10:30',end='2026-09-18 11:40',midnight='2026-09-18 00:00:00',next='2026-09-19 00:30',unchanged=True), (zone,result)
        print(zone, 'PASS', result)
        ctx.close()
    browser.close()
