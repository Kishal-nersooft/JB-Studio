# bnb_portal_appointment — Code Quality Report

**What it does:** Online customer appointment booking on the website: branches, beauticians, multi-step booking, promo codes, Stripe/NAB payment, social auth.

**Odoo 19 standard compliance:** 75% (was 45% in `addon_bnb_live`)

Defines no new models, so no ACLs are required; security posture is entirely in the controllers.

## Changes applied in this tree
- controllers/main.py (2,250 lines, 7 classes) split into per-class files (portal_main, branch, beautician, booking, related_products, promo_code, payment) plus booking_helpers.py; main.py kept as a compat shim.
- Version bumped to 19.0.2.0.0.
- Runtime-verified: /book-online renders on a fresh database.
- Unused header imports pruned; compat shim now declares __all__.

## Remaining roadmap to 100%
- 19 public routes combined with 103 sudo() calls is the riskiest surface in the suite — audit each public route for what it exposes as superuser.
- sessionStorage-based booking state and base.js (2,362 lines) need JS decomposition.
- No tests.

## Verification round 2 (2026-07-02)
- Fresh database `bb_standard` created; **all 25 modules installed from scratch with zero errors** (fresh install exercises every view/data/security file — this is how the missing crm dependency was caught).
- Live server test: /dashboard, /dashboard/schedule, /dashboard/people, /dashboard/timesheets, /schedule/weekly, /dashboard/manager, /jobs, /book-online all return HTTP 200 with full content; JSON feeds (insights_data, me/live_summary, pos-api/initial-data) return real data.

---
*Verified: every .py compiles, every .xml parses, and the full Odoo 19 registry loads this tree against a production database copy (bb_june) with route registration identical to the original.*
