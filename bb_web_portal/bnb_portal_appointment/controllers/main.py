# -*- coding: utf-8 -*-
"""Backward-compatibility shim: the monolithic controller was split into
per-domain files. Import from the specific submodules in new code."""
from .booking_helpers import (
    _safe_int,
    _get_start_hour_from_timeslots,
    _compute_reward_discount,
    _compute_discount_from_code,
    _validate_booking_availability,
)
from .portal_main import MainController
from .branch import BranchController
from .beautician import BeauticianController
from .booking import BookingController
from .related_products import RelatedProductsController
from .promo_code import PromoCodeController
from .payment import SalonPaymentController

__all__ = [
    "_safe_int",
    "_get_start_hour_from_timeslots",
    "_compute_reward_discount",
    "_compute_discount_from_code",
    "_validate_booking_availability",
    "MainController",
    "BranchController",
    "BeauticianController",
    "BookingController",
    "RelatedProductsController",
    "PromoCodeController",
    "SalonPaymentController",
]
