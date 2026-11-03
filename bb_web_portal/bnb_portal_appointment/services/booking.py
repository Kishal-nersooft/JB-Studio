"""Request-free booking calculations and availability checks."""
import re
import logging
from datetime import datetime
from odoo import fields
_logger = logging.getLogger(__name__)

def _safe_int(value):
    try:
        return int(value)
    except Exception:
        if value is None:
            return None
        match = re.match(r'\d+', str(value))
        return int(match.group(0)) if match else None

def _get_start_hour_from_timeslots(selected_timeslots, default_start):
    if not selected_timeslots:
        return default_start
    for _, timeslot_info in selected_timeslots.items():
        if isinstance(timeslot_info, dict) and 'start_hour' in timeslot_info:
            try:
                return float(timeslot_info['start_hour'])
            except (TypeError, ValueError) as error:
                _logger.warning(
                    "Skipping invalid portal booking start_hour %r: %s",
                    timeslot_info.get('start_hour'), error,
                )
                continue
    return default_start

def _compute_reward_discount(reward, total_amount):
    discount = 0.0
    if reward.discount_mode == 'percent':
        discount = total_amount * (reward.discount / 100.0)
    elif reward.discount_mode == 'per_order':
        discount = reward.discount
    else:
        return 0.0

    if reward.discount_max_amount and reward.discount_max_amount > 0:
        discount = min(discount, reward.discount_max_amount)
    return max(discount, 0.0)

def _program_unavailable_reason(program):
    """Return why this loyalty program cannot be used today, or None.

    The program's validity dates and its total usage cap are set by staff in
    Odoo, but nothing here used to read them: an expired promotion kept
    granting its discount online for as long as the program stayed active.
    Measured on bb_test_uat -- "10% PROMO CODE" ended 2026-03-31 and was still
    taking 10% off a booking five months later. Odoo enforces both limits on
    its own orders, so honouring them here keeps online booking consistent
    with the rest of the system rather than inventing a second rule.
    """
    today = fields.Date.context_today(program)
    if program.date_from and today < program.date_from:
        return "This code is not active yet"
    if program.date_to and today > program.date_to:
        return "This code has expired"
    if program.limit_usage and program.total_order_count >= program.max_usage:
        return "This code has reached its usage limit"
    return None

def _compute_discount_from_code(env, promo_code, total_amount, branch=None):
    code = (promo_code or '').strip()
    if not code:
        return 0.0, "Please enter a gift/discount code"

    company = branch.company_id if branch else env.company
    currency = company.currency_id

    rule = env['loyalty.rule'].sudo().search([
        ('mode', '=', 'with_code'),
        ('code', '=ilike', code),
        ('active', '=', True),
        ('program_id.active', '=', True),
        ('program_id.company_id', 'in', [company.id, False]),
    ], limit=1)

    if rule:
        unavailable = _program_unavailable_reason(rule.program_id)
        if unavailable:
            return 0.0, unavailable
        if rule.minimum_amount:
            min_amount = rule._compute_amount(currency)
            if total_amount < min_amount:
                return 0.0, "Minimum amount not reached for this code"
        reward = rule.program_id.reward_ids.filtered(
            lambda r: r.active and r.reward_type == 'discount' and r.discount_applicability == 'order'
        )[:1]
        if not reward:
            return 0.0, "Code not applicable to this booking"
        discount = _compute_reward_discount(reward, total_amount)
        return min(discount, total_amount), None

    card = env['loyalty.card'].sudo().search([
        ('code', '=ilike', code),
        ('active', '=', True),
        '|',
        ('program_id.company_id', '=', False),
        ('program_id.company_id', '=', company.id),
    ], limit=1)
    if card and card.program_id.active and card.program_id.company_id in (False, company):
        unavailable = _program_unavailable_reason(card.program_id)
        if unavailable:
            return 0.0, unavailable
        if card.expiration_date and card.expiration_date < fields.Date.today():
            return 0.0, "This code has expired"
        if card.program_type in ('ewallet', 'gift_card') and card.points > 0:
            return min(card.points, total_amount), None
        reward = card.program_id.reward_ids.filtered(
            lambda r: r.active and r.reward_type == 'discount' and r.discount_applicability == 'order'
        )[:1]
        if reward:
            discount = _compute_reward_discount(reward, total_amount)
            return min(discount, total_amount), None

    return 0.0, "Invalid gift/discount code"

def _pick_available_beautician(env, service, branch, appointment_date, start_hour, duration):
    """When the client picks 'Any Beautician', return the first qualified
    beautician (product template beautician-line order = index 0) who is
    actually free for this branch/date/slot, instead of leaving the service
    line unassigned (which used to land the appointment on the waiting list).
    Returns False if nobody on the line-up is free."""
    try:
        date_obj = datetime.strptime(appointment_date, '%Y-%m-%d').date()
    except Exception:
        return False

    allowed_company_id = branch.company_id.id if branch and branch.company_id else env.company.id
    end_hour = start_hour + duration

    lines = service.product_tmpl_id.beautician_line_ids.filtered(
        lambda l: l.beautician_id.is_beautician and l.beautician_id.company_id.id == allowed_company_id
    )

    for line in lines:
        beautician = line.beautician_id

        if branch:
            beautician_branch_ids = beautician.beautician_branch_ids.ids or (
                [beautician.branch_id.id] if beautician.branch_id else []
            )
            if beautician_branch_ids and branch.id not in beautician_branch_ids:
                continue

        leave = env['employee.timeoff.break'].sudo().search([
            ('employee_id', '=', beautician.id),
            ('state', '=', 'approved'),
            ('category', '=', 'timeoff'),
            ('start_date', '<=', date_obj),
            ('end_date', '>=', date_obj),
            ('company_id', '=', allowed_company_id),
        ], limit=1)
        if leave:
            continue

        existing = env['salon.appointment.service'].sudo().search([
            ('beautician_id', '=', beautician.id),
            ('appointment_id.appointment_date', '=', date_obj),
            ('appointment_id.state', '!=', 'cancelled'),
            ('appointment_id.company_id', '=', allowed_company_id),
        ])
        conflict = False
        for existing_booking in existing:
            if existing_booking.start_hour is not False and existing_booking.duration:
                booking_start = existing_booking.start_hour
                booking_end = booking_start + existing_booking.duration
                if start_hour < booking_end and end_hour > booking_start:
                    conflict = True
                    break
        if conflict:
            continue

        return beautician.id

    return False

def _format_hour_label(hour_value):
    try:
        total_minutes = int(round(float(hour_value or 0.0) * 60))
    except (TypeError, ValueError):
        total_minutes = 0
    hours = (total_minutes // 60) % 24
    minutes = total_minutes % 60
    suffix = 'AM' if hours < 12 else 'PM'
    display_hours = hours % 12 or 12
    return f"{display_hours}:{minutes:02d} {suffix}"

def _get_service_resource_ids(service, branch):
    """Return equipment IDs required by a service and valid for the branch.

    bnb_portal_appointment does not depend directly on bb_resource_management, so
    this helper is intentionally field-safe. If the resource module is not
    installed, no resource blocking is applied.
    """
    tmpl = service.product_tmpl_id if service else False
    if not tmpl or 'resource_ids' not in tmpl._fields:
        return []

    resources = tmpl.sudo().resource_ids
    if not resources:
        return []

    if branch and 'branch_ids' in resources._fields:
        resources = resources.filtered(
            lambda resource: not resource.branch_ids or branch.id in resource.branch_ids.ids
        )
    return resources.ids

def _has_resource_conflict(candidate_start, service_requirements, reservations):
    """Return whether a candidate booking overlaps a required resource.

    ``service_requirements`` contains ``(offset, duration, resource_ids)`` and
    ``reservations`` contains ``(start, end, resource_ids)``. Keeping this
    calculation independent from the ORM makes the calendar and final booking
    checks use the same interval semantics.
    """
    for offset, duration, resource_ids in service_requirements:
        if not resource_ids:
            continue
        service_start = candidate_start + offset
        service_end = service_start + duration
        for reserved_start, reserved_end, reserved_resource_ids in reservations:
            if (
                resource_ids.intersection(reserved_resource_ids)
                and service_start < reserved_end
                and service_end > reserved_start
            ):
                return True
    return False

def _get_unavailable_resource_start_hours(env, appointment_date, branch, services):
    """Return 15-minute calendar starts blocked by existing resource use."""
    appointment_service_model = env['salon.appointment.service'].sudo()
    if 'resource_ids' not in appointment_service_model._fields:
        return []

    try:
        date_obj = datetime.strptime(appointment_date, '%Y-%m-%d').date()
    except Exception:
        return []

    service_requirements = []
    required_resource_ids = set()
    offset = 0.0
    for service in services:
        duration = float(getattr(service, 'duration', 1.0) or 1.0)
        resource_ids = set(_get_service_resource_ids(service, branch))
        service_requirements.append((offset, duration, resource_ids))
        required_resource_ids.update(resource_ids)
        offset += duration

    if not required_resource_ids:
        return []

    allowed_company_id = branch.company_id.id if branch and branch.company_id else env.company.id
    conflicting_lines = appointment_service_model.search([
        ('appointment_id.appointment_date', '=', date_obj),
        ('appointment_id.state', 'in', ['draft', 'confirmed', 'in_progress']),
        ('appointment_id.company_id', '=', allowed_company_id),
        ('resource_ids', 'in', list(required_resource_ids)),
    ])
    reservations = []
    for line in conflicting_lines:
        reserved_start = float(line.start_hour or 0.0)
        reserved_end = float(line.end_hour or (reserved_start + (line.duration or 0.0)))
        if reserved_end <= reserved_start:
            continue
        reservations.append((reserved_start, reserved_end, set(line.resource_ids.ids)))

    if not reservations:
        return []

    work_start = float(branch.work_start_hour or 9.0)
    work_end = float(branch.work_end_hour or 18.0)
    slot_count = max(0, int(round((work_end - work_start) / 0.25))) + 1
    candidates = [round(work_start + (index * 0.25), 2) for index in range(slot_count)]
    return [
        candidate
        for candidate in candidates
        if _has_resource_conflict(candidate, service_requirements, reservations)
    ]

def _validate_booking_resource_availability(env, appointment_date, branch, services, start_hour):
    """Block online bookings that would double-book required equipment.

    POS already has a resource-conflict pre-check. Online booking previously
    only checked beautician overlap, so two customers could book different
    services at the same time while both required the same equipment/resource.
    """
    appointment_service_model = env['salon.appointment.service'].sudo()
    if 'resource_ids' not in appointment_service_model._fields:
        return True, None

    try:
        date_obj = datetime.strptime(appointment_date, '%Y-%m-%d').date()
    except Exception:
        return False, 'Invalid appointment date'

    allowed_company_id = branch.company_id.id if branch and branch.company_id else env.company.id
    current = start_hour

    for service in services:
        duration = getattr(service, 'duration', 1.0) or 1.0
        end = current + duration
        resource_ids = _get_service_resource_ids(service, branch)
        if resource_ids:
            conflicting_lines = appointment_service_model.search([
                ('appointment_id.appointment_date', '=', date_obj),
                ('appointment_id.state', 'in', ['draft', 'confirmed', 'in_progress']),
                ('appointment_id.company_id', '=', allowed_company_id),
                ('resource_ids', 'in', resource_ids),
                ('start_hour', '<', end),
                ('end_hour', '>', current),
            ], limit=1)
            if conflicting_lines:
                resource_name = conflicting_lines.resource_ids.filtered(
                    lambda resource: resource.id in resource_ids
                )[:1].display_name or 'required resource'
                return False, (
                    f"{service.display_name} cannot be booked at {_format_hour_label(current)} "
                    f"because {resource_name} is already booked. "
                    "Please choose another time, date, or service."
                )
        current = end

    return True, None

def _validate_booking_availability(env, appointment_date, branch, services, selected_beauticians, start_hour):
    try:
        date_obj = datetime.strptime(appointment_date, '%Y-%m-%d').date()
    except Exception:
        return False, 'Invalid appointment date'

    work_start = branch.work_start_hour or 9.0
    work_end = branch.work_end_hour or 18.0
    allowed_company_id = branch.company_id.id if branch and branch.company_id else env.company.id
    current = start_hour

    if current < work_start or current >= work_end:
        return False, 'Selected time is outside branch working hours'

    for service in services:
        duration = getattr(service, 'duration', 1.0)
        end = current + duration
        if end > work_end:
            return False, 'Selected services exceed branch working hours'

        beautician_id = selected_beauticians.get(str(service.id))
        if beautician_id and beautician_id != 'any':
            try:
                b_id = int(beautician_id)
            except (TypeError, ValueError):
                return False, 'Invalid beautician selection'

            leave = env['employee.timeoff.break'].sudo().search([
                ('employee_id', '=', b_id),
                ('state', '=', 'approved'),
                ('category', '=', 'timeoff'),
                ('start_date', '<=', date_obj),
                ('end_date', '>=', date_obj),
                ('company_id', '=', allowed_company_id),
            ], limit=1)
            if leave:
                return False, 'Selected professional is on leave for this date'

            existing = env['salon.appointment.service'].sudo().search([
                ('beautician_id', '=', b_id),
                ('appointment_id.appointment_date', '=', date_obj),
                ('appointment_id.state', '!=', 'cancelled'),
                ('appointment_id.company_id', '=', allowed_company_id),
            ])
            for booking in existing:
                if booking.start_hour is not False and booking.duration:
                    booking_start = booking.start_hour
                    booking_end = booking_start + booking.duration
                    if current < booking_end and end > booking_start:
                        return False, 'Selected professional is not available at that time'

        current = end

    return True, None
