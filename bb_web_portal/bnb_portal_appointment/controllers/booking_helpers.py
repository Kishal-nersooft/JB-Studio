"""Compatibility imports for existing booking controllers."""
import json
from odoo.http import request
from ..services.booking import (
    _safe_int,
    _get_start_hour_from_timeslots,
    _compute_reward_discount,
    _program_unavailable_reason,
    _compute_discount_from_code,
    _pick_available_beautician,
    _format_hour_label,
    _get_service_resource_ids,
    _has_resource_conflict,
    _get_unavailable_resource_start_hours,
    _validate_booking_resource_availability,
    _validate_booking_availability,
)

def _json_response(data):
    """Return `data` as a JSON http response.

    Lives here because more than one booking controller answers in JSON, and
    a controller that called a copy belonging to another class raised
    AttributeError on every one of its own return paths -- including inside
    its own error handler, so it could not even answer with the fallback.
    """
    return request.make_response(
        json.dumps(data),
        headers=[('Content-Type', 'application/json')],
    )
