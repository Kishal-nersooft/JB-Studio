from odoo import models, fields, api


class ResPartner(models.Model):
    _inherit = 'res.partner'

    is_vip = fields.Boolean(string='VIP')
    # Every service flagged as a VIP Service, shown on VIP contacts so staff can
    # see what this customer gets free. Computed rather than assigned: turning
    # the flag on or off on a service updates every VIP contact at once, and
    # there is no per-customer list to maintain or fall out of step.
    vip_free_service_ids = fields.Many2many(
        'product.product',
        string='VIP Free Services',
        compute='_compute_vip_free_service_ids',
    )

    @api.depends('is_vip')
    def _compute_vip_free_service_ids(self):
        Product = self.env['product.product']
        vip_services = Product.search([
            ('is_vip_service', '=', True),
            ('is_appointment_service', '=', True),
        ]) if any(self.mapped('is_vip')) else Product
        for partner in self:
            partner.vip_free_service_ids = vip_services if partner.is_vip else Product
    deposit_ids = fields.One2many(
        'beauty.customer.deposit',
        'partner_id',
        string='Deposits',
    )
    credit_redemption_ids = fields.One2many(
        'beauty.credit.redemption',
        'partner_id',
        string='Credit Redemptions',
    )
    account_credit_balance = fields.Monetary(
        string='Account Credit Balance',
        compute='_compute_account_credit_balance',
        store=True,
        currency_field='currency_id',
        depends=['deposit_ids.credit_amount', 'credit_redemption_ids.amount'],
    )

    appointment_count = fields.Integer(
        string='Appointments',
        compute='_compute_appointment_count',
    )
    bb_rewards_count = fields.Integer(
        string='Rewards',
        compute='_compute_bb_loyalty_counts',
    )
    bb_gift_voucher_count = fields.Integer(
        string='Gift Vouchers',
        compute='_compute_bb_loyalty_counts',
    )

    # The customer's own bookings, so the activity fields below can depend on
    # them and be brought up to date when a booking changes.
    salon_appointment_ids = fields.One2many(
        'salon.appointment', 'customer_id', string='Salon Appointments',
    )
    # Blocked is recorded here rather than worked out: it is a decision someone
    # makes about a customer, not something the bookings can tell us.
    is_blocked = fields.Boolean(
        string='Blocked',
        help='Stop this customer from making further bookings.',
    )
    client_status = fields.Selection(
        [('blocked', 'Blocked'), ('vip', 'VIP'), ('active', 'Active')],
        string='Client Status', compute='_compute_client_status', store=True,
        help='Blocked takes precedence over VIP, since a blocked customer '
             'should not read as a favoured one.',
    )
    # Bookings the customer made themselves online, as opposed to every
    # appointment on their record however it was taken.
    online_booking_count = fields.Integer(
        string='# of Bookings', compute='_compute_appointment_activity', store=True,
    )
    weeks_absent = fields.Integer(
        string='Weeks Absent', compute='_compute_appointment_activity', store=True,
        help='Whole weeks since this customer was last in.',
    )
    last_appointment_date = fields.Date(
        string='Last Appt. Date', compute='_compute_appointment_activity', store=True,
    )
    last_appointment_service = fields.Char(
        string='Last Appt. Service', compute='_compute_appointment_activity', store=True,
    )
    last_appointment_staff = fields.Char(
        string='Last Appt. Staff', compute='_compute_appointment_activity', store=True,
    )
    last_appointment_status = fields.Char(
        string='Last Appt. Status', compute='_compute_appointment_activity', store=True,
    )
    last_appointment_channel = fields.Char(
        string='Last Appt. Booked Via', compute='_compute_appointment_activity', store=True,
    )
    next_appointment_date = fields.Date(
        string='Next Appt. Date', compute='_compute_appointment_activity', store=True,
    )
    next_appointment_service = fields.Char(
        string='Next Appt. Service', compute='_compute_appointment_activity', store=True,
    )
    next_appointment_staff = fields.Char(
        string='Next Appt. Staff', compute='_compute_appointment_activity', store=True,
    )
    next_appointment_status = fields.Char(
        string='Next Appt. Status', compute='_compute_appointment_activity', store=True,
    )
    next_appointment_channel = fields.Char(
        string='Next Appt. Booked Via', compute='_compute_appointment_activity', store=True,
    )

    @api.depends('is_vip', 'is_blocked')
    def _compute_client_status(self):
        for partner in self:
            partner.client_status = (
                'blocked' if partner.is_blocked
                else 'vip' if partner.is_vip
                else 'active'
            )

    @api.depends(
        'salon_appointment_ids.appointment_date',
        'salon_appointment_ids.state',
        'salon_appointment_ids.appointment_type',
        'salon_appointment_ids.service_line_ids',
    )
    def _compute_appointment_activity(self):
        """The customer's last and next visit, read in one pass.

        There are tens of thousands of contacts, so this is answered with a
        single query for the whole set rather than a search per contact --
        opening the contact list would otherwise run one query per row.
        """
        blank = {
            'online_booking_count': 0, 'weeks_absent': 0,
            'last_appointment_date': False, 'last_appointment_service': False,
            'last_appointment_staff': False, 'last_appointment_status': False,
            'last_appointment_channel': False,
            'next_appointment_date': False, 'next_appointment_service': False,
            'next_appointment_staff': False, 'next_appointment_status': False,
            'next_appointment_channel': False,
        }
        for partner in self:
            partner.update(blank)
        partners = self.filtered('id')
        if not partners:
            return

        today = fields.Date.context_today(self)
        statuses = dict(self.env['salon.appointment']._fields['state'].selection)
        channels = dict(self.env['salon.appointment']._fields['appointment_type'].selection)
        self.env.cr.execute("""
            WITH ranked AS (
                SELECT sa.customer_id,
                       sa.appointment_date,
                       sa.state,
                       sa.appointment_type,
                       -- The visit itself is the booking; the service shown is
                       -- the first one on it, which is what the salon reads.
                       (SELECT COALESCE(line.service_name, '')
                          FROM salon_appointment_service line
                         WHERE line.appointment_id = sa.id
                         ORDER BY line.start_hour, line.id LIMIT 1) AS service,
                       (SELECT COALESCE(he.name, '')
                          FROM salon_appointment_service line
                          LEFT JOIN hr_employee he ON he.id = line.beautician_id
                         WHERE line.appointment_id = sa.id
                         ORDER BY line.start_hour, line.id LIMIT 1) AS staff,
                       ROW_NUMBER() OVER (
                           PARTITION BY sa.customer_id
                           ORDER BY sa.appointment_date DESC, sa.id DESC
                       ) AS newest_past,
                       ROW_NUMBER() OVER (
                           PARTITION BY sa.customer_id
                           ORDER BY sa.appointment_date ASC, sa.id ASC
                       ) AS soonest_future,
                       sa.appointment_date <= %(today)s AS in_the_past
                  FROM salon_appointment sa
                 WHERE sa.customer_id IN %(partner_ids)s
                   AND sa.state <> 'cancelled'
            )
            SELECT customer_id,
                   MAX(appointment_date) FILTER (WHERE in_the_past) AS last_date,
                   MIN(appointment_date) FILTER (WHERE NOT in_the_past) AS next_date,
                   COUNT(*) FILTER (WHERE appointment_type = 'online') AS online_bookings
              FROM ranked
             GROUP BY customer_id
        """, {'partner_ids': tuple(partners.ids), 'today': today})
        summary = {row[0]: row for row in self.env.cr.fetchall()}

        # The detail of those two visits, read back for the ones that exist.
        wanted = [
            (partner_id, row[1], 'last') for partner_id, row in summary.items() if row[1]
        ] + [
            (partner_id, row[2], 'next') for partner_id, row in summary.items() if row[2]
        ]
        detail = {}
        if wanted:
            self.env.cr.execute("""
                SELECT sa.customer_id, sa.appointment_date, sa.state, sa.appointment_type,
                       (SELECT COALESCE(line.service_name, '')
                          FROM salon_appointment_service line
                         WHERE line.appointment_id = sa.id
                         ORDER BY line.start_hour, line.id LIMIT 1) AS service,
                       (SELECT COALESCE(he.name, '')
                          FROM salon_appointment_service line
                          LEFT JOIN hr_employee he ON he.id = line.beautician_id
                         WHERE line.appointment_id = sa.id
                         ORDER BY line.start_hour, line.id LIMIT 1) AS staff
                  FROM salon_appointment sa
                 WHERE (sa.customer_id, sa.appointment_date) IN %(pairs)s
                   AND sa.state <> 'cancelled'
                 ORDER BY sa.id DESC
            """, {'pairs': tuple((pid, date) for pid, date, _which in wanted)})
            for row in self.env.cr.fetchall():
                detail[(row[0], row[1])] = row

        for partner in partners:
            row = summary.get(partner.id)
            if not row:
                continue
            _customer_id, last_date, next_date, online_bookings = row
            partner.online_booking_count = online_bookings or 0
            if last_date:
                partner.last_appointment_date = last_date
                partner.weeks_absent = max(0, (today - last_date).days // 7)
                found = detail.get((partner.id, last_date))
                if found:
                    partner.last_appointment_status = statuses.get(found[2], found[2])
                    partner.last_appointment_channel = channels.get(found[3], found[3])
                    partner.last_appointment_service = found[4] or False
                    partner.last_appointment_staff = found[5] or False
            if next_date:
                partner.next_appointment_date = next_date
                found = detail.get((partner.id, next_date))
                if found:
                    partner.next_appointment_status = statuses.get(found[2], found[2])
                    partner.next_appointment_channel = channels.get(found[3], found[3])
                    partner.next_appointment_service = found[4] or False
                    partner.next_appointment_staff = found[5] or False

    @api.depends('deposit_ids.credit_amount', 'credit_redemption_ids.amount', 'credit_redemption_ids.movement_type')
    def _compute_account_credit_balance(self):
        for partner in self:
            total_deposit_credit = sum(partner.deposit_ids.mapped('credit_amount'))
            total_issued_credit = sum(
                partner.credit_redemption_ids.filtered(lambda line: line.movement_type == 'credit').mapped('amount')
            )
            total_redeemed = sum(
                partner.credit_redemption_ids.filtered(lambda line: line.movement_type != 'credit').mapped('amount')
            )
            partner.account_credit_balance = max(0.0, total_deposit_credit + total_issued_credit - total_redeemed)

    def _compute_appointment_count(self):
        Appointment = self.env['salon.appointment']
        for partner in self:
            partner.appointment_count = Appointment.search_count([
                ('customer_id', '=', partner.id),
            ])

    def _compute_bb_loyalty_counts(self):
        reward_types = ('loyalty', 'coupons', 'promotion', 'discount_card')
        voucher_types = ('gift_card', 'ewallet')
        reward_groups = self.env['loyalty.card']._read_group(
            [('partner_id', 'in', self.ids), ('program_id.program_type', 'in', reward_types)],
            groupby=['partner_id'],
            aggregates=['__count'],
        )
        voucher_groups = self.env['loyalty.card']._read_group(
            [('partner_id', 'in', self.ids), ('program_id.program_type', 'in', voucher_types)],
            groupby=['partner_id'],
            aggregates=['__count'],
        )
        reward_map = {partner.id: count for partner, count in reward_groups}
        voucher_map = {partner.id: count for partner, count in voucher_groups}
        for partner in self:
            partner.bb_rewards_count = reward_map.get(partner.id, 0)
            partner.bb_gift_voucher_count = voucher_map.get(partner.id, 0)

    def action_open_appointments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Appointments',
            'res_model': 'salon.appointment',
            'view_mode': 'list,form',
            'domain': [('customer_id', '=', self.id)],
            'context': {'default_customer_id': self.id},
        }

    def action_open_rewards(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('loyalty.loyalty_card_action')
        action['domain'] = [
            ('partner_id', '=', self.id),
            ('program_id.program_type', 'in', ('loyalty', 'coupons', 'promotion', 'discount_card')),
        ]
        action['context'] = {'default_partner_id': self.id}
        action['display_name'] = 'Rewards'
        return action

    def action_open_gift_vouchers(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('loyalty.loyalty_card_action')
        action['domain'] = [
            ('partner_id', '=', self.id),
            ('program_id.program_type', 'in', ('gift_card', 'ewallet')),
        ]
        action['context'] = {'default_partner_id': self.id}
        action['display_name'] = 'Gift Vouchers'
        return action

    def action_open_issue_credit_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Issue Credit',
            'res_model': 'beauty.issue.credit.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_partner_id': self.id,
            },
        }
