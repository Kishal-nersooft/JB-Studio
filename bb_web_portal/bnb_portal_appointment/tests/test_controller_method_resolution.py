import inspect
import re

from odoo.tests import TransactionCase, tagged

from odoo.addons.bnb_portal_appointment.controllers.branch import BranchController

MODULE_PREFIX = 'odoo.addons.bnb_portal_appointment'
SELF_CALL = re.compile(r"self\.(_\w+)\(")


@tagged('post_install', '-at_install')
class TestBookingControllerResolution(TransactionCase):
    """A booking controller must own every helper it calls.

    The controllers here are separate classes that answer in JSON, and one of
    them called a `_json_response` belonging to another class. Every one of
    its return paths raised AttributeError -- including the one inside its own
    error handler -- so `/salon/get-branch-hours` could not answer at all. The
    website hid that behind a catch and fell back to a zero booking fee and a
    UTC timezone, which is why it went unnoticed.
    """

    def _unresolved(self, controller):
        called = set()
        for klass in controller.__mro__:
            if not klass.__module__.startswith(MODULE_PREFIX):
                continue
            try:
                called.update(SELF_CALL.findall(inspect.getsource(klass)))
            except (OSError, TypeError):
                continue
        return sorted(name for name in called if not hasattr(controller, name))

    def test_the_branch_controller_can_answer(self):
        missing = self._unresolved(BranchController)
        self.assertFalse(
            missing,
            f"BranchController calls helpers it does not have: {', '.join(missing)}")

    def test_every_booking_controller_can_answer(self):
        from odoo import http

        def descendants(cls):
            for sub in cls.__subclasses__():
                yield sub
                yield from descendants(sub)

        broken = {}
        for controller in descendants(http.Controller):
            if controller.__module__.startswith(MODULE_PREFIX):
                missing = self._unresolved(controller)
                if missing:
                    broken[controller.__name__] = missing
        self.assertFalse(broken, f"controllers calling helpers they lack: {broken}")

    def test_the_json_helper_is_shared_rather_than_borrowed(self):
        from odoo.addons.bnb_portal_appointment.controllers import booking_helpers, branch

        self.assertTrue(hasattr(booking_helpers, '_json_response'))
        source = inspect.getsource(branch)
        self.assertNotIn('self._json_response(', source)
        self.assertIn('_json_response(', source)
