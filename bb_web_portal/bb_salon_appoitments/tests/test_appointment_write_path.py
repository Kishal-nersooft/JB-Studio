"""The order of the appointment create/write/unlink chain is a real interface.

Seven modules override ``salon.appointment.create``. Each one does part of its
work before ``super()`` and part after, so the chain runs outward-in on the way
down and inward-out on the way back:

    bb_webex_callcenter        flags call-centre bookings, copies partner values
    bb_sms_confirmation        (nothing before)  -> texts the customer after
    bb_employee_customer       matches an existing contact by email
    bnb_excel_dashboard        (nothing before)  -> signals the live dashboard
    bb_consultation_form       defaults auto-send -> sends the forms after
    bb_appointment_pos         validates the roster, resolves branch -> company
    bb_salon_appoitments       allocates the reference, creates the customer

Nothing in the code says that. The order is a consequence of the module
dependency graph, so one added ``depends`` entry anywhere in the tree can
reorder it silently -- adding bb_employee_customer to bnb_excel_dashboard's
manifest, for instance, moves the dashboard from fourth to first across five of
these chains.

Two positions are load-bearing, and they were established by breaking them
rather than by reading the code:

  * bb_employee_customer must run *before* bb_salon_appoitments. It links a
    booking whose email belongs to a member of staff to that person's own
    contact; the base layer, seeing no customer_id, would instead create a
    second contact for someone the salon already employs.
  * bb_appointment_pos must run *before* bb_salon_appoitments, because it is
    the only layer that puts company_id on the appointment. The base layer's
    own two uses of the company -- the per-company appointment number, and the
    company of a contact it creates -- each fall back to the branch on their
    own, so those survive; the appointment's own company_id does not.

Two positions that look load-bearing are not, and are recorded here so nobody
re-derives them: bb_consultation_form reads source_webex_call_id directly
rather than relying on bb_webex_callcenter having set is_call_center_booking
first, and the base layer's branch fallbacks mean it never depends on an outer
layer having run.

On the way back out the whole chain matters at once: bb_salon_appoitments
allocates the appointment reference innermost, and bb_sms_confirmation puts
that reference in the message it texts the customer from almost the outermost
position. That span is pinned too.

See docs/adr/0010-appointment-write-path.md.
"""

from odoo.tests import TransactionCase, tagged

#: create/write/unlink, outermost override first. Modules that are not
#: installed are skipped, so this is the expected order *of what is present*.
EXPECTED = {
    "salon.appointment": {
        "create": [
            "bb_webex_callcenter",
            "bb_sms_confirmation",
            "bb_employee_customer",
            "bnb_excel_dashboard",
            "bb_consultation_form",
            "bb_appointment_pos",
            "bb_salon_appoitments",
        ],
        "write": [
            "bb_webex_callcenter",
            "bb_sms_confirmation",
            "bnb_excel_dashboard",
            "bb_consultation_form",
            "bb_appointment_pos",
            "bb_salon_appoitments",
        ],
        "unlink": [
            "bb_webex_callcenter",
            "bnb_excel_dashboard",
            "bb_salon_appoitments",
        ],
    },
    "salon.appointment.service": {
        "create": [
            "bnb_excel_dashboard",
            "bb_consultation_form",
            "bb_resource_management",
            "bb_salon_appoitments",
        ],
        "write": [
            "bnb_excel_dashboard",
            "bb_consultation_form",
            "bb_salon_appoitments",
        ],
        "unlink": [
            "bnb_excel_dashboard",
            "bb_salon_appoitments",
        ],
    },
    "salon.appointment.payment": {
        "create": ["bb_webex_callcenter", "bnb_excel_dashboard", "bb_salon_appoitments"],
        "write": ["bb_webex_callcenter", "bnb_excel_dashboard", "bb_salon_appoitments"],
        "unlink": ["bnb_excel_dashboard", "bb_salon_appoitments"],
    },
}


@tagged("post_install", "-at_install")
class TestAppointmentWritePath(TransactionCase):

    def _chain(self, model_name, method_name):
        """The modules overriding one method, outermost first."""
        chain = []
        for klass in self.env[model_name].__class__.__mro__:
            if method_name not in vars(klass):
                continue
            module = klass.__module__
            if not module.startswith("odoo.addons."):
                continue
            addon = module.split(".")[2]
            if addon in EXPECTED[model_name][method_name] and addon not in chain:
                chain.append(addon)
        return chain

    def _installed(self, addons):
        present = set(self.env["ir.module.module"].sudo().search([
            ("name", "in", addons), ("state", "=", "installed"),
        ]).mapped("name"))
        return [addon for addon in addons if addon in present]

    def test_the_override_chains_run_in_the_documented_order(self):
        for model_name, methods in EXPECTED.items():
            for method_name, expected in methods.items():
                with self.subTest(model=model_name, method=method_name):
                    self.assertEqual(
                        self._chain(model_name, method_name),
                        self._installed(expected),
                        "The %s.%s override chain has been reordered. This is "
                        "decided by the module dependency graph, so a new "
                        "'depends' entry is the usual cause. Check that the "
                        "order still satisfies the rules in "
                        "docs/adr/0010-appointment-write-path.md, then update "
                        "this list." % (model_name, method_name),
                    )

    def test_the_chain_is_actually_seven_deep(self):
        """Guard the guard: _chain returning [] would make the test above pass."""
        chain = self._chain("salon.appointment", "create")
        self.assertGreaterEqual(
            len(chain), 5,
            "found only %d create overrides; the MRO walk has broken and the "
            "ordering test above is no longer checking anything" % len(chain),
        )
        self.assertEqual(chain[-1], "bb_salon_appoitments",
                         "the base layer must stay innermost: it allocates the "
                         "reference and is what every other layer wraps")


@tagged("post_install", "-at_install")
class TestAppointmentWritePathBehaviour(TransactionCase):
    """The three ordering rules, pinned by what they produce."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env["res.company"].create({"name": "Write Path Co"})
        cls.env.user.write({"company_ids": [(4, cls.company.id)]})
        config = cls.env["pos.config"].with_company(cls.company).create({
            "name": "Write Path POS",
            "company_id": cls.company.id,
            "payment_method_ids": [(6, 0, [])],
        })
        website = cls.env["website"].create({
            "name": "Write Path Web", "company_id": cls.company.id,
        })
        cls.branch = cls.env["beauty.branch"].create({
            "name": "Write Path Branch",
            "website_id": website.id,
            "company_id": cls.company.id,
            "pos_config_id": config.id,
            "tz": "Australia/Adelaide",
        })

    def _appointment(self, **vals):
        base = {
            "customer_first_name": "Write",
            "customer_last_name": "Path",
            "appointment_date": "2026-09-10",
            "branch_id": self.branch.id,
        }
        base.update(vals)
        return self.env["salon.appointment"].with_context(
            skip_mobile_message_sms=True).create(base)

    def test_a_staff_member_booking_is_matched_to_their_own_contact(self):
        """bb_employee_customer runs before bb_salon_appoitments.

        A beautician booking a treatment for herself is recognised by her work
        email and given her own contact. If the two layers swapped, the base
        layer would see no customer_id and create a second contact for someone
        the salon already employs.
        """
        contact = self.env["res.partner"].create({
            "name": "Staff Booking",
            "email": "staff.booking@example.invalid",
        })
        self.env["hr.employee"].create({
            "name": "Staff Booking",
            "company_id": self.company.id,
            "work_email": "staff.booking@example.invalid",
            "work_contact_id": contact.id,
        })
        appointment = self._appointment(
            customer_email="staff.booking@example.invalid",
            customer_phone="+61400000111",
        )
        self.assertEqual(
            appointment.customer_id, contact,
            "the appointment was given a different contact; the staff match "
            "now runs after the layer that creates one",
        )

    def test_the_booking_is_filed_against_the_branch_company(self):
        """bb_appointment_pos is the only layer that sets company_id.

        Break its branch -> company step and the appointment is filed against
        whichever company happened to be in force instead of the one that owns
        the branch, which is what every company rule and every report scopes
        on.
        """
        appointment = self._appointment(customer_phone="+61400000222")
        self.assertEqual(appointment.company_id, self.company)
        self.assertTrue(
            appointment.appointment_no,
            "no per-company appointment number was allocated",
        )

    def test_the_reference_reaches_the_customer_confirmation(self):
        """The innermost layer's output is used by an almost-outermost one.

        bb_salon_appoitments allocates appointment_ref last on the way in, and
        bb_sms_confirmation reads it second-outermost on the way out. If the
        reference layer ever stopped being innermost, the customer would be
        texted a booking confirmation with a blank reference on it -- the SMS
        would still send, so nothing else would notice.
        """
        appointment = self.env["salon.appointment"].create({
            "customer_first_name": "Reference",
            "customer_last_name": "Carrier",
            "customer_phone": "+61400000333",
            "appointment_date": "2026-09-10",
            "branch_id": self.branch.id,
        })
        self.assertTrue(appointment.appointment_ref)
        self.assertNotEqual(appointment.appointment_ref, "New")

        sms = appointment.message_ids.filtered(
            lambda message: message.message_type == "sms")
        self.assertTrue(sms, "no confirmation SMS was posted for a new booking")
        self.assertIn(
            appointment.appointment_ref, sms[0].body or "",
            "the confirmation text does not carry the appointment reference; "
            "the layer that allocates it is no longer innermost",
        )
