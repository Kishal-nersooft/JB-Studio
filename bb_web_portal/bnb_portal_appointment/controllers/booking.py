# -*- coding: utf-8 -*-
import json
import logging

from psycopg2.errors import UniqueViolation

from odoo.http import request, route
from odoo.addons.portal.controllers import portal

from .booking_helpers import (
    _get_start_hour_from_timeslots,
    _compute_discount_from_code,
    _validate_booking_availability,
    _validate_booking_resource_availability,
    _get_unavailable_resource_start_hours,
    _get_service_resource_ids,
    _pick_available_beautician,
)

_logger = logging.getLogger(__name__)


class BookingController(portal.CustomerPortal):
    @staticmethod
    def _allowed_company_ids():
        return request.env.companies.ids or [request.env.company.id]

    def _get_scoped_branch(self, branch_id):
        return request.env['beauty.branch'].sudo().search([
            ('id', '=', int(branch_id)),
            ('company_id', 'in', self._allowed_company_ids()),
            ('active', '=', True),
        ], limit=1)

    def _get_scoped_services(self, branch, service_ids):
        services = []
        for service_id in service_ids:
            try:
                service_id = int(service_id)
            except (TypeError, ValueError):
                return [], 'Invalid service selection'
            service = request.env['product.product'].sudo().search([
                ('id', '=', service_id),
                ('type', '=', 'service'),
                ('active', '=', True),
                ('product_tmpl_id.is_appointment_service', '=', True),
                ('product_tmpl_id.branch_ids', 'in', [branch.id]),
                '|',
                ('product_tmpl_id.company_id', '=', False),
                ('product_tmpl_id.company_id', '=', branch.company_id.id),
            ], limit=1)
            if not service.exists():
                return [], 'Selected service not found'
            services.append(service)
        return services, None

    @route('/salon/get-resource-unavailable-slots', type='http', auth='public', methods=['GET'])
    def get_resource_unavailable_slots(self, **kwargs):
        try:
            branch_id = kwargs.get('branch_id')
            appointment_date = kwargs.get('appointment_date')
            selected_service_ids = [
                service_id
                for service_id in (kwargs.get('selected_services') or '').split(',')
                if service_id
            ]
            if not branch_id or not appointment_date or not selected_service_ids:
                return request.make_response(json.dumps({
                    'success': False,
                    'unavailable_start_hours': [],
                    'error': 'Please select a branch, service, and date.'
                }), headers={'Content-Type': 'application/json'})

            branch = self._get_scoped_branch(branch_id)
            if not branch.exists():
                return request.make_response(json.dumps({
                    'success': False,
                    'unavailable_start_hours': [],
                    'error': 'Invalid branch'
                }), headers={'Content-Type': 'application/json'})

            services, error = self._get_scoped_services(branch, selected_service_ids)
            if error:
                return request.make_response(json.dumps({
                    'success': False,
                    'unavailable_start_hours': [],
                    'error': error,
                }), headers={'Content-Type': 'application/json'})

            unavailable_start_hours = _get_unavailable_resource_start_hours(
                request.env,
                appointment_date,
                branch,
                services,
            )
            return request.make_response(json.dumps({
                'success': True,
                'unavailable_start_hours': unavailable_start_hours,
            }), headers={'Content-Type': 'application/json'})
        except Exception as error:
            _logger.exception("Failed to load online booking resource slots")
            return request.make_response(json.dumps({
                'success': False,
                'unavailable_start_hours': [],
                'error': 'Available times could not be loaded. Please try again or contact the salon.',
            }), headers={'Content-Type': 'application/json'})

    @route('/salon/check-resource-availability', type='http', auth='public', methods=['GET'])
    def check_resource_availability(self, **kwargs):
        try:
            branch_id = kwargs.get('branch_id')
            appointment_date = kwargs.get('appointment_date')
            selected_services = [
                sid for sid in (kwargs.get('selected_services') or '').split(',')
                if sid
            ]
            start_hour = float(kwargs.get('start_hour') or 0.0)

            if not branch_id or not appointment_date or not selected_services:
                return request.make_response(json.dumps({
                    'success': False,
                    'available': False,
                    'error': 'Please select a branch, service, date, and time.'
                }), headers={'Content-Type': 'application/json'})

            branch = self._get_scoped_branch(branch_id)
            if not branch.exists():
                return request.make_response(json.dumps({
                    'success': False,
                    'available': False,
                    'error': 'Invalid branch'
                }), headers={'Content-Type': 'application/json'})

            ordered_services, service_error = self._get_scoped_services(branch, selected_services)
            if service_error:
                return request.make_response(json.dumps({
                    'success': False,
                    'available': False,
                    'error': service_error,
                }), headers={'Content-Type': 'application/json'})

            ok, error = _validate_booking_resource_availability(
                request.env,
                appointment_date,
                branch,
                ordered_services,
                start_hour,
            )
            return request.make_response(json.dumps({
                'success': True,
                'available': bool(ok),
                'error': error or '',
            }), headers={'Content-Type': 'application/json'})
        except Exception as e:
            _logger.exception("Failed to check online booking resource availability")
            return request.make_response(json.dumps({
                'success': False,
                'available': False,
                'error': 'Availability could not be checked. Please try again or contact the salon.',
            }), headers={'Content-Type': 'application/json'})

    @route('/salon/complete-booking', type='http', auth='public', methods=['POST'], website=True)
    def complete_booking(self, **kwargs):
        # Legacy callers must also complete the verified payment checkout.
        from .payment_intent import PaymentIntentController
        return PaymentIntentController().start_checkout(**kwargs)
