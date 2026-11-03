from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    # -------------------------
    # Beautician Fields
    # -------------------------
    # prefetch=False: these two are mirrored onto hr.employee.public for the
    # POS preload (see bb_appointment_pos.HrEmployeePublic). Left at the
    # default prefetch group, reading either one from a bare hr.employee
    # recordset pulls in every other field sharing that group -- including
    # this module's private onboarding/rate fields -- and hr.employee.fetch()
    # rejects the whole batch for a user without HR access, because those
    # fields aren't on hr.employee.public. Fetching them alone avoids that.
    is_beautician = fields.Boolean('Is Beautician', prefetch=False)

    # Legacy field - kept for DB compatibility but hidden in views
    branch_id = fields.Many2one(
        'beauty.branch',
        'Branch (Legacy)',
        domain="[('active', '=', True), ('company_id', '=', company_id)]",
        prefetch=False,
    )

    # New Many2many field for multiple branch assignment
    beautician_branch_ids = fields.Many2many(
        'beauty.branch',
        'hr_employee_beauty_branch_rel',
        'employee_id',
        'branch_id',
        string='Working Branches',
        domain="[('active', '=', True)]",
        help='Branches where this beautician works'
    )

    # The services this beautician performs. This is the beautician side of
    # the same product.beautician.line records edited from the service form,
    # so both views always show the same assignments.
    beautician_service_line_ids = fields.One2many(
        'product.beautician.line',
        'beautician_id',
        string='Services',
        help='Services this beautician is able to perform, with the price and '
             'duration that apply to them.',
    )

    def action_open_service_bulk_wizard(self):
        self.ensure_one()
        wizard = self.env['service.bulk.add.wizard'].create({
            'beautician_id': self.id,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'service.bulk.add.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }
    working_company_ids = fields.Many2many(
        'res.company',
        string='Working Companies',
        compute='_compute_working_company_ids',
        store=True,
        help='All companies where this employee can work based on main/working branches.',
    )
    all_working_branch_ids = fields.Many2many(
        'beauty.branch',
        string='All Working Branches',
        compute='_compute_all_working_branch_ids',
        store=True,
        help='Union of main branch and working branches for robust multi-branch filtering.',
    )

    # Portal hierarchy (portal-only managers)
    portal_manager_id = fields.Many2one(
        'hr.employee',
        string='Area Manager',
        domain="[('is_beautician', '=', False)]",
    )
    portal_subordinate_ids = fields.One2many('hr.employee', 'portal_manager_id', string='Portal Subordinates')
    subordinate_ids_portal = fields.Many2many(
        'hr.employee',
        compute='_compute_subordinates_portal',
        string='Portal Subordinates (All)',
        store=False,
    )
    child_all_count_portal = fields.Integer(
        compute='_compute_subordinates_portal',
        string='Portal Indirect Subordinates Count',
        store=False,
        recursive=True,
    )


    # -------------------------
    # CRUD METHODS
    # -------------------------
    @api.model_create_multi
    def create(self, vals_list):
        """Inherit the Main Branch's Area Manager for new beauticians.

        Covers programmatic/import creation where onchange does not run.
        An explicitly provided Area Manager is never overridden.
        """
        for vals in vals_list:
            if vals.get('branch_id'):
                branch = self.env['beauty.branch'].browse(vals['branch_id'])
                if vals.get('is_beautician') and branch.area_manager_id and not vals.get('portal_manager_id'):
                    vals['portal_manager_id'] = branch.area_manager_id.id
                # Auto-fill the work location from the main branch
                if not vals.get('work_location_id'):
                    location = self._get_work_location_for_branch(branch)
                    if location:
                        vals['work_location_id'] = location.id
        # Record this before super(): resource.mixin.create() pops 'tz' out of
        # vals, so afterwards there is no way to tell an explicit timezone from
        # one that was never supplied.
        tz_was_explicit = [bool(vals.get('tz')) for vals in vals_list]
        employees = super().create(vals_list)
        # Put the employee on the branch's clock. hr.employee.tz comes from the
        # resource, which defaults to the company calendar and is then
        # overwritten by core's _sync_user() with the linked user's timezone --
        # neither of which has ever looked at the branch. Left alone, core
        # attendance and time-off compute an employee's working day in a
        # timezone their branch has never been in. This runs after super()
        # precisely because _sync_user would otherwise win. An explicitly
        # supplied tz still takes priority, so imports can override.
        for employee, was_explicit in zip(employees, tz_was_explicit):
            if was_explicit:
                continue
            employee._bb_sync_tz_to_branch()
        return employees

    def write(self, vals):
        """Keep the timezone on the branch's clock when the branch changes."""
        res = super().write(vals)
        if 'branch_id' in vals and 'tz' not in vals:
            for employee in self:
                employee._bb_sync_tz_to_branch()
        return res

    def _bb_sync_tz_to_branch(self):
        """Align the employee's timezone with their main branch, if it has one."""
        self.ensure_one()
        branch_tz = self.branch_id.tz
        if branch_tz and self.tz != branch_tz:
            self.tz = branch_tz

    def _get_work_location_for_branch(self, branch):
        """Resolve the hr.work.location that matches a branch.

        Work locations are pre-loaded per branch (same name), so we match by
        name scoped to the branch's company.
        """
        if not branch:
            return self.env['hr.work.location']
        domain = [('name', '=', branch.name)]
        if branch.company_id:
            domain.append(('company_id', '=', branch.company_id.id))
        return self.env['hr.work.location'].search(domain, limit=1)

    # -------------------------
    # ONCHANGE METHODS
    # -------------------------
    @api.onchange('company_id')
    def _onchange_company_branch(self):
        """Keep branch selections intact; working branches can span companies."""
        return

    @api.onchange('branch_id')
    def _onchange_main_branch_company(self):
        """Keep employee company aligned with selected main branch.
        Also ensure the main branch is included in working branches."""
        if self.branch_id:
            if self.branch_id.company_id:
                self.company_id = self.branch_id.company_id
            if self.branch_id not in self.beautician_branch_ids:
                self.beautician_branch_ids = [(4, self.branch_id.id)]
            # Auto-select the work location matching the main branch
            location = self._get_work_location_for_branch(self.branch_id)
            if location:
                self.work_location_id = location

    @api.constrains('branch_id', 'beautician_branch_ids')
    def _check_main_branch_in_working_branches(self):
        for employee in self:
            if employee.branch_id and employee.branch_id not in employee.beautician_branch_ids:
                raise ValidationError(_(
                    "Main Branch '%s' must be included in Working Branches for employee '%s'.",
                    employee.branch_id.name,
                    employee.name,
                ))

    @api.onchange('beautician_branch_ids', 'branch_id', 'is_beautician')
    def _onchange_portal_manager_domain(self):
        domain = [('is_beautician', '=', False)]
        return {'domain': {'portal_manager_id': domain}}

    @api.onchange('branch_id', 'is_beautician')
    def _onchange_branch_area_manager(self):
        """Auto-assign the beautician's Area Manager from the Main Branch.

        When a beautician's Main Branch is selected, inherit that branch's
        Area Manager. Only fills when the branch defines one, so a manual
        selection is preserved if the branch has no area manager.
        """
        if self.is_beautician and self.branch_id.area_manager_id:
            self.portal_manager_id = self.branch_id.area_manager_id

    @api.onchange('portal_manager_id')
    def _onchange_portal_manager_keep_parent(self):
        """Keep parent_id independent from portal_manager_id selection."""
        if self._origin and self.parent_id != self._origin.parent_id:
            self.parent_id = self._origin.parent_id

    @api.depends('company_id', 'branch_id.company_id', 'beautician_branch_ids.company_id')
    def _compute_working_company_ids(self):
        for employee in self:
            company_ids = set()
            if employee.company_id:
                company_ids.add(employee.company_id.id)
            if employee.branch_id and employee.branch_id.company_id:
                company_ids.add(employee.branch_id.company_id.id)
            company_ids.update(employee.beautician_branch_ids.mapped('company_id').ids)
            employee.working_company_ids = [(6, 0, list(company_ids))]

    @api.depends('branch_id', 'beautician_branch_ids')
    def _compute_all_working_branch_ids(self):
        for employee in self:
            branch_ids = set(employee.beautician_branch_ids.ids)
            if employee.branch_id:
                branch_ids.add(employee.branch_id.id)
            employee.all_working_branch_ids = [(6, 0, list(branch_ids))]

    def _get_working_branch_ids(self):
        self.ensure_one()
        branch_ids = set(self.beautician_branch_ids.ids)
        if self.branch_id:
            branch_ids.add(self.branch_id.id)
        return branch_ids

    def _can_work_in_branch(self, branch):
        self.ensure_one()
        if not branch:
            return False
        return branch.id in self._get_working_branch_ids()

    def _get_online_booking_availability(
        self, branch, appointment_date, start_hour=None, duration=0.0
    ):
        """Extension point for optional scheduling modules.

        The salon domain owns branch eligibility. Modules that own a roster
        source may narrow online availability without the website importing
        their private models.
        """
        self.ensure_one()
        return {'available': True, 'reason': False}

    def _get_subordinates_portal(self, parents=None):
        if not parents:
            parents = self.env[self._name]
        indirect_subordinates = self.env[self._name]
        parents |= self
        direct_subordinates = self.portal_subordinate_ids - parents
        child_subordinates = direct_subordinates._get_subordinates_portal(parents=parents) if direct_subordinates else self.browse()
        indirect_subordinates |= child_subordinates
        return indirect_subordinates | direct_subordinates

    @api.depends('portal_subordinate_ids', 'portal_subordinate_ids.child_all_count_portal')
    def _compute_subordinates_portal(self):
        for employee in self:
            employee.subordinate_ids_portal = employee._get_subordinates_portal()
            employee.child_all_count_portal = len(employee.subordinate_ids_portal)
