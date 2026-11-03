"""One place to get a beauty.branch in a test.

Seven test classes across three modules used to open with

    branch = env['beauty.branch'].search([('company_id', '=', ...)], limit=1)
    if not branch:
        raise SkipTest('A branch is required for ...')

and one of them explained why: "beauty.branch has a long required-field chain
(pos_config_id, website_id ...) -- reuse an existing branch rather than fight
that fixture."

The chain is four fields. The cost of not fighting it was that all seven
classes skipped on any database without a branch already in it -- which is
every clean one, including CI. They had never run. Two of them are security
tests.

So this builds the branch instead. Everything it needs is created here, and
existing records are reused when they are already present, so a test that runs
against a production copy behaves as it did before.
"""


def ensure_branch(env, name="Test Branch", company=None, tz="Australia/Adelaide"):
    """Return a beauty.branch for this company, creating one if there is none.

    An existing branch is preferred so tests that were written against seeded
    data keep the record they were written against.
    """
    company = company or env.company
    branch = env["beauty.branch"].search(
        [("company_id", "=", company.id)], limit=1)
    if branch:
        return branch
    return env["beauty.branch"].create({
        "name": name,
        "company_id": company.id,
        "pos_config_id": ensure_pos_config(env, company=company).id,
        "website_id": ensure_website(env, company=company).id,
        "tz": tz,
    })


def ensure_pos_config(env, name="Test POS", company=None):
    """A pos.config for this company, created without payment methods.

    The default payment methods pull in a journal, which needs a chart of
    accounts, so a company without one cannot create the config at all. A
    config that has to run a real session needs them, and gets its own -- see
    ensure_pos_session.
    """
    company = company or env.company
    config = env["pos.config"].search(
        [("company_id", "=", company.id)], limit=1)
    if config:
        return config
    return env["pos.config"].with_company(company).create({
        "name": name,
        "company_id": company.id,
        "payment_method_ids": [(6, 0, [])],
    })


def ensure_website(env, name="Test Website", company=None):
    """A website for this company, falling back to any website.

    beauty.branch.website_id is domained on the branch's company, but websites
    are often company-less in practice, so an existing one is taken first.
    """
    company = company or env.company
    website = env["website"].search(
        [("company_id", "=", company.id)], limit=1) or env["website"].search([], limit=1)
    if website:
        return website
    return env["website"].create({"name": name, "company_id": company.id})


def ensure_second_company(env, name="Second Test Company", users=None):
    """A company other than the current one, for cross-company assertions.

    Tests that check isolation used to search for a second company and skip
    when the database had only one -- which is every fresh install, so the
    isolation was asserted nowhere.

    ``users`` are given membership of it, defaulting to the environment's own
    user. Odoo refuses an allowed_company_ids context naming a company the
    user does not belong to, so without membership an isolation test gets an
    access error rather than an empty result -- and would then be asserting
    the wrong thing entirely. Pass the user the test actually logs in as: in
    an HttpCase, env.user is the superuser while authenticate('admin', ...)
    runs as base.user_admin, which is a different record.

    On a database that already has a second company the user is usually a
    member already, which is why this only surfaces on a fresh one.
    """
    other = env["res.company"].search([("id", "!=", env.company.id)], limit=1)
    if not other:
        other = env["res.company"].create({"name": name})
    for user in (users if users is not None else env.user):
        if other not in user.company_ids:
            user.sudo().write({"company_ids": [(4, other.id)]})
    return other


def ensure_beautician(env, branch, name="Test Beautician"):
    """A beautician attached to this branch."""
    employee = env["hr.employee"].search([
        ("is_beautician", "=", True),
        ("company_id", "=", branch.company_id.id),
    ], limit=1)
    return employee or env["hr.employee"].create({
        "name": name,
        "company_id": branch.company_id.id,
        "is_beautician": True,
        "branch_id": branch.id,
        "beautician_branch_ids": [(6, 0, branch.ids)],
    })


def ensure_service_product(env, name="Test Service", branch=None):
    """A sellable service product, published to the POS when a branch is given.

    The search matches what is being asked for. Looking only for sale_ok and
    returning the first hit meant a caller that wanted a POS-published
    appointment service was handed any sellable product at all, and then found
    it missing from the POS payload.
    """
    domain = [("sale_ok", "=", True)]
    if branch is not None:
        domain += [
            ("available_in_pos", "=", True),
            ("product_tmpl_id.is_appointment_service", "=", True),
            ("product_tmpl_id.branch_ids", "in", branch.ids),
        ]
    product = env["product.product"].search(domain, limit=1)
    if product:
        return product
    values = {"name": name, "type": "service", "sale_ok": True}
    if branch is not None:
        values.update({
            "available_in_pos": True,
            "is_appointment_service": True,
            "branch_ids": [(6, 0, branch.ids)],
        })
    return env["product.product"].create(values)


def ensure_published_roster_slot(env, branch=None, employee=None):
    """A published planning slot linked to a roster.

    The timesheet sync tests searched for one and skipped when the database
    had none, which is every fresh install. Built here so they run anywhere.
    Requires bb_portal_employee_management, which owns branch.roster.
    """
    from odoo import fields
    slot = env["planning.slot"].search([
        ("state", "=", "published"),
        ("planning_type", "in", ("shift", "open", "open_approval")),
        ("employee_id", "!=", False),
        ("roster_id", "!=", False),
        ("company_id", "=", env.company.id),
    ], limit=1)
    if slot:
        return slot

    branch = branch or ensure_branch(env, name="Roster Slot Branch")
    employee = employee or ensure_beautician(env, branch, name="Roster Slot Beautician")
    day = fields.Date.context_today(env.user)
    roster = env["branch.roster"].create({
        "name": "Roster Slot Fixture",
        "branch_id": branch.id,
        "start_date": day,
        "end_date": day,
        "start_time": "09:00",
        "end_time": "17:00",
        "shift_type": "assigned",
        "assigned_employee_id": employee.id,
    })
    return env["planning.slot"].create({
        "name": "Roster Slot Fixture",
        "employee_id": employee.id,
        "resource_id": employee.resource_id.id,
        "start_datetime": "%s 09:00:00" % day,
        "end_datetime": "%s 17:00:00" % day,
        "state": "published",
        "planning_type": "shift",
        "roster_id": roster.id,
        "company_id": branch.company_id.id,
    })


def has_accounting(env, company=None):
    """Whether this company has a chart of accounts loaded.

    A POS session posts to a journal, so without one it cannot be opened at
    all. Every real salon database has accounting configured -- point_of_sale
    depends on account -- but a bare test install may not, and the tests that
    need a session should say so rather than fail obscurely.
    """
    company = company or env.company
    return bool(company.chart_template)


def ensure_pos_session(env, branch=None, state="opened", company=None):
    """An open or closed pos.session, built rather than searched for.

    Eleven tests used to search for a session and skip when the database had
    none. On a fresh install there is never one, so none of them ran.

    Returns an empty recordset when the company has no chart of accounts,
    because a session cannot exist without a journal; callers should skip on
    that, which is then an honest statement about the environment rather than
    about the data.
    """
    company = company or env.company
    session = env["pos.session"].search([
        ("state", "=", state), ("company_id", "=", company.id),
    ], limit=1)
    if session:
        return session
    if not has_accounting(env, company):
        return env["pos.session"].browse()

    if branch is None:
        branch = ensure_branch(env, company=company)
    config = branch.pos_config_id
    if not config.payment_method_ids:
        # The branch fixture builds its config with no payment methods so it
        # works without accounting. A session needs at least one, and
        # pos.config.create fills in Cash/Card/Customer Account by itself --
        # so this creates one directly rather than going through
        # ensure_pos_config, which would hand back the empty config it finds.
        config = env["pos.config"].with_company(company).create({
            "name": "Session POS", "company_id": company.id,
        })

    session = env["pos.session"].create({
        "config_id": config.id, "user_id": env.uid,
    })
    # A new session lands in opening_control, not opened: the cash count is a
    # deliberate gate. set_opening_control is what the wizard calls.
    session.set_opening_control(0, "")
    if state == "closed":
        session.action_pos_session_closing_control()
    return session


def ensure_deposit_product(env, name="Test Deposit"):
    """The product a customer deposit is taken on."""
    product = env["product.product"].search(
        [("product_tmpl_id.is_deposit_product", "=", True)], limit=1)
    return product or env["product.product"].create({
        "name": name,
        "type": "service",
        "sale_ok": True,
        "available_in_pos": True,
        "is_deposit_product": True,
    })


def ensure_cash_payment_method(env, company=None):
    """The cash method a POS payment is recorded against."""
    company = company or env.company
    return env["pos.payment.method"].search([
        ("company_id", "=", company.id),
        ("is_cash_count", "=", True),
    ], limit=1) or env["pos.payment.method"].search([
        ("company_id", "=", company.id),
    ], limit=1)
