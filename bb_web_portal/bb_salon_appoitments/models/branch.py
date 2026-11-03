import pytz

from odoo import models, fields, api


_TZ_SELECTION = [
    (timezone, timezone)
    for timezone in sorted(
        pytz.all_timezones,
        key=lambda timezone: timezone if not timezone.startswith('Etc/') else '_' + timezone,
    )
]


class Branch(models.Model):
    _name = 'beauty.branch'
    _description = 'Beauty Branch'
    _inherit = ['mail.thread']

    # -------------------------
    # Basic Information
    # -------------------------
    name = fields.Char('Branch Name', required=True, tracking=True)
    image = fields.Binary('Image')
    active = fields.Boolean('Active', default=True)
    is_franchise = fields.Boolean('Is Franchise', tracking=True)
    company_id = fields.Many2one('res.company', 'Company', required=True, tracking=True)

    # -------------------------
    # Branch Configurations
    # -------------------------
    pos_config_id = fields.Many2one(
        'pos.config',
        'POS Configuration',
        required=True,
        domain="[('company_id', '=', company_id)]",
    )
    website_id = fields.Many2one(
        'website',
        'Website',
        domain="[('company_id', '=', company_id)]",
        required=True,
    )
    booking_fee = fields.Float(string="Booking Fee")
    saturday_surcharge_percent = fields.Float(string="Saturday Surcharge (%)", digits=(16, 2), default=0.0)
    sunday_surcharge_percent = fields.Float(string="Sunday Surcharge (%)", digits=(16, 2), default=0.0)
    work_start_hour = fields.Float(string="Work Start Hour", default=9.0, required=True)
    work_end_hour = fields.Float(string="Work End Hour", default=18.0, required=True)
    tz = fields.Selection(
        selection=_TZ_SELECTION,
        string='Time Zone',
        required=True,
        default=lambda self: self.env.company.resource_calendar_id.tz or 'UTC',
        tracking=True,
        help='Local timezone of this branch. Appointment slots, reminders and customer messages use this timezone.',
    )
    # -------------------------
    # Address & Contact
    # -------------------------
    street = fields.Char('Street')
    street2 = fields.Char('Street 2')
    city = fields.Char('City')
    state_id = fields.Many2one('res.country.state', 'State')
    zip = fields.Char('Zip')
    country_id = fields.Many2one('res.country', 'Country')
    phone = fields.Char('Phone')
    email = fields.Char('Email')

    # -------------------------
    # Beauticians
    # -------------------------
    beautician_count = fields.Integer(
        'No of Beauticians',
        compute='_compute_beautician_count'
    )
    appointment_count = fields.Integer(
        string='Appointments',
        compute='_compute_appointment_count'
    )
    area_ids = fields.One2many(
        'beauty.location.area',
        'branch_id',
        string='Areas'
    )

    # -------------------------
    # Area Manager
    # -------------------------
    area_manager_id = fields.Many2one(
        'hr.employee',
        string='Area Manager',
        domain="[('is_beautician', '=', False)]",
        tracking=True,
        help='Non-beautician employee responsible for this branch. '
             'Auto-assigned as the Area Manager of beauticians whose Main Branch is this branch.',
    )

    # -------------------------
    # COMPUTE METHODS
    # -------------------------
    @api.depends('company_id')
    def _compute_beautician_count(self):
        for branch in self:
            branch.beautician_count = self.env['hr.employee'].search_count([
                ('is_beautician', '=', True),
                ('beautician_branch_ids', 'in', branch.id),
            ])

    def _compute_appointment_count(self):
        for branch in self:
            branch.appointment_count = self.env['salon.appointment'].search_count([
                ('branch_id', '=', branch.id),
            ])

    # -------------------------
    # ACTION METHODS
    # -------------------------
    def action_view_beauticians(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Beauticians',
            'res_model': 'hr.employee',
            'view_mode': 'list,form',
            'domain': [
                ('is_beautician', '=', True),
                ('beautician_branch_ids', 'in', self.id),
            ]
        }

    def action_view_appointments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Appointments',
            'res_model': 'salon.appointment',
            'view_mode': 'calendar,gantt,list,form',
            'domain': [
                ('branch_id', '=', self.id),
            ],
        }
