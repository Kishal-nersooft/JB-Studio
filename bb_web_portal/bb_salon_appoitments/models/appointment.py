import logging

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from markupsafe import Markup, escape
from datetime import datetime, timedelta, time
import pytz
from odoo.tools.misc import format_amount

_logger = logging.getLogger(__name__)


class SalonAppointment(models.Model):
    _name = 'salon.appointment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Salon Appointment'
    _order = 'appointment_date desc'
    _rec_name = 'display_name'

    # The expiry cron runs every five minutes and only ever looks for draft
    # appointments that have an expiry set. A partial index keeps that lookup
    # off a full table scan as appointment history grows, and stays small
    # because it excludes every appointment the cron can never match.
    # Declared rather than created in init() so it survives upgrades.
    _auto_expire_due_idx = models.Index(
        "(auto_expire_datetime) WHERE auto_expire IS TRUE "
        "AND auto_expire_datetime IS NOT NULL AND state = 'draft'"
    )

    @api.model
    def _booking_channel(self, vals):
        """Which channel a new booking came through.

        The markers that tell online and call-centre bookings apart live in
        `bnb_portal_appointment` and `bb_webex_callcenter`, which depend on
        this module rather than the other way round. Each overrides this hook
        for its own channel, the same way the consultation-form SMS hook works
        below, so this module needs no knowledge of either.

        Anything not claimed by one of those is taken at the till or in the
        back office, which is what Instore means.
        """
        return 'instore'

    @api.model
    def _backfill_appointment_type(self):
        """Record the booking channel on appointments made before it was kept.

        Every appointment created before this existed sits on the plain
        Appointment type, so the reports cannot tell an online booking from
        one taken at the till. The channel is worked out from the markers the
        booking already carries, which is the same rule new appointments use.

        Declared as a function rather than a post-install hook so it runs on
        module update too, which is how it reaches appointments already in the
        system. Leave and Break are never touched, nor is any appointment that
        already carries a channel, so repeating it changes nothing.

        The online and call-centre markers belong to modules that may not be
        installed, so each column is checked before it is used. So does the
        planning slot that identifies a leave or break: it lives on another
        table entirely, and leaving it unchecked meant a fresh install of this
        module died on "column blocking.break_appointment_id does not exist"
        before any of its data loaded. Nobody had hit it because every
        database in use was upgraded from one that already had the column.
        """
        def has_column(table, name):
            self.env.cr.execute("""
                SELECT 1 FROM information_schema.columns
                 WHERE table_name = %s AND column_name = %s
            """, (table, name))
            return bool(self.env.cr.fetchone())

        # Leave and break slots created before this field existed are also
        # sitting on the plain type, and they are not customer bookings, so
        # they must not be swept into Instore. A planning slot pointing back
        # at the appointment is what identifies them - the same test the
        # dashboards already use. Whether each one is leave or break cannot be
        # told from the data, because they predate the link to the time-off
        # record that carries the category, so they are left as they are
        # rather than guessed at.
        # Without the module that owns break_appointment_id there are no
        # blocking slots to exclude, so the clause is simply left out.
        not_a_leave_or_break = ""
        if has_column('planning_slot', 'break_appointment_id'):
            not_a_leave_or_break = """
              AND NOT EXISTS (
                  SELECT 1 FROM planning_slot blocking
                   WHERE blocking.break_appointment_id = salon_appointment.id
              )
            """

        filled = {}
        # Most specific first: a booking taken on a call is a call centre
        # booking even if it was also flagged as online.
        if has_column('salon_appointment', 'source_webex_call_id'):
            self.env.cr.execute(f"""
                UPDATE salon_appointment SET appointment_type = 'callcenter'
                 WHERE appointment_type = 'normal'
                   AND source_webex_call_id IS NOT NULL
                   {not_a_leave_or_break}
            """)
            filled['callcenter'] = self.env.cr.rowcount
        if has_column('salon_appointment', 'booked_online'):
            self.env.cr.execute(f"""
                UPDATE salon_appointment SET appointment_type = 'online'
                 WHERE appointment_type = 'normal'
                   AND booked_online IS TRUE
                   {not_a_leave_or_break}
            """)
            filled['online'] = self.env.cr.rowcount
        # Whatever is left was taken at the till or in the back office.
        self.env.cr.execute(f"""
            UPDATE salon_appointment SET appointment_type = 'instore'
             WHERE appointment_type = 'normal'
               {not_a_leave_or_break}
        """)
        filled['instore'] = self.env.cr.rowcount

        if any(filled.values()):
            _logger.info(
                "Appointment type backfilled: %s",
                ", ".join(f"{count} {kind}" for kind, count in filled.items() if count),
            )
        return filled

    def _send_consultation_form_link_sms(self, survey_url):
        """Optional integration hook for sending an existing form link by SMS.

        The base appointment and consultation-email flows must keep working when
        no SMS provider module is installed.  SMS integrations can override this
        hook without making the appointment modules depend on a provider.
        """
        self.ensure_one()
        return False

    # -------------------------
    # Basic Information
    # -------------------------
    appointment_ref = fields.Char(
        string='Appointment Reference',
        default='New',
        copy=False,
        readonly=True,
        tracking=True
    )
    # The reference above is the calendar's own running number, and every
    # record on the calendar takes one -- leave and break slots included, so
    # that each has an identity there. That makes it the wrong number to trace
    # trade by: the run is broken up by records that never served a customer.
    # This second number is drawn per company and only by real bookings,
    # whichever channel they came through, so a company's appointments can be
    # searched and followed on their own without disturbing the calendar run.
    appointment_no = fields.Char(
        string='Appointment No.',
        copy=False,
        readonly=True,
        index=True,
        tracking=True,
        help='Running number for real appointments within the company, apart '
             'from the calendar reference that leave and break slots also '
             'carry. Empty on leave and break.',
    )
    display_name = fields.Char(string='Appointment', compute='_compute_display_name', store=True)

    # -------------------------
    # Appointment kind
    # -------------------------
    # Leave and break slots are booked as ordinary appointments so the calendar
    # shows the beautician as occupied. Until now nothing on the appointment
    # said so: consumers had to look for a planning.slot pointing back at it,
    # which is why that EXISTS sub-query is repeated across the dashboards.
    # This field states it directly. Existing behaviour is unchanged -- those
    # sub-queries still work, and normal appointments keep the default.
    appointment_type = fields.Selection(
        [
            ('normal', 'Appointment'),
            ('online', 'Online Appointment'),
            ('instore', 'Instore Appointment'),
            ('callcenter', 'Call center Appointment'),
            ('leave', 'Leave'),
            ('break', 'Break'),
        ],
        string='Appointment Type',
        default='normal',
        required=True,
        index=True,
        readonly=True,
        copy=False,
        tracking=True,
        help='Where the booking came from: made on the website, taken at the '
             'till, or raised from a call centre call.\n\n'
             'Leave and Break block calendar time for an employee rather than '
             'serving a customer.\n\n'
             'Appointment is the plain type kept for bookings made before the '
             'source was recorded.',
    )

    #: Types that represent a customer booking, whatever channel it came from.
    #: Leave and Break are the two that do not.
    BOOKING_APPOINTMENT_TYPES = ('normal', 'online', 'instore', 'callcenter')
    # The links to the source leave/break records live in
    # bb_portal_employee_management, which owns employee.timeoff.break and
    # depends on planning. This module cannot reference either without
    # inverting the dependency between the two addons.
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        readonly=True,
        copy=False,
        index=True,
        help='The employee this leave or break belongs to. Empty on normal '
             'appointments, which have a customer instead.',
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('in_progress', 'Arrived'),
        ('completed', 'Completed'),
        ('refunded', 'Refunded'),
        ('cancelled', 'Cancelled')
    ], default='draft', string='Status', tracking=True)

    # A draft appointment is a tentative hold. These let it release itself if
    # the customer never confirms, instead of blocking the slot indefinitely.
    auto_expire = fields.Boolean(
        string='Auto-expire at set time',
        default=False,
        tracking=True,
        help='Cancel this appointment automatically if it is still in Draft '
             'when the expiry time passes.',
    )
    auto_expire_datetime = fields.Datetime(
        string='Expires At',
        tracking=True,
        help='When the appointment expires if it has not been confirmed. '
             'Only applies while the appointment is still in Draft.',
    )

    # A promo code chosen when the appointment is booked, applied when the
    # customer checks out. Separate from the website's online-deposit code so
    # a code entered at the counter is not stored under an online-only name.
    promo_code = fields.Char(
        string='Promo Code',
        tracking=True,
        help='Discount code to apply when this appointment is paid at the '
             'point of sale.',
    )

    # -------------------------
    # Customer Information
    # -------------------------
    customer_id = fields.Many2one('res.partner', string='Customer', tracking=True)
    customer_first_name = fields.Char(string='First Name', tracking=True)
    customer_last_name = fields.Char(string='Last Name', tracking=True)
    customer_email = fields.Char(string='Email', tracking=True)
    customer_phone = fields.Char(string='Mobile Phone', tracking=True)
    customer_other_phone = fields.Char(string='Other Phone', tracking=True)
    customer_pronouns = fields.Selection([
        ('she/her', 'She/Her'),
        ('he/him', 'He/Him'),
        ('they/them', 'They/Them'),
        ('prefer_not_to_say', 'Prefer not to say')
    ], string='Pronouns', tracking=True)
    customer_is_vip = fields.Boolean(
        string='Is VIP Customer',
        related='customer_id.is_vip',
        store=True,
        readonly=True
    )

    # -------------------------
    # Location Information
    # -------------------------
    branch_id = fields.Many2one(
        'beauty.branch',
        string='Salon Branch',
        required=True,
        domain="[('company_id', '=', company_id)]",
        tracking=True
    )

    # -------------------------
    # Appointment Details
    # -------------------------
    appointment_date = fields.Date(string='Appointment Date', required=True, tracking=True)

    appointment_start_datetime = fields.Datetime(
        string='Start Date & Time',
        compute='_compute_appointment_datetimes_from_hours',
        store=True,
        tracking=True
    )
    appointment_end_datetime = fields.Datetime(
        string='End Date & Time',
        compute='_compute_appointment_datetimes_from_hours',
        store=True,
        tracking=True
    )
    # Odoo renders every Datetime on the viewer's own clock, so a Colombo-based
    # user opening a Canberra booking sees it 4.5 hours out, and a UTC user can
    # even see the wrong date. The stored values are correct; only the rendering
    # follows the reader. This restates them on the branch's clock so the form
    # agrees with the SMS the customer received.
    branch_local_time_display = fields.Char(
        string='Branch Local Time',
        compute='_compute_branch_local_time_display',
        help='Start and end on the branch\'s own clock, whatever timezone you '
             'are working in.',
    )
    # The same two instants shown separately, so the form can present start and
    # end on the branch clock in place of the raw Datetime fields. Those are
    # computed with no inverse, so nothing is lost by displaying them this way.
    branch_local_start_display = fields.Char(
        string='Start Date & Time',
        compute='_compute_branch_local_time_display',
    )
    branch_local_end_display = fields.Char(
        string='End Date & Time',
        compute='_compute_branch_local_time_display',
    )

    # Display coordinates only: branch wall-clock dates for the dedicated views.
    # Never use these fields for booking, billing, reminders or real UTC instants.
    branch_calendar_start = fields.Datetime(compute='_compute_branch_calendar_window', store=True, index=True)
    branch_calendar_end = fields.Datetime(compute='_compute_branch_calendar_window', store=True, index=True)
    branch_display_timezone = fields.Selection(related='branch_id.tz', readonly=True)

    @api.depends('appointment_start_datetime', 'appointment_end_datetime', 'branch_id.tz', 'state')
    def _compute_branch_calendar_window(self):
        for record in self:
            start, end = record._get_display_window_utc()
            zone = pytz.timezone(record.branch_id.tz or 'UTC')
            record.branch_calendar_start = pytz.UTC.localize(start).astimezone(zone).replace(tzinfo=None) if start else False
            record.branch_calendar_end = pytz.UTC.localize(end).astimezone(zone).replace(tzinfo=None) if end else False

    def _get_display_window_utc(self):
        """Return the (start, end) instants the form should show.

        Overridden in bb_appointment_pos to prefer the booked window, which
        survives completion. Here there is nothing else to fall back on.
        """
        self.ensure_one()
        return self.appointment_start_datetime, self.appointment_end_datetime

    @api.depends('appointment_start_datetime', 'appointment_end_datetime', 'branch_id.tz', 'state')
    def _compute_branch_local_time_display(self):
        for record in self:
            start, end = record._get_display_window_utc()
            if not start:
                record.branch_local_time_display = ''
                record.branch_local_start_display = ''
                record.branch_local_end_display = ''
                continue
            tz_name = record.branch_id.tz or 'UTC'
            branch_tz = pytz.timezone(tz_name)
            start_local = pytz.UTC.localize(start).astimezone(branch_tz)
            record.branch_local_start_display = start_local.strftime('%d %b %Y, %I:%M %p')
            text = start_local.strftime('%d %b %Y, %I:%M %p')
            record.branch_local_end_display = ''
            if end:
                end_local = pytz.UTC.localize(end).astimezone(branch_tz)
                record.branch_local_end_display = end_local.strftime('%d %b %Y, %I:%M %p')
                # Only repeat the date when the appointment crosses midnight on
                # the branch's clock.
                if end_local.date() == start_local.date():
                    text += ' - %s' % end_local.strftime('%I:%M %p')
                else:
                    text += ' - %s' % end_local.strftime('%d %b %Y, %I:%M %p')
            record.branch_local_time_display = '%s (%s)' % (text, tz_name)

    # Why an appointment was cancelled. Chosen from a configurable list so the
    # reasons can be reported on, with a free-text note for anything the list
    # does not cover.
    cancellation_reason_id = fields.Many2one(
        'salon.cancellation.reason',
        string='Cancellation Reason',
        tracking=True,
        ondelete='restrict',
        copy=False,
    )
    cancellation_note = fields.Char(
        string='Cancellation Note',
        tracking=True,
        copy=False,
    )

    notes = fields.Text(string='Notes', tracking=True)
    special_note = fields.Text(string='Special Note', tracking=True)
    duplicate_parent_id = fields.Many2one(
        'salon.appointment',
        string='Duplicate Parent Appointment',
        ondelete='cascade',
        tracking=True
    )
    duplicate_child_ids = fields.One2many(
        'salon.appointment',
        'duplicate_parent_id',
        string='Duplicate Appointments',
        tracking=True
    )
    duplicate_appointment_count = fields.Integer(
        string='Duplicate Appointments',
        compute='_compute_duplicate_appointment_count'
    )

    # -------------------------
    # Services
    # -------------------------
    service_line_ids = fields.One2many(
        'salon.appointment.service',
        'appointment_id',
        string='Services',
        tracking=True
    )
    consumption_line_ids = fields.One2many(
        'salon.appointment.consumption',
        'appointment_id',
        string='Consumptions',
        tracking=True
    )
    beautician_ids = fields.Many2many(
        'hr.employee',
        string='Beauticians',
        compute='_compute_beautician_ids',
        store=True,
        tracking=True
    )
    has_party_details = fields.Boolean(
        string='Has Party Details',
        compute='_compute_party_details',
        store=True
    )
    party_prep_minutes_total = fields.Integer(
        string='Party Prep (min)',
        compute='_compute_party_details',
        store=True
    )
    party_wrap_minutes_total = fields.Integer(
        string='Party Wrap (min)',
        compute='_compute_party_details',
        store=True
    )

    # -------------------------
    # Totals & Payments
    # -------------------------
    booking_fee = fields.Monetary(string='Booking Fee', compute='_compute_booking_fee', store=True, tracking=True)
    services_subtotal = fields.Monetary(string='Services Subtotal', compute='_compute_totals', store=True, tracking=True)
    surcharge_percent = fields.Float(
        string='Surcharge (%)',
        compute='_compute_totals',
        store=True,
        digits=(16, 2),
        tracking=True
    )
    surcharge_amount = fields.Monetary(string='Surcharge Amount', compute='_compute_totals', store=True, tracking=True)
    services_total = fields.Monetary(string='Services Total', compute='_compute_totals', store=True, tracking=True)
    total_amount = fields.Monetary(string='Total Amount', compute='_compute_totals', store=True, tracking=True)

    payment_status = fields.Selection([
        ('unpaid', 'Unpaid'),
        ('partial', 'Partial'),
        ('paid', 'Paid'),
        ('refunded', 'Refunded')
    ], default='unpaid', string='Payment Status', tracking=True)

    is_online_booking = fields.Boolean(
        compute='_compute_online_payment_summary', store=True,
        string='Online Booking')
    online_payment_receipt_status = fields.Selection([
        ('not_received', 'Not Received'),
        ('half_received', 'Half Payment Received'),
        ('full_received', 'Full Payment Received'),
        ('refunded', 'Refunded'),
    ], compute='_compute_online_payment_summary', store=True,
       string='Online Payment Received')
    online_refunded_amount = fields.Monetary(
        compute='_compute_online_payment_summary', store=True,
        string='Online Refunded')

    payment_line_ids = fields.One2many(
        'salon.appointment.payment',
        'appointment_id',
        string='Payment Details',
        tracking=True
    )

    # -------------------------
    # Policy & Customer Preferences
    # -------------------------
    policy_agreed = fields.Boolean(string='Policy Agreed', default=False, tracking=True)
    remember_customer = fields.Boolean(string='Remember Customer', default=False, tracking=True)

    # -------------------------
    # Company & Currency
    # -------------------------
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
        tracking=True
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        tracking=True
    )

    # -------------------------
    # POS Integration
    # -------------------------
    session_id = fields.Many2one(
        'pos.session',
        string='POS Session',
        help='POS Session where this appointment was created/managed',
        tracking=True
    )
    pos_order_id = fields.Many2one(
        'pos.order',
        string='POS Order',
        help='Associated POS Order for payment',
        tracking=True
    )
    pos_order_paid = fields.Boolean(
        string='POS Order Paid',
        default=False,
        help='Whether the associated POS order has been paid',
        tracking=True
    )
    pos_order_count = fields.Integer(string='POS Orders', compute='_compute_pos_order_count')

    # -------------------------
    # Booking Questions & Answers
    # -------------------------
    question_answer_ids = fields.One2many(
        'salon.appointment.question.answer',
        'appointment_id',
        string='Booking Q&A'
    )

    # -------------------------
    # Waiting List
    # -------------------------
    is_waiting_list = fields.Boolean(
        string='Waiting List',
        default=False,
        help='If True, this appointment is on the waiting list (no beautician/time assigned yet)',
        tracking=True
    )

    # -------------------------
    # COMPUTE METHODS
    # -------------------------
    @api.depends(
        'appointment_date',
        'branch_id.tz',
        'service_line_ids.start_hour',
        'service_line_ids.end_hour',
    )
    def _compute_appointment_datetimes_from_hours(self):
        """Compute start and end datetime of the appointment based on service hours and branch timezone."""
        for record in self:
            if not record.appointment_date or not record.service_line_ids:
                record.appointment_start_datetime = False
                record.appointment_end_datetime = False
                continue
            start_hours = record.service_line_ids.mapped('start_hour')
            end_hours = record.service_line_ids.mapped('end_hour')

            if not start_hours or not end_hours:
                record.appointment_start_datetime = False
                record.appointment_end_datetime = False
                continue

            appointment_date = fields.Date.from_string(record.appointment_date)
            start_datetime = datetime.combine(appointment_date, time.min) + timedelta(hours=min(start_hours))
            end_datetime = datetime.combine(appointment_date, time.min) + timedelta(hours=max(end_hours))

            branch_tz = record.branch_id.tz or 'UTC'
            branch_timezone = pytz.timezone(branch_tz)

            record.appointment_start_datetime = branch_timezone.localize(start_datetime).astimezone(
                pytz.UTC).replace(tzinfo=None)
            record.appointment_end_datetime = branch_timezone.localize(end_datetime).astimezone(
                pytz.UTC).replace(tzinfo=None)

    @api.depends(
        'service_line_ids.is_party_product',
        'service_line_ids.party_prep_minutes',
        'service_line_ids.party_wrap_minutes'
    )
    def _compute_party_details(self):
        for record in self:
            prep_total = 0
            wrap_total = 0
            has_party = False
            for line in record.service_line_ids:
                prep_val = int(line.party_prep_minutes or 0)
                wrap_val = int(line.party_wrap_minutes or 0)
                if line.is_party_product or prep_val or wrap_val:
                    has_party = True
                prep_total += prep_val
                wrap_total += wrap_val
            record.has_party_details = has_party
            record.party_prep_minutes_total = prep_total
            record.party_wrap_minutes_total = wrap_total

    @api.depends('service_line_ids.beautician_id')
    def _compute_beautician_ids(self):
        for record in self:
            record.beautician_ids = record.service_line_ids.mapped('beautician_id')

    def _compute_duplicate_appointment_count(self):
        for record in self:
            parent = record.duplicate_parent_id or record
            duplicates = self.search([
                "|",
                ("id", "=", parent.id),
                ("duplicate_parent_id", "=", parent.id),
            ]) - record
            record.duplicate_appointment_count = len(duplicates)

    def action_view_duplicate_appointments(self):
        self.ensure_one()
        parent = self.duplicate_parent_id or self
        duplicates = self.search([
            "|",
            ("id", "=", parent.id),
            ("duplicate_parent_id", "=", parent.id),
        ]) - self

        return {
            'type': 'ir.actions.act_window',
            'name': _('Duplicate Appointments'),
            'res_model': 'salon.appointment',
            'view_mode': 'list,form',
            'domain': [('id', 'in', duplicates.ids)],
            'context': dict(self.env.context),
        }

    @api.depends('branch_id', 'branch_id.booking_fee')
    def _compute_booking_fee(self):
        for record in self:
            record.booking_fee = record.branch_id.booking_fee or 0.0

    @api.depends('appointment_ref', 'customer_first_name', 'customer_last_name', 'appointment_date', 'branch_id')
    def _compute_display_name(self):
        for record in self:
            customer_name = f"{record.customer_first_name or ''} {record.customer_last_name or ''}".strip()
            if not customer_name:
                customer_name = record.customer_id.name or 'Unknown Customer'

            date_str = record.appointment_date.strftime('%Y-%m-%d') if record.appointment_date else 'No Date'
            branch_name = record.branch_id.name if record.branch_id else 'No Branch'

            ref = record.appointment_ref or ''
            ref_prefix = f"{ref} - " if ref else ''
            record.display_name = f"{ref_prefix}{customer_name} - {date_str} - {branch_name}"

    @api.depends('pos_order_id')
    def _compute_pos_order_count(self):
        for appointment in self:
            appointment.pos_order_count = 1 if appointment.pos_order_id else 0

    def action_view_pos_order(self):
        self.ensure_one()
        if not self.pos_order_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': _('POS Order'),
            'res_model': 'pos.order',
            'view_mode': 'form',
            'res_id': self.pos_order_id.id,
            'context': {'create': False},
        }


    def _bb_surcharge_date(self):
        """Return the date the weekend surcharge is judged on.

        The booked appointment date, settled when the booking is made. It is
        deliberately not re-judged later against the day the work was actually
        carried out: a Sunday booking keeps its Sunday surcharge even when it
        is completed on the Monday, so the customer pays what they were quoted.
        """
        self.ensure_one()
        return self.appointment_date

    def _bb_surcharge_for_base_total(self, base_total):
        """Return the surcharge that applies to ``base_total`` for this booking.

        Kept here so the appointment, the POS checkout and the website all ask
        the same question and get the same answer.
        """
        self.ensure_one()
        return self.env['bb.appointment.pricing.service'].calculate_service_totals(
            base_total,
            appointment_date=self._bb_surcharge_date(),
            saturday_surcharge_percent=(
                self.branch_id.saturday_surcharge_percent if self.branch_id else 0.0
            ),
            sunday_surcharge_percent=(
                self.branch_id.sunday_surcharge_percent if self.branch_id else 0.0
            ),
        )

    @api.depends(
        'service_line_ids.total_price',
        'booking_fee',
        'appointment_date',
        'branch_id',
        'branch_id.saturday_surcharge_percent',
        'branch_id.sunday_surcharge_percent',
    )
    def _compute_totals(self):
        pricing_service = self.env['bb.appointment.pricing.service']
        for record in self:
            base_total = sum(record.service_line_ids.mapped('total_price'))
            totals = pricing_service.calculate_service_totals(
                base_total,
                appointment_date=record.appointment_date,
                saturday_surcharge_percent=(
                    record.branch_id.saturday_surcharge_percent
                    if record.branch_id else 0.0
                ),
                sunday_surcharge_percent=(
                    record.branch_id.sunday_surcharge_percent
                    if record.branch_id else 0.0
                ),
            )
            record.services_subtotal = totals['services_subtotal']
            record.surcharge_percent = totals['surcharge_percent']
            record.surcharge_amount = totals['surcharge_amount']
            record.services_total = totals['services_total']
            record.total_amount = totals['total_amount']

    # -------------------------
    # PAYMENT METHODS
    # -------------------------
    @api.depends(
        'payment_line_ids.payment_method',
        'payment_line_ids.payment_option',
        'payment_line_ids.payment_status',
        'payment_line_ids.refunded_amount',
    )
    def _compute_online_payment_summary(self):
        for appointment in self:
            online_payments = appointment.payment_line_ids.filtered(
                lambda payment: payment.payment_method == 'online'
            )
            completed_online = online_payments.filtered(
                lambda payment: (
                    payment.payment_status == 'completed'
                )
            )
            appointment.is_online_booking = bool(online_payments)
            refunded_total = sum(online_payments.mapped('refunded_amount'))
            appointment.online_refunded_amount = refunded_total
            if refunded_total:
                # Any online money handed back shows as Refunded, whole or part;
                # the Online Refunded amount says how much.
                appointment.online_payment_receipt_status = 'refunded'
            elif completed_online.filtered(lambda payment: payment.payment_option == 'full'):
                appointment.online_payment_receipt_status = 'full_received'
            elif completed_online.filtered(lambda payment: payment.payment_option == 'half'):
                appointment.online_payment_receipt_status = 'half_received'
            else:
                appointment.online_payment_receipt_status = 'not_received'

    def _update_payment_status(self):
        for appointment in self:
            completed = appointment.payment_line_ids.filtered(
                lambda p: p.payment_status == 'completed'
            )
            # Online booking payments remain deposits/prepayments until POS
            # checkout. The separate online_payment_receipt_status field shows
            # whether the online deposit was full or half without closing the
            # operational checkout flow.
            settling = sum(
                completed.filtered(lambda p: p.payment_method != 'online').mapped('payment_amount')
            )
            total_amount = appointment.total_amount or 0.0
            currency = appointment.currency_id or appointment.company_id.currency_id
            has_full_payment_evidence = bool(
                appointment.pos_order_paid
                or (
                    total_amount > 0
                    and currency.compare_amounts(settling, total_amount) >= 0
                )
            )
            new_status = self.env[
                'bb.appointment.pricing.service'
            ].determine_payment_status(
                has_full_payment_evidence=has_full_payment_evidence,
                has_partial_payment_evidence=bool(completed),
            )

            if appointment.payment_status != new_status:
                has_online_payment = bool(appointment.payment_line_ids.filtered(
                    lambda payment: payment.payment_method == 'online'
                ))
                appointment.with_context(
                    suppress_online_deposit_payment_status_log=(
                        has_online_payment and new_status != 'paid'
                    )
                ).write({'payment_status': new_status})

    @api.model
    def _reconcile_online_deposit_payment_statuses(self):
        """Restore online deposits to partial without changing paid POS sales."""
        appointments = self.sudo().search([
            ('pos_order_paid', '=', False),
            ('payment_line_ids.payment_method', '=', 'online'),
            ('payment_line_ids.payment_status', '=', 'completed'),
        ])
        appointments._update_payment_status()
        return True

    # -------------------------
    # OVERRIDE CREATE
    # -------------------------
    @api.model
    def _lock_appointment_reference_sequence(self):
        """Serialize appointment reference allocation and deletion resets."""
        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(%s, %s)",
            [0x53414C4F, 0x41505054],  # "SALO" / "APPT"
        )

    @api.model
    def _appointment_reference_sequence(self):
        """Return the global APPT sequence used by every company/branch."""
        return self.env['ir.sequence'].sudo().search([
            ('code', '=', 'salon.appointment'),
            ('company_id', '=', False),
        ], limit=1)

    #: Code of the per-company sequence behind `appointment_no`.
    APPOINTMENT_NUMBER_SEQUENCE_CODE = 'salon.appointment.booking'

    @api.model
    def _company_appointment_sequence(self, company):
        """The company's own appointment sequence, made on first use.

        One sequence per company, so each counts its own appointments from one
        and a company added later needs nothing set up by hand. The prefix is
        left on the sequence record rather than built here, so a company can be
        given its own without a code change.

        Callers hold the appointment reference lock, which is what stops two
        bookings from creating the sequence twice.
        """
        if not company:
            return self.env['ir.sequence'].browse()
        Sequence = self.env['ir.sequence'].sudo()
        sequence = Sequence.search([
            ('code', '=', self.APPOINTMENT_NUMBER_SEQUENCE_CODE),
            ('company_id', '=', company.id),
        ], limit=1)
        return sequence or Sequence.create({
            'name': f'Appointment Number - {company.name}',
            'code': self.APPOINTMENT_NUMBER_SEQUENCE_CODE,
            'company_id': company.id,
            'prefix': 'APP/',
            'padding': 5,
            'number_next': 1,
            'implementation': 'standard',
        })

    @api.model
    def _appointment_company(self, vals):
        """The company a set of appointment values belongs to.

        Taken from the values where they carry one, otherwise from the branch
        being booked, which is what the rest of create() does. Falls back to
        the company in force so a booking is never left without a number.
        """
        company_id = vals.get('company_id')
        if not company_id and vals.get('branch_id'):
            branch = self.env['beauty.branch'].sudo().browse(vals['branch_id']).exists()
            company_id = branch.company_id.id if branch else None
        return self.env['res.company'].sudo().browse(company_id) if company_id else self.env.company

    @api.model
    def _appointment_reference_number(self, reference):
        """Return the numeric part of a canonical APPT reference."""
        if not isinstance(reference, str) or not reference.startswith('APPT'):
            return None
        number = reference[4:]
        return int(number) if number.isdigit() and int(number) > 0 else None

    @api.model
    def _appointment_reference_state(self):
        """Return global references, their numbers, and the lowest free number."""
        references = set(self.sudo().search([]).mapped('appointment_ref'))
        references.discard(False)
        numbers = {
            number
            for reference in references
            if (number := self._appointment_reference_number(reference)) is not None
        }
        next_number = 1
        while next_number in numbers:
            next_number += 1
        return references, numbers, next_number

    @api.model_create_multi
    def create(self, vals_list):
        """Allocate the references, then create the customer if there is none.

        api.model_create_multi already turns a single dict into a list, so
        every caller shape reaches here as a list.
        """
        # Record the channel the booking came through. Leave and Break set the
        # type themselves and are not customer bookings, so they are left
        # alone; anything else is asked of the channel hook.
        for vals in vals_list:
            if not vals.get('appointment_type'):
                vals['appointment_type'] = self._booking_channel(vals)

        self._lock_appointment_reference_sequence()
        allowed_company_ids = self.env.companies.ids or [self.env.company.id]
        sequence = self._appointment_reference_sequence()

        # By default, never trust client-provided appointment_ref values.
        # Allocate a unique APPT number through Odoo's database sequence. The
        # advisory transaction lock still serializes this custom path with
        # deletion and other appointment-reference operations.
        allow_manual_ref = bool(self.env.context.get('allow_manual_appointment_ref'))

        def _allocate_reference():
            if not sequence:
                return 'New'
            # Use Odoo's atomic PostgreSQL sequence allocation.  Writing
            # number_next_actual after create races with concurrent requests
            # and can turn a valid booking into a serialization failure.
            return sequence.next_by_id()

        # Process each record
        processed_vals_list = []
        for vals in vals_list:
            incoming_ref = vals.get('appointment_ref')
            ref = (incoming_ref or 'New')
            if isinstance(ref, str):
                ref = ref.strip()

            if not allow_manual_ref and ref not in (False, '', 'New'):
                ref = 'New'

            if ref in (False, '', 'New'):
                ref = _allocate_reference()
            vals['appointment_ref'] = ref

            # A real booking also takes a number of its own within its company,
            # whichever channel it arrived through. Leave and break slots keep
            # the calendar reference above and nothing more, so a blank here
            # says the record never served a customer. Never taken from the
            # caller: like the reference, it is the system's to give.
            vals.pop('appointment_no', None)
            if vals.get('appointment_type') in self.BOOKING_APPOINTMENT_TYPES:
                company_sequence = self._company_appointment_sequence(
                    self._appointment_company(vals))
                if company_sequence:
                    vals['appointment_no'] = company_sequence.next_by_id()

            # Create customer if needed
            if not vals.get('customer_id') and vals.get('customer_phone'):
                company_id = vals.get('company_id')
                if not company_id and vals.get('branch_id'):
                    branch = self.env['beauty.branch'].search([
                        ('id', '=', vals['branch_id']),
                        ('company_id', 'in', allowed_company_ids),
                    ], limit=1)
                    if branch:
                        company_id = branch.company_id.id
                customer_vals = {
                    'name': f"{vals.get('customer_first_name', '')} {vals.get('customer_last_name', '')}".strip(),
                    'email': vals.get('customer_email'),
                    'phone': vals.get('customer_phone'),
                    'is_company': False,
                    'company_id': company_id or self.env.company.id,
                }
                customer = self.env['res.partner'].create(customer_vals)
                vals['customer_id'] = customer.id

            processed_vals_list.append(vals)

        # Call super with list (disable default tracking to avoid duplicate chatter)
        records = super(SalonAppointment, self.with_context(tracking_disable=True)).create(processed_vals_list)

        # Log each provided field as a separate message for clarity
        for record, vals in zip(records, processed_vals_list):
            record._log_field_changes(vals, prefix=_("Appointment created"))

        return records

    def unlink(self):
        """Delete through ORM cascades without mutating the live sequence."""
        return super().unlink()

    def write(self, vals):
        if not vals:
            return super().write(vals)

        # Capture old values per record before write
        tracked_fields = self._get_chatter_tracked_fields(vals)
        old_values = {
            record.id: {name: record[name] for name in tracked_fields}
            for record in self
        }

        res = super(SalonAppointment, self.with_context(tracking_disable=True)).write(vals)

        # Log each field change as a separate message
        for record in self:
            record._log_field_changes(
                vals,
                prefix=_("Appointment updated"),
                old_values=old_values.get(record.id, {})
            )

        return res

    def _get_chatter_tracked_fields(self, vals):
        skip = {
            'message_follower_ids', 'message_partner_ids', 'message_ids',
            'activity_ids', 'activity_exception_decoration', 'activity_state',
            'activity_type_icon', 'activity_type_id', 'activity_user_id',
            'display_name',
        }
        if self.env.context.get('suppress_online_deposit_payment_status_log'):
            skip.add('payment_status')
        return [name for name in vals.keys() if name in self._fields and name not in skip]

    def _log_field_changes(self, vals, prefix, old_values=None):
        old_values = old_values or {}
        changes = []
        label_overrides = {
            'real_planned_start': _('Scheduled Start Time'),
            'real_planned_end': _('Scheduled End Time'),
            'total_amount_before_discount': _('Total Before Discount'),
            'total_amount_after_discount': _('Total After Discount'),
        }
        for name in self._get_chatter_tracked_fields(vals):
            field = self._fields.get(name)
            if not field:
                continue
            old = old_values.get(name, False)
            new = self[name]

            # Normalize for comparison
            if field.type == 'many2one':
                old_cmp = old.id if old else False
                new_cmp = new.id if new else False
            elif field.type in ('many2many', 'one2many'):
                old_cmp = old.ids if old else []
                new_cmp = new.ids if new else []
            else:
                old_cmp = old
                new_cmp = new

            if old_cmp == new_cmp and name in old_values:
                continue

            field_label = label_overrides.get(name, field.string or name)
            old_disp = self._format_field_value(field, old)
            new_disp = self._format_field_value(field, new)

            if old_values:
                change = _("%s: %s → %s") % (field_label, old_disp, new_disp)
            else:
                change = _("%s: %s") % (field_label, new_disp)
            changes.append(change)

        if changes:
            items = Markup('').join(
                Markup('<li>{}</li>').format(escape(change))
                for change in changes
            )
            body = Markup(
                '<div class="o_mail_notification">'
                '<p><strong>{}</strong></p><ul>{}</ul><hr/></div>'
            ).format(escape(prefix), items)
            self.message_post(
                body=body,
                subtype_xmlid="mail.mt_note",
            )

    def _history_tz_name(self):
        self.ensure_one()
        return (self.branch_id and self.branch_id.tz) or self.env.user.tz or 'UTC'

    def _format_datetime_for_history(self, value):
        if not value:
            return "None"

        dt_value = None
        if isinstance(value, datetime):
            dt_value = value
        elif isinstance(value, str):
            parsed = value.strip()
            # Tracking payload often includes UTC suffix like `...Z`.
            if parsed.endswith('Z'):
                parsed = parsed[:-1] + '+00:00'
            try:
                dt_value = datetime.fromisoformat(parsed.replace(' ', 'T'))
            except ValueError:
                dt_value = fields.Datetime.to_datetime(value)
        else:
            dt_value = fields.Datetime.to_datetime(value)

        if not dt_value:
            return str(value)

        tz_name = self._history_tz_name()
        branch_tz = pytz.timezone(tz_name)
        if dt_value.tzinfo:
            dt_utc = dt_value.astimezone(pytz.UTC)
        else:
            dt_utc = pytz.UTC.localize(dt_value)
        dt_local = dt_utc.astimezone(branch_tz)
        return dt_local.strftime('%b %d, %Y, %I:%M %p')

    def _format_field_value(self, field, value):
        empty_label = _("Not set")
        if field.type == 'many2one':
            return value.display_name if value else empty_label
        if field.type in ('many2many', 'one2many'):
            return ", ".join(value.mapped('display_name')) if value else empty_label
        if field.type == 'monetary':
            if value in (False, None, ''):
                return empty_label
            currency = self.currency_id or self.company_id.currency_id
            return format_amount(self.env, value, currency)
        if field.type == 'float' and ('duration' in (field.name or '') or 'Duration' in (field.string or '')):
            return SalonAppointment._format_duration_hours(value)
        if field.type == 'float' and 'percent' in (field.name or ''):
            if value in (False, None, ''):
                return empty_label
            return f"{float(value) * 100:.2f}%"
        if field.type == 'selection':
            if value in (False, None, ''):
                return empty_label
            selection = dict(field.selection)
            return selection.get(value, value)
        if field.type == 'boolean':
            return "Yes" if value else "No"
        if field.type in ('date', 'datetime'):
            if not value:
                return empty_label
            if field.type == 'date':
                return fields.Date.to_string(value)
            return self._format_datetime_for_history(value)
        return str(value) if value not in (False, None, '') else empty_label

    @staticmethod
    def _format_duration_hours(value):
        if value in (False, None, ''):
            return "None"
        try:
            total_minutes = int(round(float(value) * 60))
        except (TypeError, ValueError):
            return str(value)
        hours = total_minutes // 60
        minutes = total_minutes % 60
        if hours and minutes:
            return f"{hours}h {minutes}m"
        if hours:
            return f"{hours}h"
        return f"{minutes}m"

    # -------------------------
    # STATE TRANSITIONS
    # -------------------------
    def action_confirm(self):
        self.state = 'confirmed'

    def action_start(self):
        """Mark the customer as arrived. This does not start the service.

        The button reads "Arrived": the state it sets, in_progress, is
        labelled Arrived. Guarded so a completed or cancelled appointment
        cannot be dragged back to Arrived by a stale form.
        """
        for appointment in self:
            if appointment.state in ('draft', 'confirmed'):
                appointment.state = 'in_progress'

    def action_complete(self):
        self.state = 'completed'

    def action_reset_to_draft(self):
        """Reset appointment status through normal write permissions.

        This is a booking correction, not a payment/refund reversal. Keep the
        payment evidence, linked orders and recorded service timings intact.
        """
        self.filtered(lambda appointment: appointment.state != 'draft').write({'state': 'draft'})
        return True

    def action_open_cancel_wizard(self):
        """Ask for a reason before cancelling, from the backend form."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Cancel Appointment'),
            'res_model': 'salon.appointment.cancel.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_appointment_id': self.id},
        }

    def action_cancel(self, reason_id=None, note=None):
        """Cancel, optionally recording why.

        The arguments are optional so every existing caller keeps working; the
        POS and the backend wizard pass them, older callers do not.
        """
        vals = {'state': 'cancelled'}
        if reason_id:
            vals['cancellation_reason_id'] = int(reason_id)
        if note:
            vals['cancellation_note'] = note
        self.write(vals)

    def action_mark_refunded(self):
        """Move to Refunded once the appointment's POS order is fully refunded."""
        for appointment in self:
            if appointment.state != 'refunded':
                appointment.write({'state': 'refunded'})

    @api.model
    def _cron_expire_draft_appointments(self):
        """Cancel draft appointments whose expiry time has passed.

        A draft appointment is a tentative hold. Once the customer confirms
        it, the hold is real and the expiry no longer applies, so only draft
        records are considered. Follows the same shape as the call-center
        waiting-list expiry: find, explain in the chatter, cancel.
        """
        expired = self.search([
            ('auto_expire', '=', True),
            ('auto_expire_datetime', '!=', False),
            ('auto_expire_datetime', '<=', fields.Datetime.now()),
            ('state', '=', 'draft'),
        ])
        if not expired:
            return 0
        for appointment in expired:
            appointment.message_post(body=_(
                "Automatically cancelled: this appointment was still "
                "unconfirmed when its expiry time passed."
            ))
        # Stamp the expiry reason so these are distinguishable in reporting
        # from cancellations a person made. Missing reason data must not stop
        # the expiry itself, so this falls back to a plain cancel.
        reason = self.env.ref(
            'bb_salon_appoitments.cancellation_reason_expired', raise_if_not_found=False)
        expired.action_cancel(
            reason_id=reason.id if reason else None,
            # Say plainly that nobody cancelled this: the note is what staff
            # read on the form, and "Expired" alone does not tell them whether
            # a person or the system did it.
            note=_('Cancelled automatically by the scheduled action '
                   '(not confirmed before the expiry time).'),
        )
        return len(expired)

    @api.onchange('auto_expire')
    def _onchange_auto_expire(self):
        """Clear the expiry time when the option is switched off.

        Leaving a stale timestamp behind would cancel the appointment if the
        option were ever switched back on without setting a new time.
        """
        if not self.auto_expire:
            self.auto_expire_datetime = False

    @api.constrains('auto_expire', 'auto_expire_datetime')
    def _check_auto_expire_datetime(self):
        for appointment in self:
            if appointment.auto_expire and not appointment.auto_expire_datetime:
                raise ValidationError(_(
                    "Set the time this appointment should expire, or turn "
                    "off Auto-expire at set time."
                ))

    def get_history_messages(self, limit=100):
        self.ensure_one()
        subtype_id = self.env.ref('mail.mt_note').id
        messages = self.env['mail.message'].search(
            [
                ('model', '=', self._name),
                ('res_id', '=', self.id),
                '|',
                ('subtype_id', '=', subtype_id),
                ('tracking_value_ids', '!=', False),
            ],
            order='date desc, id desc',
            limit=limit,
        )
        currency_cache = {}
        return [
            {
                'id': msg.id,
                'date': msg.date,
                'author': msg.author_id.name or msg.email_from or '',
                'author_id': msg.author_id.id or False,
                'author_image': msg.author_id.image_128 or False,
                'body': msg.body or '',
                'tracking_values': msg.tracking_value_ids._tracking_value_format() if msg.tracking_value_ids else [],
            }
            for msg in messages
        ]

    def _format_history_body(self, msg, currency_cache):
        body = (msg.body or '').strip()
        if body:
            return body

        if not msg.tracking_value_ids:
            return ''

        lines = []
        for item in msg.tracking_value_ids._tracking_value_format():
            field_name = item['fieldInfo']['changedField']
            field_type = item['fieldInfo']['fieldType']
            old_val = item.get('oldValue')
            new_val = item.get('newValue')
            currency_id = item['fieldInfo'].get('currencyId')

            old_disp = self._format_tracking_value(field_name, field_type, old_val, currency_id, currency_cache)
            new_disp = self._format_tracking_value(field_name, field_type, new_val, currency_id, currency_cache)
            lines.append(f"{old_disp} -> {new_disp} ({field_name})")

        return "\n".join(lines)

    def _format_tracking_value(self, field_name, field_type, value, currency_id, currency_cache):
        if value in (False, None, '', []):
            return "None"

        # Duration fields: display in hours/minutes
        if field_type == 'float' and ('duration' in (field_name or '').lower()):
            return self._format_duration_hours(value)

        if field_type == 'monetary':
            if not currency_id:
                return str(value)
            currency = currency_cache.get(currency_id)
            if not currency:
                currency = self.env['res.currency'].browse(currency_id)
                currency_cache[currency_id] = currency
            try:
                return currency.format(value)
            except Exception:
                return str(value)

        if field_type in ('date', 'datetime'):
            if not value:
                return "None"
            if field_type == 'date':
                return str(value)
            return self._format_datetime_for_history(value)

        return str(value)

    # -------------------------
    # TEST UTILITIES
    # -------------------------
    def action_delete_all_appointments(self):
        """
        TEST ONLY: delete all appointments and related deposits/journal entries.
        """
        allowed_company_ids = self.env.companies.ids or [self.env.company.id]
        appointments = self.env['salon.appointment'].sudo().search([
            ('company_id', 'in', allowed_company_ids),
        ])
        if not appointments:
            return {'type': 'ir.actions.client', 'tag': 'reload'}

        deposits = self.env['beauty.customer.deposit'].sudo().search([
            ('appointment_id', 'in', appointments.ids),
            ('company_id', 'in', allowed_company_ids),
        ])
        moves = deposits.mapped('move_id').filtered(
            lambda m: not m.company_id or m.company_id.id in allowed_company_ids
        ).sudo()

        for move in moves:
            if move.state == 'posted' and hasattr(move, 'button_draft'):
                move.button_draft()

        moves.with_context(force_delete=True).unlink()
        deposits.unlink()
        appointments.unlink()

        return {'type': 'ir.actions.client', 'tag': 'reload'}
    # -------------------------
    # POS INTEGRATION METHODS
    # -------------------------
    def update_pos_payment_status(self, pos_order_id, session_id, is_paid):
        """Update POS order information and payment status for this appointment"""
        for appointment in self:
            appointment.write({
                'pos_order_id': pos_order_id,
                'session_id': session_id,
                'pos_order_paid': is_paid
            })
            # Re-evaluate payment status now that the POS sale is (un)paid, so an
            # online-deposit appointment flips to 'paid' once checked out in POS.
            appointment._update_payment_status()
        return True

    # -------------------------
    # POS DATA LOADING (Odoo 19)
    # -------------------------
    def _load_pos_data_domain(self, data):
        """Define which appointments to load in POS - only from current session or recent/upcoming"""
        # Load appointments from:
        # 1. Current session (if available in data)
        # 2. Or appointments from today and next 7 days
        session_id = data.get('pos.session', {}).get('id')
        if session_id:
            # Prefer session-based loading
            return [
                '|',
                ('session_id', '=', session_id),
                ('session_id', '=', False),
                ('company_id', 'in', self.env.companies.ids),
            ]
        else:
            # Fallback: load recent and upcoming appointments
            from datetime import date, timedelta
            today = date.today()
            future_date = today + timedelta(days=7)
            past_date = today - timedelta(days=1)
            return [
                ('appointment_date', '>=', past_date.isoformat()),
                ('appointment_date', '<=', future_date.isoformat()),
                ('company_id', 'in', self.env.companies.ids),
            ]


class SalonAppointmentQuestionAnswer(models.Model):
    _name = 'salon.appointment.question.answer'
    _description = 'Appointment Booking Question Answer'
    _order = 'service_line_id, sequence, id'

    appointment_id = fields.Many2one(
        'salon.appointment', string='Appointment', required=True, ondelete='cascade'
    )
    service_line_id = fields.Many2one(
        'salon.appointment.service', string='Service Line', ondelete='cascade'
    )
    product_tmpl_id = fields.Many2one('product.template', string='Product')
    service_name = fields.Char(string='Service', readonly=True)
    important_notice = fields.Text(string='Important Notice', readonly=True)
    sequence = fields.Integer(string='Sequence', default=10)
    question_text = fields.Char(string='Question', readonly=True)
    answer_text = fields.Text(string='Answer')
