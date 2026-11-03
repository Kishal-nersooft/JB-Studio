# -*- coding: utf-8 -*-
import json
import logging

from odoo.http import request, route
from odoo.addons.portal.controllers import portal

from .booking_helpers import (
    _safe_int,
)

_logger = logging.getLogger(__name__)


class RelatedProductsController(portal.Controller):
    @staticmethod
    def _allowed_company_ids():
        return request.env.companies.ids or [request.env.company.id]

    def _get_scoped_branch(self, branch_id):
        if not branch_id:
            return request.env['beauty.branch']
        return request.env['beauty.branch'].sudo().search([
            ('id', '=', int(branch_id)),
            ('company_id', 'in', self._allowed_company_ids()),
            ('active', '=', True),
        ], limit=1)

    @route('/salon/get-all-related-products', type='http', auth='public', methods=['POST'])
    def get_all_related_products(self, **kwargs):
        """
        Fetch all related products for the selected services.
        This will be called when user clicks "Book" on service selection.
        """
        try:
            # Parse request data
            data = {}
            raw = request.httprequest.data
            if raw:
                try:
                    data = json.loads(raw.decode('utf-8'))
                except Exception:
                    data = {}
            service_ids = data.get('service_ids') or kwargs.get('service_ids') or []
            if isinstance(service_ids, str):
                try:
                    service_ids = json.loads(service_ids)
                except Exception:
                    service_ids = []
            branch_id = _safe_int(data.get('branch_id', kwargs.get('branch_id')))

            _logger.debug("Get related products request")

            if not service_ids:
                return self._json_response({
                    'success': False,
                    'related_products': [],
                    'message': 'No services selected'
                })

            # Get selected services
            selected_services = request.env['product.product'].sudo().search([
                ('id', 'in', [int(sid) for sid in service_ids]),
                ('type', '=', 'service'),
                ('active', '=', True),
                '|',
                ('product_tmpl_id.company_id', '=', False),
                ('product_tmpl_id.company_id', 'in', self._allowed_company_ids()),
            ])
            _logger.debug("Found %s selected services", len(selected_services))

            # Get all related product templates from selected services
            related_product_template_ids = set()

            for service in selected_services:
                _logger.debug("Checking service %s", service.id)

                # Check if product template has related_product_ids field
                if hasattr(service.product_tmpl_id, 'related_product_ids'):
                    related_products = service.product_tmpl_id.related_product_ids
                    _logger.debug("Found %s related product templates", len(related_products))

                    for related in related_products:
                        related_product_template_ids.add(related.id)
                        _logger.debug("Related template %s", related.id)
                else:
                    _logger.debug("Product template lacks related_product_ids")

            _logger.debug("Total unique related product templates: %s", len(related_product_template_ids))

            if not related_product_template_ids:
                _logger.debug("No related product templates found")
                return self._json_response({
                    'success': True,
                    'related_products': [],
                    'message': 'No related products found'
                })

            # Get product variants for these templates (only appointment services)
            related_products = request.env['product.product'].sudo().search([
                ('product_tmpl_id', 'in', list(related_product_template_ids)),
                ('active', '=', True),
                ('type', '=', 'service'),
                ('product_tmpl_id.is_appointment_service', '=', True),
                '|',
                ('product_tmpl_id.company_id', '=', False),
                ('product_tmpl_id.company_id', 'in', self._allowed_company_ids()),
                ('id', 'not in', [int(sid) for sid in service_ids])  # Exclude already selected services
            ])

            _logger.debug("Found %s related product variants", len(related_products))

            # If branch_id provided, filter by branch availability
            branch = None
            if branch_id:
                branch = self._get_scoped_branch(branch_id)
                if branch.exists():
                    _logger.debug("Filtering related products by branch")
                    related_products = related_products.filtered(
                        lambda p: branch in p.product_tmpl_id.branch_ids
                    )
                    related_products = related_products.filtered(
                        lambda p: (not p.product_tmpl_id.company_id
                                   or p.product_tmpl_id.company_id.id == branch.company_id.id)
                    )
                    _logger.debug("After branch filter: %s products", len(related_products))

            # Format related products data
            currency = (
                branch.company_id.currency_id
                if branch and branch.exists()
                else request.env.company.currency_id
            )
            related_products_data = []

            for product in related_products:
                # Get service duration
                service_duration = getattr(product, 'duration', 1.0)
                service_duration_display = getattr(product, 'service_duration_display', '1h')

                # Get base price
                base_price = product.list_price
                formatted_price = currency.format(base_price)

                # Get description
                description = product.description_sale if product.description_sale else ''

                product_data = {
                    'id': product.id,
                    'name': product.name,
                    'duration': service_duration,
                    'duration_display': service_duration_display,
                    'base_price': base_price,
                    'formatted_price': formatted_price,
                    'description': description
                }

                related_products_data.append(product_data)
                _logger.debug("Added related product %s", product.id)

            _logger.debug("Returning %s related products", len(related_products_data))

            return self._json_response({
                'success': True,
                'related_products': related_products_data,
                'message': f'Found {len(related_products_data)} related products'
            })

        except Exception as e:
            _logger.exception("Error in get_all_related_products")

            return self._json_response({
                'success': False,
                'related_products': [],
                'error': 'Related services could not be loaded. Please try again.',
                'message': 'Related services could not be loaded. Please try again.'
            })

    def _json_response(self, data):
        """Helper method to return JSON response"""
        return request.make_response(
            json.dumps(data),
            headers=[('Content-Type', 'application/json')]
        )

    @route('/salon/get-related-services', type='http', auth='public', methods=['POST'])
    def get_related_services(self, **kwargs):
        """Compatibility endpoint for older frontend flow (beautician step)."""
        try:
            data = {}
            raw = request.httprequest.data
            if raw:
                try:
                    data = json.loads(raw.decode('utf-8'))
                except Exception:
                    data = {}

            service_ids = data.get('service_ids') or kwargs.get('service_ids') or []
            if isinstance(service_ids, str):
                try:
                    service_ids = json.loads(service_ids)
                except Exception:
                    service_ids = []

            branch_id = _safe_int(data.get('branch_id', kwargs.get('branch_id')))
            branch = self._get_scoped_branch(branch_id) if branch_id else None

            related_products = []
            if service_ids:
                selected_services = request.env['product.product'].sudo().search([
                    ('id', 'in', [int(sid) for sid in service_ids]),
                    ('type', '=', 'service'),
                    ('active', '=', True),
                    '|',
                    ('product_tmpl_id.company_id', '=', False),
                    ('product_tmpl_id.company_id', 'in', self._allowed_company_ids()),
                ])
                template_ids = set()
                for service in selected_services:
                    if hasattr(service.product_tmpl_id, 'related_product_ids'):
                        template_ids.update(service.product_tmpl_id.related_product_ids.ids)

                related_products = request.env['product.product'].sudo().search([
                    ('product_tmpl_id', 'in', list(template_ids)),
                    ('active', '=', True),
                    ('type', '=', 'service'),
                    ('product_tmpl_id.is_appointment_service', '=', True),
                    '|',
                    ('product_tmpl_id.company_id', '=', False),
                    ('product_tmpl_id.company_id', 'in', self._allowed_company_ids()),
                    ('id', 'not in', [int(sid) for sid in service_ids])
                ])

                if branch and branch.exists():
                    related_products = related_products.filtered(
                        lambda p: branch in p.product_tmpl_id.branch_ids
                    )
                    related_products = related_products.filtered(
                        lambda p: (not p.product_tmpl_id.company_id
                                   or p.product_tmpl_id.company_id.id == branch.company_id.id)
                    )

            currency = (
                branch.company_id.currency_id
                if branch and branch.exists()
                else request.env.company.currency_id
            )
            related_products_data = []
            for product in related_products:
                related_products_data.append({
                    'id': product.id,
                    'name': product.name,
                    'duration': getattr(product, 'duration', 1.0),
                    'duration_display': getattr(product, 'service_duration_display', '1h'),
                    'formatted_total_price': currency.format(product.list_price),
                    'addon_price': 0,
                })

            return self._json_response({
                'success': True,
                'related_services': related_products_data,
                'message': f'Found {len(related_products_data)} related products'
            })

        except Exception as e:
            _logger.exception("Error in get_related_services")
            return self._json_response({
                'success': False,
                'related_services': [],
                'message': 'Related services could not be loaded. Please try again.'
            })
