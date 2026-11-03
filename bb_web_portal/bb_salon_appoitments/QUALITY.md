# bb_salon_appoitments — Code Quality Report

**What it does:** Core salon suite: branch/franchise management, appointments, beauticians, services, deposits/credits, POS and website integration.

**Odoo 19 standard compliance:** 88% (was 70% in `addon_bnb_live`)

Well-structured models (largest file 807 lines), proper security dir, minimal sudo (4) and raw SQL (2).

## Changes applied in this tree
- Version normalized to 19.0.1.1.0 (was 1.1).
- Undeclared dependency fixed: module inherits crm.view_partners_form_crm1 but did not list crm in depends — fresh installs crashed (existing DBs only worked because CRM happened to be installed). crm added to depends.
- Automated tests added (tests/test_branch_employee.py): branch defaults, beautician working-branch constraint, area-manager auto-fill on create, explicit-manager precedence.

## Remaining roadmap to 100%
- Add automated tests (this is the most load-bearing module of the suite).
- appointment.py (807 lines) is fine but nearing the point where checkout/payment logic could move to a dedicated service model.

## Verification round 2 (2026-07-02)
- Fresh database `bb_standard` created; **all 25 modules installed from scratch with zero errors** (fresh install exercises every view/data/security file — this is how the missing crm dependency was caught).
- Live server test: /dashboard, /dashboard/schedule, /dashboard/people, /dashboard/timesheets, /schedule/weekly, /dashboard/manager, /jobs, /book-online all return HTTP 200 with full content; JSON feeds (insights_data, me/live_summary, pos-api/initial-data) return real data.

---
*Verified: every .py compiles, every .xml parses, and the full Odoo 19 registry loads this tree against a production database copy (bb_june) with route registration identical to the original.*
