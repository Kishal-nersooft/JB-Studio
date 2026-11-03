# -*- coding: utf-8 -*-
from odoo.http import request, route
import logging
from odoo.addons.portal.controllers import portal

from .booking_helpers import (
    _json_response,
    _safe_int,
)

_logger = logging.getLogger(__name__)

class BranchController(portal.CustomerPortal):
    @staticmethod
    def _allowed_company_ids():
        return request.env.companies.ids or [request.env.company.id]

    @route('/salon/get-branch-hours', type='http', auth='public', methods=['GET'])
    def get_branch_hours(self, **kwargs):
        try:
            def _round_to_quarter(hour_value):
                try:
                    value = float(hour_value or 0)
                except (TypeError, ValueError):
                    return 0.0
                return round(value * 4) / 4.0

            branch_id = _safe_int(kwargs.get('branch_id', 0))

            if not branch_id:
                return _json_response({
                    'success': False,
                    'error': 'Please select a valid location.'
                })

            branch = request.env['beauty.branch'].sudo().search([
                ('id', '=', branch_id),
                ('company_id', 'in', self._allowed_company_ids()),
                ('active', '=', True),
            ], limit=1)
            if not branch:
                return _json_response({
                    'success': False,
                    'error': 'This location is unavailable. Please select another location.'
                })
            start_hour = _round_to_quarter(branch.work_start_hour or 9.0)
            end_hour = _round_to_quarter(branch.work_end_hour or 18.0)
            if end_hour <= start_hour:
                start_hour = 9.0
                end_hour = 18.0

            return _json_response({
                'start_hour': start_hour,
                'end_hour': end_hour,
                'booking_fee': branch.booking_fee or 0.00,
                'branch_name': branch.name,
                'branch_tz': branch.tz or 'UTC',
                'saturday_surcharge_percent': branch.saturday_surcharge_percent or 0.0,
                'sunday_surcharge_percent': branch.sunday_surcharge_percent or 0.0,
            })

        except Exception as e:
            _logger.exception('Failed to load online booking branch details')
            return _json_response({
                'success': False,
                'error': 'Location details could not be loaded. Please try again or contact the salon.'
            })
