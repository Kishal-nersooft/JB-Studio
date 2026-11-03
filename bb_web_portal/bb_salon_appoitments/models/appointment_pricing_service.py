from datetime import time, timedelta

from odoo import api, models


class AppointmentPricingService(models.AbstractModel):
    """Stable, persistence-free boundary for appointment pricing rules.

    This abstract model deliberately owns no fields or database table.  Callers
    pass primitive values in and receive primitive values out, so pricing rules
    can be reused without coupling POS, website, or reporting code to the
    internal structure of ``salon.appointment``.
    """

    _name = "bb.appointment.pricing.service"
    _description = "BnB Appointment Pricing Service"

    @api.model
    def calculate_line_total(self, base_price, beautician_addon_price):
        """Return the existing appointment-service line arithmetic."""
        return (base_price or 0.0) + (beautician_addon_price or 0.0)

    @api.model
    def calculate_end_hour(self, start_hour, duration):
        """Return the legacy end-hour calculation for a service line."""
        if start_hour and duration:
            return start_hour + duration
        return start_hour or 0.0

    @api.model
    def format_time_hour(self, float_hour):
        """Format a float hour using the legacy appointment display contract."""
        if float_hour is None:
            return None
        try:
            td = timedelta(hours=float_hour)
            total_seconds = int(td.total_seconds())
            hours, remainder = divmod(total_seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            return time(hour=hours % 24, minute=minutes).strftime('%H:%M')
        except (ValueError, OverflowError):
            return 'Invalid'

    @api.model
    def calculate_service_totals(
        self,
        base_total,
        appointment_date=None,
        saturday_surcharge_percent=0.0,
        sunday_surcharge_percent=0.0,
    ):
        """Return the appointment service-total calculation.

        Surcharge percentages are fractions: ``0.05`` is 5%. That is the
        contract set by the branch form, where the fields use
        ``widget="percentage"`` and so store a fraction whenever someone types
        a percentage into them.

        An earlier version also accepted whole percentages, reading any value
        above ``1`` as one. That made the meaning of the number flip at exactly
        ``1``: a branch set to 1% was read as the fraction 1.0 and charged
        100%, doubling every Saturday booking. Values are now read one way
        only, so a branch holding whole percentages has to be corrected in
        configuration rather than guessed at here.
        """
        base_total = base_total or 0.0
        surcharge_fraction = 0.0
        if appointment_date:
            weekday = appointment_date.weekday()
            if weekday == 5:
                surcharge_fraction = saturday_surcharge_percent or 0.0
            elif weekday == 6:
                surcharge_fraction = sunday_surcharge_percent or 0.0

        normalized_percent = surcharge_fraction
        surcharge_amount = (
            base_total * normalized_percent if normalized_percent else 0.0
        )
        services_total = base_total + surcharge_amount
        return {
            "services_subtotal": base_total,
            "surcharge_percent": normalized_percent,
            "surcharge_amount": surcharge_amount,
            "services_total": services_total,
            "total_amount": services_total,
        }

    @api.model
    def calculate_checkout_totals(
        self,
        service_total,
        booking_fee=0.0,
        discount_amount=0.0,
        payment_option="full",
    ):
        """Return the legacy website-booking checkout arithmetic.

        Discount discovery and currency rounding deliberately remain outside
        this method. Those concerns stay at the website and currency boundaries;
        this contract owns only the shared primitive arithmetic.
        """
        service_total = service_total or 0.0
        booking_fee = booking_fee or 0.0
        discount_amount = discount_amount or 0.0
        total_before_discount = service_total + booking_fee
        applied_discount = min(discount_amount, total_before_discount)
        total_after_discount = max(
            total_before_discount - applied_discount,
            0.0,
        )
        payment_amount = (
            total_after_discount / 2
            if payment_option == "half"
            else total_after_discount
        )
        if payment_amount < 0:
            payment_amount = 0.0
        return {
            "discount_amount": applied_discount,
            "total_before_discount": total_before_discount,
            "total_after_discount": total_after_discount,
            "payment_amount": payment_amount,
        }

    @api.model
    def calculate_deposit_allocation(
        self,
        service_total,
        discount_amount,
        deposit_amount,
        payment_option,
    ):
        """Return the existing online-deposit balance and credit allocation.

        ``service_total`` intentionally excludes the booking fee, matching the
        persisted online-deposit contract.  Full payments also intentionally
        force both balance and credit to zero, even when the supplied amounts
        would otherwise produce a remainder.  These are compatibility rules;
        changing them requires a separately approved business change.
        """
        service_total = service_total or 0.0
        discount_amount = discount_amount or 0.0
        deposit_amount = deposit_amount or 0.0
        net_service_total = max(service_total - discount_amount, 0.0)
        allocation = self.calculate_balance_and_credit(
            net_service_total,
            deposit_amount,
        )
        balance_due = allocation["balance_due"]
        credit_amount = allocation["credit_amount"]
        if payment_option == "full":
            balance_due = 0.0
            credit_amount = 0.0
        return {
            "net_service_total": net_service_total,
            "balance_due": balance_due,
            "credit_amount": credit_amount,
        }

    @api.model
    def calculate_balance_and_credit(self, service_total, applied_amount):
        """Return the shared legacy POS deposit balance/credit split.

        Currency rounding and the decision to suppress automatic credit remain
        at each caller boundary.  This method owns only the duplicated primitive
        arithmetic used when a deposit or redemption is applied to services.
        """
        service_total = service_total or 0.0
        applied_amount = applied_amount or 0.0
        return {
            "balance_due": max(service_total - applied_amount, 0.0),
            "credit_amount": max(applied_amount - service_total, 0.0),
        }

    @api.model
    def calculate_deposit_surplus(self, deposit_total, service_total):
        """Return the legacy POS surplus from negative deposit order lines."""
        deposit_total = deposit_total or 0.0
        service_total = service_total or 0.0
        if deposit_total >= 0.0:
            return 0.0
        return max(abs(deposit_total) - max(service_total, 0.0), 0.0)

    @api.model
    def calculate_change_credit_availability(
        self,
        amount_return,
        deposit_surplus,
        credited_amount=0.0,
    ):
        """Return the legacy POS change-credit bounds before currency checks."""
        available_credit = max(
            amount_return or 0.0,
            deposit_surplus or 0.0,
            0.0,
        )
        available_change = max(
            available_credit - (credited_amount or 0.0),
            0.0,
        )
        return {
            "available_credit": available_credit,
            "available_change": available_change,
        }

    @api.model
    def calculate_forfeit_split(self, deposit_amount, requested_forfeit_amount):
        """Return the legacy capped forfeit and remaining-credit amounts.

        Callers keep currency rounding at the ``res.currency`` boundary and
        pass the rounded requested amount into this primitive-only contract.
        """
        deposit_amount = deposit_amount or 0.0
        requested_forfeit_amount = requested_forfeit_amount or 0.0
        forfeit_amount = min(
            max(requested_forfeit_amount, 0.0),
            deposit_amount,
        )
        remaining_amount = max(deposit_amount - forfeit_amount, 0.0)
        return {
            "forfeit_amount": forfeit_amount,
            "remaining_amount": remaining_amount,
        }

    @api.model
    def determine_payment_status(
        self,
        has_full_payment_evidence,
        has_partial_payment_evidence,
    ):
        """Return the legacy paid/partial/unpaid evidence classification.

        Callers retain ownership of currency comparisons and of deciding which
        payment records qualify as settlement evidence.  This contract only
        centralizes the shared precedence rule, so it cannot weaken the POS or
        online-payment validation boundaries.
        """
        if has_full_payment_evidence:
            return "paid"
        if has_partial_payment_evidence:
            return "partial"
        return "unpaid"

    @api.model
    def determine_deposit_redemption_state(
        self,
        has_redemption_evidence,
        has_full_redemption_evidence,
    ):
        """Return the legacy active/partial/redeemed deposit state.

        Callers retain their existing currency or tolerance comparisons and
        pass only the resulting evidence flags.  Full-redemption evidence has
        precedence, matching every migrated POS and appointment caller.
        """
        if has_full_redemption_evidence:
            return "redeemed"
        if has_redemption_evidence:
            return "partial"
        return "active"
