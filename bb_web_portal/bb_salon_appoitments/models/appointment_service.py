from odoo import models, fields, api, _
from markupsafe import Markup
from datetime import timedelta
from odoo.exceptions import ValidationError


class SalonAppointmentService(models.Model):
    _name = 'salon.appointment.service'
    _description = 'Salon Appointment Service Line'

    # -------------------------
    # Appointment & Service
    # -------------------------
    appointment_id = fields.Many2one(
        'salon.appointment',
        string='Appointment',
        required=True,
        ondelete='cascade'
    )
    service_id = fields.Many2one(
        'product.product',
        string='Service',
        required=True,
        domain=[('type', '=', 'service')]
    )
    service_category_id = fields.Many2one(
        'product.category',
        string='Service Category',
        compute='_compute_service_details',
        store=True
    )
    service_name = fields.Char(
        string='Service Name',
        compute='_compute_service_details',
        store=True
    )

    # -------------------------
    # Beautician Information
    # -------------------------
    beautician_id = fields.Many2one(
        'hr.employee',
        string='Beautician',
        required=False,  # Not required for waiting list appointments
        domain=[('is_beautician', '=', True)]
    )
    beautician_name = fields.Char(
        string='Beautician Name',
        compute='_compute_beautician_name',
        store=True
    )
    staff_requested_by_client = fields.Boolean(
        string='Staff Requested by Client',
        default=False,
        help='The client specifically requested the professional assigned to this service.',
    )
    additional_beautician_ids = fields.Many2many(
        'hr.employee',
        'appointment_service_beautician_rel',
        'appointment_service_id',
        'employee_id',
        string="Additional Beauticians",
        domain="[('is_beautician', '=', True)]",
        help="Additional beauticians assigned to this service"
    )

    # -------------------------
    # Pricing
    # -------------------------
    base_price = fields.Float(
        string='Base Price',
        compute='_compute_service_details',
        store=True
    )
    beautician_addon_price = fields.Monetary(
        string='Beautician Add-on Price',
        default=0.0
    )
    total_price = fields.Monetary(
        string='Total Price',
        compute='_compute_total_price',
        store=True
    )

    # -------------------------
    # Duration & Time Slot
    # -------------------------
    duration = fields.Float(
        string='Duration (Hours)',
        default=0.0,
    )
    duration_display = fields.Char(
        string='Duration Display',
        compute='_compute_service_details',
        store=True
    )
    is_party_product = fields.Boolean(
        string="Party Service",
        compute='_compute_service_details',
        store=True
    )
    party_prep_minutes = fields.Integer(
        string="Preparation (min)",
        compute='_compute_service_details',
        store=True,
        readonly=False,
    )
    party_prep_color = fields.Char(
        string="Preparation Color",
        compute='_compute_service_details',
        store=True
    )
    party_wrap_minutes = fields.Integer(
        string="Wrap-up/Cleanup (min)",
        compute='_compute_service_details',
        store=True,
        readonly=False,
    )
    party_wrap_color = fields.Char(
        string="Wrap-up Color",
        compute='_compute_service_details',
        store=True
    )
    time_period = fields.Selection([
        ('morning', 'Morning'),
        ('evening', 'Evening')
    ], string='Time Period')

    start_hour = fields.Float('Start Hour', required=False, default=0.0)  # Not required for waiting list
    end_hour = fields.Float('End Hour', compute='_compute_end_hour', store=True)
    time_slot = fields.Char(string='Time Slot')
    time_display = fields.Char('Time Display', compute='_compute_time_display', store=True)

    # -------------------------
    # Currency
    # -------------------------
    currency_id = fields.Many2one(
        'res.currency',
        related='appointment_id.currency_id'
    )

    # A service added at POS checkout is written back as an ordinary service
    # line, so once it is there it reads the same as a booked one. This is the
    # only record that it was sold on top of the booking, which the Upselling
    # report needs.
    added_at_checkout = fields.Boolean(
        string='Added at Checkout',
        default=False,
        copy=False,
        help="Set when this service was added at POS checkout rather than "
             "booked in the original appointment. Ticked automatically for "
             "new checkouts; tick it by hand on an older appointment to count "
             "the service in the Upselling report.",
    )

    _BACKFILL_FLAG = 'bb_salon_appoitments.added_at_checkout_backfilled'

    @api.model
    def _backfill_added_at_checkout(self):
        """Flag checkout additions recorded before the flag existed.

        Checkout additions are written with zero duration so the appointment
        keeps its planned time window, and a booked service has a duration.
        So a zero-duration line on a settled appointment that also has a
        timed service is a checkout addition. Declared as a function so it
        runs on module update, which is how it reaches the lines already in
        the system. It runs once: later zero-duration lines are flagged by
        the checkout sync itself, not guessed at here.
        """
        params = self.env['ir.config_parameter'].sudo()
        if params.get_param(self._BACKFILL_FLAG):
            return
        # Raw SQL below, so anything still pending in the ORM must reach the
        # database first or those lines would not be seen.
        self.env.flush_all()
        self.env.cr.execute("""
            UPDATE salon_appointment_service sas
               SET added_at_checkout = TRUE
              FROM salon_appointment sa
             WHERE sa.id = sas.appointment_id
               AND sa.pos_order_id IS NOT NULL
               AND COALESCE(sas.duration, 0) = 0
               AND COALESCE(sas.added_at_checkout, FALSE) = FALSE
               AND EXISTS (
                   SELECT 1 FROM salon_appointment_service timed
                    WHERE timed.appointment_id = sa.id
                      AND COALESCE(timed.duration, 0) > 0
               )
        """)
        self.env.invalidate_all()
        params.set_param(self._BACKFILL_FLAG, '1')

    # -------------------------
    # OVERRIDE CREATE
    # -------------------------
    @api.model_create_multi
    def create(self, vals_list):
        """
        Override create to manually set base_price from service_id.list_price
        since the computed field doesn't trigger during creation.
        """
        for vals in vals_list:
            if 'service_id' in vals and vals['service_id']:
                service = self.env['product.product'].search([
                    ('id', '=', vals['service_id']),
                    ('type', '=', 'service'),
                    '|',
                    ('product_tmpl_id.company_id', '=', False),
                    ('product_tmpl_id.company_id', 'in', self.env.companies.ids),
                ], limit=1)
                if service:
                    # Manually set base_price from service list_price
                    vals['base_price'] = service.list_price

                    # Also set other computed fields if not already set
                    if 'service_name' not in vals:
                        vals['service_name'] = service.name
                    if 'service_category_id' not in vals and service.categ_id:
                        vals['service_category_id'] = service.categ_id.id
                    if 'duration' not in vals:
                        vals['duration'] = getattr(service, 'duration', 1.0)

        records = super(SalonAppointmentService, self).create(vals_list)
        for record in records:
            record._log_appointment_change(
                _("Service line added: %s") % (record.service_name or record.service_id.display_name or "Unknown")
            )
        records._create_consumption_lines()
        records._create_booking_question_answers()
        return records

    def write(self, vals):
        if not vals:
            return super().write(vals)

        if 'service_id' in vals and 'duration' not in vals:
            new_service = self.env['product.product'].browse(vals['service_id'])
            vals['duration'] = getattr(new_service, 'duration', 1.0) or 0.0

        tracked_fields = self._get_chatter_tracked_fields(vals)
        old_values = {
            record.id: {name: record[name] for name in tracked_fields}
            for record in self
        }

        res = super().write(vals)

        for record in self:
            record._log_field_changes(
                vals,
                prefix=_("Service line updated: %s") % (record.service_name or record.service_id.display_name or "Unknown"),
                old_values=old_values.get(record.id, {})
            )
        if 'service_id' in vals:
            self._refresh_consumption_lines()
            self._refresh_booking_question_answers()
        return res

    def _create_booking_question_answers(self):
        qa_model = self.env['salon.appointment.question.answer']
        vals_list = []
        for record in self:
            if not record.appointment_id:
                continue
            tmpl = record.service_id.product_tmpl_id if record.service_id else False
            if not tmpl or tmpl.booking_question_display == 'not_required' or not tmpl.booking_question_ids:
                continue
            for q in tmpl.booking_question_ids:
                vals_list.append({
                    'appointment_id': record.appointment_id.id,
                    'service_line_id': record.id,
                    'product_tmpl_id': tmpl.id,
                    'service_name': record.service_name or record.service_id.name or '',
                    'important_notice': tmpl.important_notice or '',
                    'sequence': q.sequence,
                    'question_text': q.question_text,
                    'answer_text': '',
                })
        if vals_list:
            qa_model.create(vals_list)

    def _refresh_booking_question_answers(self):
        qa_model = self.env['salon.appointment.question.answer']
        for record in self:
            qa_model.search([('service_line_id', '=', record.id)]).unlink()
        self._create_booking_question_answers()

    def _create_consumption_lines(self):
        consumption_model = self.env['salon.appointment.consumption']
        vals_list = []
        for record in self:
            tmpl = record.service_id.product_tmpl_id if record.service_id else False
            if not tmpl or not tmpl.consumption_line_ids:
                continue
            for tmpl_line in tmpl.consumption_line_ids:
                if not tmpl_line.product_id:
                    continue
                existing = consumption_model.search([
                    ('service_line_id', '=', record.id),
                    ('product_id', '=', tmpl_line.product_id.id),
                    ('uom_id', '=', tmpl_line.uom_id.id),
                ], limit=1)
                if existing:
                    continue
                vals_list.append({
                    'service_line_id': record.id,
                    'product_id': tmpl_line.product_id.id,
                    'uom_id': tmpl_line.uom_id.id,
                    'planned_qty': tmpl_line.quantity,
                    'actual_qty': tmpl_line.quantity,
                })
        if vals_list:
            consumption_model.create(vals_list)

    def _refresh_consumption_lines(self):
        consumption_model = self.env['salon.appointment.consumption']
        for record in self:
            lines = consumption_model.search([('service_line_id', '=', record.id)])
            existing_actual = {
                (line.product_id.id, line.uom_id.id): line.actual_qty
                for line in lines
            }
            if lines:
                lines.unlink()
            tmpl = record.service_id.product_tmpl_id if record.service_id else False
            if not tmpl or not tmpl.consumption_line_ids:
                continue
            vals_list = []
            for tmpl_line in tmpl.consumption_line_ids:
                if not tmpl_line.product_id:
                    continue
                actual_qty = existing_actual.get(
                    (tmpl_line.product_id.id, tmpl_line.uom_id.id),
                    tmpl_line.quantity
                )
                vals_list.append({
                    'service_line_id': record.id,
                    'product_id': tmpl_line.product_id.id,
                    'uom_id': tmpl_line.uom_id.id,
                    'planned_qty': tmpl_line.quantity,
                    'actual_qty': actual_qty,
                })
            if vals_list:
                consumption_model.create(vals_list)

    # -------------------------
    # COMPUTE METHODS
    # -------------------------
    @api.depends(
        'service_id',
        'service_id.product_tmpl_id.is_party_product',
        'service_id.product_tmpl_id.party_prep_minutes',
        'service_id.product_tmpl_id.party_prep_color',
        'service_id.product_tmpl_id.party_wrap_minutes',
        'service_id.product_tmpl_id.party_wrap_color'
    )
    def _compute_service_details(self):
        for record in self:
            if record.service_id:
                record.service_category_id = record.service_id.categ_id.id
                record.service_name = record.service_id.name
                record.base_price = record.service_id.list_price

                # Duration display (duration value managed separately)
                record.duration_display = getattr(
                    record.service_id,
                    'service_duration_display',
                    self._format_duration(record.duration)
                )
                tmpl = record.service_id.product_tmpl_id
                record.is_party_product = bool(getattr(tmpl, 'is_party_product', False))
                record.party_prep_minutes = int(getattr(tmpl, 'party_prep_minutes', 0) or 0)
                record.party_prep_color = getattr(tmpl, 'party_prep_color', '') or ''
                record.party_wrap_minutes = int(getattr(tmpl, 'party_wrap_minutes', 0) or 0)
                record.party_wrap_color = getattr(tmpl, 'party_wrap_color', '') or ''
            else:
                record.service_category_id = False
                record.service_name = False
                record.base_price = 0.0
                record.duration_display = False
                record.is_party_product = False
                record.party_prep_minutes = 0
                record.party_prep_color = ''
                record.party_wrap_minutes = 0
                record.party_wrap_color = ''

    @staticmethod
    def _format_duration(duration):
        hours = int(duration)
        minutes = round((duration % 1) * 60)
        if hours > 0 and minutes > 0:
            return f"{hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h"
        else:
            return f"{minutes}m"

    @api.depends('beautician_id')
    def _compute_beautician_name(self):
        for record in self:
            record.beautician_name = record.beautician_id.name if record.beautician_id else False

    @api.depends('base_price', 'beautician_addon_price')
    def _compute_total_price(self):
        pricing_service = self.env['bb.appointment.pricing.service']
        for record in self:
            record.total_price = pricing_service.calculate_line_total(
                record.base_price,
                record.beautician_addon_price,
            )

    @api.onchange('service_id', 'beautician_id')
    def _onchange_service_beautician(self):
        if self.service_id and self.beautician_id:
            try:
                lines = getattr(self.service_id.product_tmpl_id, 'beautician_line_ids', False)
                if lines:
                    beautician_line = lines.filtered(lambda l: l.beautician_id == self.beautician_id)
                    self.beautician_addon_price = beautician_line[0].price if beautician_line else 0.0
                else:
                    self.beautician_addon_price = 0.0
            except Exception:
                self.beautician_addon_price = 0.0

    @api.depends('start_hour', 'duration')
    def _compute_end_hour(self):
        pricing_service = self.env['bb.appointment.pricing.service']
        for record in self:
            record.end_hour = pricing_service.calculate_end_hour(
                record.start_hour,
                record.duration,
            )

    def _float_to_time_string(self, float_hour):
        """Convert float hour to HH:MM string format."""
        return self.env['bb.appointment.pricing.service'].format_time_hour(
            float_hour
        )

    @api.depends('start_hour', 'end_hour')
    def _compute_time_display(self):
        for record in self:
            start_str = record._float_to_time_string(record.start_hour)
            end_str = record._float_to_time_string(record.end_hour)
            if start_str and end_str and start_str != "Invalid" and end_str != "Invalid":
                record.time_display = f"{start_str} - {end_str}"
            else:
                record.time_display = ""

    # -------------------------
    # POS DATA LOADING (Odoo 19)
    # -------------------------
    def _load_pos_data_domain(self, data):
        """Define which service lines to load in POS - based on loaded appointments"""
        # Load service lines for appointments that are loaded in POS
        appointment_data = data.get('salon.appointment', {})
        loaded_appointment_ids = []

        # Extract appointment IDs from loaded data
        appointments = appointment_data.get('data', []) if isinstance(appointment_data, dict) else appointment_data
        for appointment in appointments:
            if isinstance(appointment, dict) and 'id' in appointment:
                loaded_appointment_ids.append(appointment['id'])
            elif isinstance(appointment, int):
                loaded_appointment_ids.append(appointment)

        if loaded_appointment_ids:
            return [
                ('appointment_id', 'in', loaded_appointment_ids),
                ('appointment_id.company_id', 'in', self.env.companies.ids),
            ]
        else:
            # Fallback: load service lines for recent appointments
            from datetime import date, timedelta
            today = date.today()
            future_date = today + timedelta(days=7)
            past_date = today - timedelta(days=1)
            return [
                ('appointment_id.appointment_date', '>=', past_date.isoformat()),
                ('appointment_id.appointment_date', '<=', future_date.isoformat()),
                ('appointment_id.company_id', 'in', self.env.companies.ids),
            ]

    def _load_pos_data_fields(self, data):
        """Define which service line fields to load in POS"""
        return [
            'appointment_id', 'service_id', 'service_category_id', 'service_name',
            'beautician_id', 'beautician_name', 'additional_beautician_ids',
            'base_price', 'beautician_addon_price', 'total_price',
            'duration', 'duration_display', 'time_period',
            'start_hour', 'end_hour', 'time_slot', 'time_display',
            'resource_ids', 'currency_id'
        ]

    def _load_pos_data(self, data):
        """Load service line data for POS (Odoo 19 pattern)"""
        domain = self._load_pos_data_domain(data)
        fields = self._load_pos_data_fields(data)
        service_lines = self.search_read(domain, fields, order='appointment_id, start_hour asc')
        return {
            'data': service_lines,
            'fields': fields,
        }

    def unlink(self):
        for record in self:
            record._log_appointment_change(
                _("Service line removed: %s") % (record.service_name or record.service_id.display_name or "Unknown")
            )
        return super().unlink()

    def _log_appointment_change(self, body):
        if not body:
            return
        for record in self:
            if record.appointment_id:
                record.appointment_id.message_post(
                    body=Markup(f"<div class=\"o_mail_notification\"><p>{body}</p><hr/></div>"),
                    subtype_xmlid="mail.mt_note",
                )

    def _get_chatter_tracked_fields(self, vals):
        skip = {
            'message_follower_ids', 'message_partner_ids', 'message_ids',
            'activity_ids', 'activity_exception_decoration', 'activity_state',
            'activity_type_icon', 'activity_type_id', 'activity_user_id',
            'display_name',
        }
        return [name for name in vals.keys() if name in self._fields and name not in skip]

    def _log_field_changes(self, vals, prefix, old_values=None):
        old_values = old_values or {}
        for name in self._get_chatter_tracked_fields(vals):
            field = self._fields.get(name)
            if not field:
                continue
            old = old_values.get(name, False)
            new = self[name]

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

            field_label = field.string or name
            old_disp = self._format_field_value(field, old)
            new_disp = self._format_field_value(field, new)
            body = _("%s: %s: %s -> %s") % (prefix, field_label, old_disp, new_disp)
            self._log_appointment_change(body)

    @staticmethod
    def _format_field_value(field, value):
        if field.type == 'many2one':
            return value.display_name if value else "None"
        if field.type in ('many2many', 'one2many'):
            return ", ".join(value.mapped('display_name')) if value else "None"
        if field.type == 'float' and ('duration' in (field.name or '') or 'Duration' in (field.string or '')):
            return SalonAppointmentService._format_duration_hours(value)
        if field.type == 'selection':
            if value in (False, None, ''):
                return "None"
            selection = dict(field.selection)
            return selection.get(value, value)
        if field.type == 'boolean':
            return "Yes" if value else "No"
        if field.type in ('date', 'datetime'):
            if not value:
                return "None"
            return fields.Date.to_string(value) if field.type == 'date' else fields.Datetime.to_string(value)
        return str(value) if value not in (False, None, '') else "None"

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
