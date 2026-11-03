from email.policy import default

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    @api.model
    def _party_duration_selection(self):
        return [(str(i), f"{i} min") for i in range(0, 241, 5)]

    # -------------------------
    # Beauticians
    # -------------------------
    beautician_line_ids = fields.One2many(
        'product.beautician.line',
        'product_tmpl_id',
        string="Beauticians"
    )

    # -------------------------
    # Service Duration
    # -------------------------
    duration = fields.Float(string="Duration")
    service_duration_display = fields.Char(
        string="Duration Display",
        compute="_compute_service_duration_display",
        store=False
    )

    # -------------------------
    # Branches & Related Services
    # -------------------------
    branch_ids = fields.Many2many(
        'beauty.branch',
        string='Branches',
        domain=[('company_id', '!=', False)]
    )
    related_product_ids = fields.Many2many(
        'product.template',
        'product_template_related_product_rel',
        'product_tmpl_id',
        'related_product_tmpl_id',
        string="Services",
        domain="[('sale_ok', '=', True), ('type', '=', 'service'), ('id', '!=', id)]"
    )

    is_resource_product = fields.Boolean(string="Requires Equipment")

    is_deposit_product = fields.Boolean(string="Deposit", default=False)
    is_credit_product = fields.Boolean(string="Credit Balance", default=False)
    is_issue_credit_product = fields.Boolean(
        string="Issue Credit",
        default=False,
        help="When this product is clicked in POS, open the Issue Credit wizard "
             "instead of adding it to the order.",
    )
    bb_surcharge_day = fields.Selection(
        selection=[
            ('saturday', 'Saturday'),
            ('sunday', 'Sunday'),
            ('both', 'Saturday and Sunday'),
        ],
        string="Weekend Surcharge Product",
        help="Marks this product as the one used for the weekend surcharge "
             "line on an order. The surcharge is charged on its own line "
             "instead of being added into the price of each service, so the "
             "customer can see what it is.\n\n"
             "Use a separate product for Saturday and for Sunday to keep the "
             "two rates apart on the receipt and in reporting, or one product "
             "set to 'Saturday and Sunday' if that split is not wanted.\n\n"
             "Set it up as a service. The surcharge used to sit inside the "
             "price of the services it applied to and so counted as service "
             "revenue; a storable product here would move that money into "
             "product sales in the reports instead.",
    )
    is_appointment_service = fields.Boolean(
        string="Bookable",
        help="Enable to make this service available for web and POS booking."
    )
    # A VIP service is free for every VIP customer. Held on the service rather
    # than assigned per customer, so switching it on or off applies everywhere
    # at once and no one has to maintain a list per contact.
    is_vip_service = fields.Boolean(
        string='VIP Service',
        help='Free of charge for any customer flagged as VIP.',
    )
    store_only = fields.Boolean(
        string="In-Store Only",
        help="Enable to make this service available only in-store."
    )
    is_video_call_service = fields.Boolean(
        string="Video Call Service",
        help="Enable to mark this service as available via video call."
    )

    # -------------------------
    # Booking Questions
    # -------------------------
    booking_question_display = fields.Selection([
        ('not_required', 'Not Required'),
        ('online_and_calendar', 'Online and via Calendar'),
        ('online_only', 'Online Only'),
        ('calendar_only', 'Calendar Only'),
    ], string='Show Questions On', default='not_required')
    important_notice = fields.Text(
        string='Important Notice',
        help="Important notice shown alongside this service's booking questions on the appointment."
    )
    booking_question_ids = fields.One2many(
        'product.booking.question',
        'product_tmpl_id',
        string='Booking Questions'
    )

    is_party_product = fields.Boolean(
        string="Party Service",
        help="Enable to add preparation and wrap-up sections to appointment tiles."
    )
    party_prep_minutes = fields.Selection(
        selection=_party_duration_selection,
        string="Preparation (min)",
        default='0'
    )
    party_prep_color = fields.Char(
        string="Preparation Color",
        default="#FFD59A"
    )
    party_wrap_minutes = fields.Selection(
        selection=_party_duration_selection,
        string="Wrap-up/Cleanup (min)",
        default='0'
    )
    party_wrap_color = fields.Char(
        string="Wrap-up Color",
        default="#CDEFE3"
    )

    # -------------------------
    # Payment Policy (per-service deposit)
    # -------------------------
    payment_policy = fields.Selection([
        ('none', 'None'),
        ('do_not_accept', 'Do not accept online payment'),
        ('full_payment', 'Require full payment'),
        ('deposit_percentage', 'Require a deposit (percentage)'),
        ('deposit_fixed', 'Require a deposit (fixed amount)'),
    ], string='Payment Policy', default='none')
    deposit_percentage_value = fields.Float(
        string='Deposit Percentage (%)',
        digits=(5, 2),
    )
    deposit_fixed_amount = fields.Float(
        string='Deposit Fixed Amount',
        digits='Account',
    )

    # -------------------------
    # Service Consumptions (Kit)
    # -------------------------
    consumption_line_ids = fields.One2many(
        'product.service.consumption.line',
        'product_tmpl_id',
        string="Consumptions"
    )

    # -------------------------
    # COMPUTE METHODS
    # -------------------------
    @api.depends('duration')
    def _compute_service_duration_display(self):
        """Convert float duration to readable string, e.g., 1.5 -> '1h 30m'"""
        for record in self:
            if record.duration:
                hours = int(record.duration)
                minutes = round((record.duration - hours) * 60)

                if hours and minutes:
                    record.service_duration_display = f"{hours}h {minutes}m"
                elif hours:
                    record.service_duration_display = f"{hours}h"
                elif minutes:
                    record.service_duration_display = f"{minutes}m"
                else:
                    record.service_duration_display = "N/A"
            else:
                record.service_duration_display = "N/A"

    @api.onchange('branch_ids')
    def _onchange_branch_ids(self):
        """Remove beautician lines if their branches are removed and update domain"""
        current_branch_ids = self.branch_ids.ids if self.branch_ids else []

        # Remove beautician lines linked to removed branches
        if hasattr(self, '_origin') and self._origin.branch_ids:
            removed_branches = set(self._origin.branch_ids.ids) - set(current_branch_ids)
            if removed_branches and self.beautician_line_ids:
                lines_to_remove = [(2, line.id) for line in self.beautician_line_ids
                                   if line.beautician_id and (
                                       (line.beautician_id.branch_id and line.beautician_id.branch_id.id in removed_branches)
                                       or line.beautician_id.beautician_branch_ids.filtered(lambda b: b.id in removed_branches)
                                   )]
                if lines_to_remove:
                    self.beautician_line_ids = lines_to_remove

        # If no branches remain, remove all beautician lines
        if not current_branch_ids and self.beautician_line_ids:
            self.beautician_line_ids = [(5, 0, 0)]

        # Update domain for available beauticians
        if current_branch_ids:
            return {'domain': {'beautician_line_ids': {
                'beautician_id': [
                    ('is_beautician', '=', True),
                    '|',
                    ('branch_id', 'in', current_branch_ids),
                    ('beautician_branch_ids', 'in', current_branch_ids),
                ]
            }}}
        else:
            return {'domain': {'beautician_line_ids': {'beautician_id': [('id', '=', False)]}}}

    @api.onchange('is_appointment_service')
    def _onchange_is_appointment_service(self):
        if self.is_appointment_service:
            self.store_only = False

    @api.onchange('store_only')
    def _onchange_store_only(self):
        if self.store_only:
            self.is_appointment_service = False

    @api.constrains('is_appointment_service', 'store_only')
    def _check_service_channel_selection(self):
        for record in self:
            if record.is_appointment_service and record.store_only:
                raise ValidationError(
                    _("You can select either Appointment Service or Store Only, not both.")
                )

    def action_open_beautician_bulk_wizard(self):
        wizard = self.env['beautician.bulk.add.wizard'].create({
            'product_tmpl_id': self.id,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'beautician.bulk.add.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }


class ProductProduct(models.Model):
    """The same Add Multiple Beauticians button, reached from a variant form.

    product.product delegates its template's *fields* through _inherits but
    not its methods, so a button that works on the template form breaks the
    moment that same arch is reused in a variant view. website_sale does
    exactly that - its product.product form inherits the template form - and
    the server refused to load with "action_open_beautician_bulk_wizard is
    not a valid action on product.product".

    Handing it to the template keeps one implementation and makes the button
    work from either form.
    """

    _inherit = 'product.product'

    def action_open_beautician_bulk_wizard(self):
        self.ensure_one()
        return self.product_tmpl_id.action_open_beautician_bulk_wizard()


class ProductBookingQuestion(models.Model):
    _name = 'product.booking.question'
    _description = 'Product Booking Question'
    _order = 'sequence, id'

    product_tmpl_id = fields.Many2one(
        'product.template', string='Product', required=True, ondelete='cascade'
    )
    sequence = fields.Integer(string='Sequence', default=10)
    question_text = fields.Char(string='Question', required=True)


class ProductBeauticianLine(models.Model):
    _name = 'product.beautician.line'
    _description = 'Product Beautician Line'

    # -------------------------
    # Links
    # -------------------------
    product_tmpl_id = fields.Many2one('product.template', string="Product")
    beautician_id = fields.Many2one(
        'hr.employee',
        string="Beautician",
        domain="[('is_beautician', '=', True), '|', ('branch_id', 'in', parent.branch_ids), ('beautician_branch_ids', 'in', parent.branch_ids)]",
        required=True
    )

    # -------------------------
    # Pricing
    # -------------------------
    price = fields.Float(string="Price", required=True)
    duration = fields.Float(string="Duration (Hours)")

    # -------------------------
    # ONCHANGE METHODS
    # -------------------------
    @api.onchange('product_tmpl_id')
    def _onchange_product_tmpl_id(self):
        """Clear beautician when the product template changes"""
        if self.product_tmpl_id:
            self.beautician_id = False


class ProductServiceConsumptionLine(models.Model):
    _name = 'product.service.consumption.line'
    _description = 'Product Service Consumption Line'

    product_tmpl_id = fields.Many2one(
        'product.template',
        string="Service",
        required=True,
        ondelete='cascade'
    )
    product_id = fields.Many2one(
        'product.product',
        string="Consumption Product",
        required=True,
        domain="[('type', 'in', ['product', 'consu'])]"
    )
    uom_reference_id = fields.Many2one(
        'uom.uom',
        string="UoM Reference",
        compute="_compute_uom_reference_id"
    )
    uom_id = fields.Many2one(
        'uom.uom',
        string="UoM",
        required=True,
        domain="['|', ('id', '=', uom_reference_id), ('relative_uom_id', '=', uom_reference_id)]"
    )
    quantity = fields.Float(string="Quantity", default=1.0)

    @api.depends('product_id', 'product_id.uom_id', 'product_id.uom_id.relative_uom_id')
    def _compute_uom_reference_id(self):
        for line in self:
            uom = line.product_id.uom_id
            line.uom_reference_id = uom.relative_uom_id or uom if uom else False

    @api.onchange('product_id')
    def _onchange_product_id(self):
        for line in self:
            if line.product_id:
                line.uom_id = line.product_id.uom_id
