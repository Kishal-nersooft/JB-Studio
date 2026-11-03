# -*- coding: utf-8 -*-
import base64
import json
import logging
from datetime import datetime

from odoo.http import request, route
from odoo.addons.portal.controllers import portal

from .booking_helpers import (
    _safe_int,
    _validate_booking_resource_availability,
)

_logger = logging.getLogger(__name__)


class BeauticianController(portal.CustomerPortal):
    @staticmethod
    def _allowed_company_ids():
        return request.env.companies.ids or [request.env.company.id]

    @route('/salon/get-beauticians', type='http', auth="public", methods=['POST'])
    def get_beauticians(self, service_ids=None, branch_ids=None, **kw):
        service_ids = self._safe_json(service_ids, [])
        branch_ids = self._safe_json(branch_ids, [])

        if not service_ids:
            return self._json_response({'services': []})

        products = request.env['product.product'].sudo().search([
            ('id', 'in', service_ids),
            ('type', '=', 'service'),
            ('active', '=', True),
            '|',
            ('product_tmpl_id.company_id', '=', False),
            ('product_tmpl_id.company_id', 'in', self._allowed_company_ids()),
        ])
        if branch_ids:
            branches = request.env['beauty.branch'].sudo().search([
                ('id', 'in', branch_ids),
                ('company_id', 'in', self._allowed_company_ids()),
                ('active', '=', True),
            ])
            company_ids = branches.mapped('company_id').ids
            products = products.filtered(lambda p: (
                p.type == 'service'
                and getattr(p.product_tmpl_id, 'is_appointment_service', False)
                and any(b.id in p.product_tmpl_id.branch_ids.ids for b in branches)
                and (not p.product_tmpl_id.company_id or p.product_tmpl_id.company_id.id in company_ids)
            ))
        currency = (
            branches[:1].company_id.currency_id
            if branch_ids and branches
            else request.env.company.currency_id
        )
        services = []

        for product in products:
            beauticians = []
            for line in product.product_tmpl_id.beautician_line_ids:
                beautician = line.beautician_id
                if not beautician.is_beautician:
                    continue

                if branch_ids:
                    beautician_branch_ids = beautician.beautician_branch_ids.ids if beautician.beautician_branch_ids else []
                    if not beautician_branch_ids and beautician.branch_id:
                        beautician_branch_ids = [beautician.branch_id.id]
                    if not any(branch_id in beautician_branch_ids for branch_id in branch_ids):
                        continue

                beauticians.append({
                    'id': beautician.id,
                    'name': beautician.name,
                    'image': f'/web/image/hr.employee/{beautician.id}/image_128',
                    'price': currency.format(line.price),
                    'raw_price': line.price,
                    'branch_id': beautician.branch_id.id if beautician.branch_id else False
                })

            if beauticians:
                services.append({
                    'id': product.id,
                    'name': product.name,
                    'duration': getattr(product, 'service_duration_display', '1h'),
                    'beauticians': beauticians
                })

        return self._json_response({'services': services})

    @route('/salon/get-available-slots', type='http', auth="public", methods=['POST'])
    def get_available_slots(self, appointment_date=None, beautician_ids=None, service_durations=None, **kw):
        beautician_ids = self._safe_json(beautician_ids, [])
        durations = self._safe_json(service_durations, {})

        if not all([appointment_date, beautician_ids]):
            return self._json_response({'slots': {}})

        date = datetime.strptime(appointment_date, '%Y-%m-%d').date()
        slots = {}
        allowed_company_ids = self._allowed_company_ids()

        for b_id in beautician_ids:
            duration = float(durations.get(str(b_id), 1.0))

            # Check if beautician is on leave for this date
            leave = request.env['employee.timeoff.break'].sudo().search([
                ('employee_id', '=', b_id),
                ('state', '=', 'approved'),
                ('category', '=', 'timeoff'),
                ('start_date', '<=', date),
                ('end_date', '>=', date),
                ('company_id', 'in', allowed_company_ids),
            ], limit=1)
            if leave:
                slots[str(b_id)] = []  # No slots available — on leave
                continue

            # Get blocked slots
            blocked = request.env['salon.appointment.service'].sudo().search([
                ('beautician_id', '=', b_id),
                ('appointment_id.appointment_date', '=', date),
                ('appointment_id.state', '!=', 'cancelled'),
                ('appointment_id.company_id', 'in', allowed_company_ids),
            ])

            blocked_times = [(s.start_hour, s.start_hour + s.duration) for s in blocked if s.start_hour]

            # Get branch hours
            beautician = request.env['hr.employee'].sudo().search([
                ('id', '=', b_id),
                ('company_id', 'in', self._allowed_company_ids()),
            ], limit=1)
            branch = beautician.branch_id
            start_hour = getattr(branch, 'work_start_hour', 9.0)
            end_hour = getattr(branch, 'work_end_hour', 18.0)

            # Generate slots
            available = []
            current = start_hour

            while current + duration <= end_hour:
                # Check if slot conflicts with blocked times
                is_free = all(not (current < end and current + duration > start)
                              for start, end in blocked_times)

                if is_free:
                    available.append({
                        'start_hour': current,
                        'display': f"{self._format_hour(current)} - {self._format_hour(current + duration)}",
                        'period': 'morning' if current < 12 else 'evening'
                    })

                current += 0.5  # 30-minute intervals

            slots[str(b_id)] = available

        return self._json_response({'slots': slots})

    @route('/salon/get-beauticians-by-services', type='http', auth='public', methods=['GET'])
    def get_beauticians_by_services(self, **kwargs):
        try:
            branch_id = _safe_int(kwargs.get('branch_id', 0))
            service_ids = kwargs.get('service_ids', '').split(',')
            service_ids = [int(sid) for sid in service_ids if sid.strip().isdigit()]

            selected_date = kwargs.get('selected_date')
            selected_time = kwargs.get('selected_time')

            if not branch_id:
                return request.make_response(
                    json.dumps({'beauticians': [], 'message': 'No branch selected'}),
                    headers={'Content-Type': 'application/json'}
                )

            branch = request.env['beauty.branch'].sudo().search([
                ('id', '=', branch_id),
                ('company_id', 'in', self._allowed_company_ids()),
                ('active', '=', True),
            ], limit=1)
            if not branch:
                return request.make_response(
                    json.dumps({'beauticians': [], 'message': 'Invalid branch'}),
                    headers={'Content-Type': 'application/json'}
                )
            work_start = branch.work_start_hour or 9.0
            work_end = branch.work_end_hour or 18.0

            if not service_ids:
                beauticians = request.env['hr.employee'].sudo().search([
                    ('is_beautician', '=', True),
                    ('active', '=', True),
                    ('company_id', 'in', self._allowed_company_ids()),
                    '|',
                    ('branch_id', '=', branch_id),
                    ('beautician_branch_ids', 'in', [branch_id]),
                ])

                available_beauticians = []
                for beautician in beauticians:
                    image_url = None
                    if beautician.image_128:
                        try:
                            image_data = base64.b64decode(beautician.image_128)
                            image_b64 = base64.b64encode(image_data).decode('utf-8')
                            image_url = f'data:image/png;base64,{image_b64}'
                        except:
                            image_url = None

                    available_beauticians.append({
                        'id': beautician.id,
                        'name': beautician.name,
                        'price': "$0.00",
                        'image': image_url
                    })

                return request.make_response(
                    json.dumps({
                        'beauticians': available_beauticians,
                        'busy_beauticians': [],
                        'message': 'Select services to see availability',
                        'total_duration': 0,
                        'salon_hours': f"{self._format_hour(work_start)} - {self._format_hour(work_end)}",
                        'selected_time_hour': None,
                        'selected_time_end': None
                    }),
                    headers={'Content-Type': 'application/json'}
                )

            # Get service durations
            services = request.env['product.product'].sudo().search([
                ('id', 'in', service_ids),
                ('type', '=', 'service'),
                ('active', '=', True),
                '|',
                ('product_tmpl_id.company_id', '=', False),
                ('product_tmpl_id.company_id', '=', branch.company_id.id),
            ])
            total_duration = sum([getattr(s, 'duration', 1.0) for s in services])

            # Convert selected time to hour float
            selected_hour = None
            if selected_time:
                try:
                    time_parts = selected_time.split(':')
                    selected_hour = float(time_parts[0]) + float(time_parts[1]) / 60
                except:
                    selected_hour = None

            selected_date_obj = None
            if selected_date:
                try:
                    selected_date_obj = datetime.strptime(selected_date, '%Y-%m-%d').date()
                except (TypeError, ValueError):
                    selected_date_obj = None

            ordered_services = [
                services.filtered(lambda service: service.id == service_id)
                for service_id in service_ids
            ]
            any_professional_available = True
            waiting_list_available = False
            if selected_date_obj and selected_hour is not None:
                Intent = request.env['bb.online.booking.intent'].sudo().with_company(branch.company_id)
                assignments, _held = Intent._plan_any_professionals(
                    ordered_services,
                    branch,
                    selected_date_obj,
                    selected_hour,
                )
                resources_available, _resource_error = _validate_booking_resource_availability(
                    request.env,
                    str(selected_date_obj),
                    branch,
                    ordered_services,
                    selected_hour,
                )
                any_professional_available = bool(assignments) and resources_available
                # Nobody rostered and free (and not just held by someone mid
                # payment): the customer may join the waiting list instead.
                waiting_list_available = (
                    not assignments
                    and not _held
                    and Intent._waiting_list_allowed(
                        branch, selected_hour,
                        sum(float(getattr(service, 'duration', 0) or 0) for service in services),
                    )
                )

            # Get all beautician lines for these services
            beautician_lines = request.env['product.beautician.line'].sudo().search([
                ('product_tmpl_id.product_variant_ids.id', 'in', service_ids),
                ('beautician_id.is_beautician', '=', True),
                ('beautician_id.active', '=', True),
                ('beautician_id.company_id', '=', branch.company_id.id),
                '|',
                ('product_tmpl_id.company_id', '=', False),
                ('product_tmpl_id.company_id', '=', branch.company_id.id),
                '|',
                ('beautician_id.branch_id', '=', branch_id),
                ('beautician_id.beautician_branch_ids', 'in', [branch_id]),
            ])
            # A named professional is shown only when that same person can
            # perform every selected service.  ``Any professional`` may still
            # be available because its planner can assign different people to
            # consecutive services.
            qualified_sets = [
                set(service.product_tmpl_id.beautician_line_ids.filtered(
                    lambda line: line.beautician_id.active
                    and line.beautician_id.is_beautician
                    and line.beautician_id.company_id == branch.company_id
                    and (
                        branch in line.beautician_id.beautician_branch_ids
                        or line.beautician_id.branch_id == branch
                    )
                ).mapped('beautician_id').ids)
                for service in ordered_services
            ]
            common_qualified_ids = set.intersection(*qualified_sets) if qualified_sets else set()
            beautician_lines = beautician_lines.filtered(
                lambda line: line.beautician_id.id in common_qualified_ids
            )

            available_beauticians = []
            busy_beauticians = []
            seen_beauticians = set()

            for line in beautician_lines:
                beautician = line.beautician_id
                if beautician.id in seen_beauticians:
                    continue
                seen_beauticians.add(beautician.id)

                # Fix image access for public users
                image_url = None
                if beautician.image_128:
                    try:
                        image_data = base64.b64decode(beautician.image_128)
                        image_b64 = base64.b64encode(image_data).decode('utf-8')
                        image_url = f'data:image/png;base64,{image_b64}'
                    except:
                        image_url = None

                beautician_data = {
                    'id': beautician.id,
                    'name': beautician.name,
                    'price': f"${line.price:.2f}",
                    'image': image_url
                }

                if selected_date_obj:
                    roster_availability = beautician._get_online_booking_availability(
                        branch,
                        selected_date_obj,
                        start_hour=selected_hour,
                        duration=total_duration,
                    )
                    if not roster_availability.get('available'):
                        continue

                # Check availability if date AND time selected
                if selected_date_obj and selected_hour is not None:
                    try:
                        # Check if service fits within salon hours
                        service_end_hour = selected_hour + total_duration
                        if service_end_hour > work_end:
                            beautician_data[
                                'reason'] = f"Service ends after salon closes ({self._format_hour(work_end)})"
                            busy_beauticians.append(beautician_data)
                            continue

                        # Check existing appointments
                        date_obj = selected_date_obj

                        existing_bookings = request.env['salon.appointment.service'].sudo().search([
                            ('beautician_id', '=', beautician.id),
                            ('appointment_id.appointment_date', '=', date_obj),
                            ('appointment_id.state', '!=', 'cancelled'),
                            ('appointment_id.company_id', '=', branch.company_id.id),
                        ])

                        is_busy = False
                        busy_reason = None

                        for booking in existing_bookings:
                            if booking.start_hour is not False and booking.duration:
                                booking_start = booking.start_hour
                                booking_end = booking_start + booking.duration

                                # FIXED: Check if the NEW appointment overlaps with existing booking
                                # Overlap occurs if: new_start < existing_end AND new_end > existing_start
                                new_appointment_end = selected_hour + total_duration

                                if selected_hour < booking_end and new_appointment_end > booking_start:
                                    # There IS an overlap - beautician is busy
                                    busy_reason = f"Busy from {self._format_hour(booking_start)} - {self._format_hour(booking_end)}"
                                    is_busy = True
                                    break

                        # Check if beautician is on approved leave for this date
                        if not is_busy:
                            leave = request.env['employee.timeoff.break'].sudo().search([
                                ('employee_id', '=', beautician.id),
                                ('state', '=', 'approved'),
                                ('category', '=', 'timeoff'),
                                ('start_date', '<=', date_obj),
                                ('end_date', '>=', date_obj),
                                ('company_id', '=', branch.company_id.id),
                            ], limit=1)
                            if leave:
                                is_busy = True
                                busy_reason = "On leave"

                        if is_busy:
                            beautician_data['reason'] = busy_reason
                            busy_beauticians.append(beautician_data)
                        else:
                            # Beautician is available at selected time
                            available_beauticians.append(beautician_data)

                    except Exception as e:
                        _logger.exception("Error checking beautician availability")
                        raise
                else:
                    # No time selected, show all as available
                    available_beauticians.append(beautician_data)

            # Generate response message
            message = ""
            if selected_date and selected_hour is not None:
                if not available_beauticians and busy_beauticians:
                    busy_names = [f"{b['name']} ({b['reason']})" for b in busy_beauticians[:3]]
                    message = f"All professionals are busy: {', '.join(busy_names)}"
                    if len(busy_beauticians) > 3:
                        message += f" and {len(busy_beauticians) - 3} more"
                elif available_beauticians and busy_beauticians:
                    message = f"{len(busy_beauticians)} professional(s) busy at this time"
                elif available_beauticians:
                    message = f"{len(available_beauticians)} professional(s) available"

            return request.make_response(
                json.dumps({
                    'beauticians': available_beauticians,
                    'busy_beauticians': busy_beauticians,
                    'any_professional_available': any_professional_available,
                    'waiting_list_available': waiting_list_available,
                    'message': message,
                    'total_duration': total_duration,
                    'salon_hours': f"{self._format_hour(work_start)} - {self._format_hour(work_end)}",
                    'selected_time_hour': selected_hour,  # Debug info
                    'selected_time_end': selected_hour + total_duration if selected_hour else None  # Debug info
                }),
                headers={'Content-Type': 'application/json'}
            )

        except Exception as e:
            _logger.exception("Error in get_beauticians_by_services")
            return request.make_response(
                json.dumps({'success': False, 'beauticians': [], 'error': 'Professional availability could not be checked. Please try again or contact the salon.'}),
                headers={'Content-Type': 'application/json'}
            )

    def _get_or_create_customer(self, data):
        email = data.get('email')
        customer = request.env['res.partner'].sudo().search([
            ('email', '=', email),
            '|',
            ('company_id', '=', False),
            ('company_id', 'in', self._allowed_company_ids()),
        ], limit=1)

        if not customer:
            customer = request.env['res.partner'].sudo().create({
                'name': f"{data.get('first_name')} {data.get('last_name')}",
                'email': email,
                'phone': data.get('mobile_phone'),
                'is_company': False,
                'company_id': False,
            })

        return customer

    def _safe_json(self, data, default=None):
        """Safely parse JSON data"""
        try:
            if isinstance(data, str):
                return json.loads(data)
            elif data:
                return data
            else:
                return default if default is not None else []
        except Exception as e:
            _logger.warning("JSON parse error: %s", e)
            return default if default is not None else []

    def _format_hour(self, hour):
        """Format hour float to time string (e.g., 14.5 -> '14:30')"""
        hours = int(hour)
        minutes = int((hour - hours) * 60)
        return f"{hours:02d}:{minutes:02d}"

    def _json_response(self, data):
        """Return JSON response with proper headers"""
        return request.make_response(
            json.dumps(data),
            headers={'Content-Type': 'application/json'}
        )
