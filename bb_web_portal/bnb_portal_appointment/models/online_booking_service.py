"""The parts of an online booking both checkout paths share.

A customer booking online reaches one of two controllers depending on whether
they pay now or pay at the salon:

    /salon/complete-booking        booking.py    pay later
    /salon/create-booking-payment  payment.py    pay now

Both had their own copy of the same work -- reading the form, finding or
creating the contact, validating the chosen services, assembling the
appointment values -- and the copies had drifted apart in four places. This
service owns that work once so they cannot drift again.

Per ARCHITECTURE_AND_CHANGE_GUARDRAILS.md the controllers stay as the public
entry points and become thin adapters over this; routes, form fields and
response payloads are unchanged.
"""

from odoo import api, models


class OnlineBookingService(models.AbstractModel):
    """Resolve the customer, the branch's services and the appointment values.

    Owns no table. Every method takes what it needs and returns a result;
    nothing here reads the request.
    """

    _name = "bb.online.booking.service"
    _description = "BnB Online Booking Service"

    # The same field arrives under two names because the two checkout forms
    # were written separately. Both are accepted so neither form has to change.
    _OTHER_PHONE_KEYS = ("customer_other_phone", "other_phone")

    @api.model
    def read_booking_form(self, form):
        """Normalise one checkout form into the values a booking needs."""
        other_phone = ""
        for key in self._OTHER_PHONE_KEYS:
            if form.get(key):
                other_phone = form[key]
                break
        return {
            "first_name": form.get("first_name", ""),
            "last_name": form.get("last_name", ""),
            "email": form.get("email", ""),
            "mobile_phone": form.get("mobile_phone", ""),
            "other_phone": other_phone,
            "pronouns": form.get("pronouns", ""),
            "salon_id": form.get("salon_id"),
            "appointment_date": form.get("appointment_date"),
            "billing_address": form.get("billing_address", ""),
            "city": form.get("city", ""),
            "state": form.get("state", ""),
            "postcode": form.get("postcode", ""),
            "promo_code": form.get("promo_code", ""),
            "payment_option": form.get("payment_option", "full"),
            "agree_policy": form.get("agree_policy") == "on",
            "remember_customer": form.get("remember_me") == "on",
        }

    @api.model
    def has_required_fields(self, booking):
        """The five fields neither path will book without."""
        return all([
            booking["first_name"], booking["last_name"], booking["email"],
            booking["mobile_phone"], booking["salon_id"],
            booking["appointment_date"],
        ])

    @api.model
    def resolve_customer(self, booking, allowed_company_ids, social_partner_id=None):
        """Find the contact this booking belongs to, or create it.

        Looks first at a partner already identified by social login, then by
        email, and creates one only if neither matched. An existing contact has
        its blank fields filled in and nothing overwritten -- the customer is
        booking, not editing their record.

        The address is written on both paths. It used to be written only on the
        pay-now path, so which details a salon ended up holding depended on how
        the customer chose to pay.
        """
        Partner = self.env["res.partner"].sudo()
        company_clause = [
            "|", ("company_id", "=", False),
            ("company_id", "in", allowed_company_ids),
        ]

        customer = Partner.browse()
        if social_partner_id:
            customer = Partner.search(
                [("id", "=", int(social_partner_id))] + company_clause, limit=1)
        if not customer:
            customer = Partner.search(
                [("email", "=", booking["email"])] + company_clause, limit=1)

        full_name = ("%s %s" % (booking["first_name"], booking["last_name"])).strip()
        if not customer:
            return Partner.create({
                "name": full_name,
                "email": booking["email"],
                "phone": booking["mobile_phone"],
                "street": booking["billing_address"],
                "city": booking["city"],
                "zip": booking["postcode"],
                "is_company": False,
                "company_id": False,
            })

        updates = {}
        if booking["mobile_phone"] and not customer.phone:
            updates["phone"] = booking["mobile_phone"]
        # A contact created from an email alone is named after the local part;
        # a real name from the form is an improvement on that, and only that.
        placeholder = (customer.email or "").split("@")[0]
        if full_name and (not customer.name or customer.name == placeholder):
            updates["name"] = full_name
        if booking["billing_address"] and not customer.street:
            updates["street"] = booking["billing_address"]
        if booking["city"] and not customer.city:
            updates["city"] = booking["city"]
        if booking["postcode"] and not customer.zip:
            updates["zip"] = booking["postcode"]
        if updates:
            customer.write(updates)
        return customer

    @api.model
    def resolve_services(self, service_ids, branch, require_branch_offering=True):
        """Return the chosen services in order, or raise ValueError.

        ``require_branch_offering`` additionally demands that each service is
        flagged as an appointment service and linked to this branch. The
        pay-now path has always required that; the pay-later path never has,
        so it can take a booking for a service the branch does not offer. The
        two are kept apart here, behind one flag, until that is decided --
        rather than left as two copies of a query that quietly disagree.
        """
        Product = self.env["product.product"].sudo()
        ordered = []
        for raw_id in service_ids:
            try:
                service_id = int(raw_id)
            except (TypeError, ValueError):
                raise ValueError("Invalid service selection")
            domain = [
                ("id", "=", service_id),
                ("type", "=", "service"),
                ("active", "=", True),
            ]
            if require_branch_offering:
                domain += [
                    ("product_tmpl_id.is_appointment_service", "=", True),
                    ("product_tmpl_id.branch_ids", "in", [branch.id]),
                ]
            domain += [
                "|", ("product_tmpl_id.company_id", "=", False),
                ("product_tmpl_id.company_id", "=", branch.company_id.id),
            ]
            service = Product.search(domain, limit=1)
            if not service:
                raise ValueError("Selected service not found")
            ordered.append(service)
        return ordered

    @api.model
    def appointment_values(self, booking, customer):
        """The appointment both paths create, in draft, before payment.

        remember_customer is set on both. Only the pay-later path used to
        record it, so a customer who ticked "remember me" and then paid online
        was not remembered.
        """
        values = {
            "customer_id": customer.id,
            "customer_first_name": booking["first_name"],
            "customer_last_name": booking["last_name"],
            "customer_email": booking["email"],
            "customer_phone": booking["mobile_phone"],
            "customer_other_phone": booking["other_phone"],
            "customer_pronouns": booking["pronouns"],
            "branch_id": int(booking["salon_id"]),
            "appointment_date": booking["appointment_date"],
            "policy_agreed": booking["agree_policy"],
            "remember_customer": booking["remember_customer"],
            "booked_online": True,
            "state": "draft",
        }
        if "auto_send_consultation_forms" in self.env["salon.appointment"]._fields:
            values["auto_send_consultation_forms"] = True
        return values
