# -*- coding: utf-8 -*-
import json
import logging

from odoo.http import request, route
from odoo.addons.portal.controllers import portal

from .booking_helpers import (
    _safe_int,
    _compute_discount_from_code,
)

_logger = logging.getLogger(__name__)


class PromoCodeController(portal.CustomerPortal):
    """Controller for promo code validation"""
    @staticmethod
    def _allowed_company_ids():
        return request.env.companies.ids or [request.env.company.id]

    @route('/salon/promo/validate', type='http', auth='public', methods=['POST'])
    def validate_promo_code(self, **kwargs):
        """Validate a gift/discount code and return discount info"""
        try:
            data = {}
            raw = request.httprequest.data
            if raw:
                try:
                    data = json.loads(raw.decode('utf-8'))
                except Exception:
                    data = {}
            promo_code = (data.get('promo_code') or kwargs.get('promo_code') or '').strip()
            total_amount = float(data.get('total_amount', kwargs.get('total_amount', 0)))
            branch_id = _safe_int(data.get('branch_id', kwargs.get('branch_id')))

            branch = None
            if branch_id:
                branch = request.env['beauty.branch'].sudo().search([
                    ('id', '=', branch_id),
                    ('company_id', 'in', self._allowed_company_ids()),
                    ('active', '=', True),
                ], limit=1)

            discount_amount, error = _compute_discount_from_code(
                request.env, promo_code, total_amount, branch=branch
            )

            if error:
                return request.make_response(
                    json.dumps({'valid': False, 'message': error}),
                    headers={'Content-Type': 'application/json'}
                )

            return request.make_response(
                json.dumps({
                    'valid': True,
                    'message': 'Code applied successfully',
                    'discount_amount': round(discount_amount, 2),
                    'new_total': round(max(total_amount - discount_amount, 0), 2),
                }),
                headers={'Content-Type': 'application/json'}
            )

        except Exception as e:
            _logger.exception("Error validating promo code")
            return request.make_response(
                json.dumps({'valid': False, 'message': 'The code could not be checked. Please try again.', 'error': 'The code could not be checked. Please try again.'}),
                headers={'Content-Type': 'application/json'}
            )
