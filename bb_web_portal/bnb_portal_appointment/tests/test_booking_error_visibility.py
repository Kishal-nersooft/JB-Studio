"""Customer-visible failures must not become invented prices or availability."""
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from odoo.tests import TransactionCase, tagged
from odoo.http import Response

from ..controllers import branch as branch_module
from ..controllers import beautician as beautician_module
from .test_payment_first_checkout import PaymentFirstFixture


@tagged('post_install', '-at_install')
class TestBookingErrorVisibility(PaymentFirstFixture, TransactionCase):
    def _branch_details(self, branch_id, error=None):
        fake_request = SimpleNamespace(env=self.env)
        with patch.object(branch_module, 'request', fake_request), \
                patch.object(branch_module, '_json_response', side_effect=lambda data: Response(json.dumps(data), content_type='application/json')):
            if error:
                with patch.object(type(self.env['beauty.branch']), 'search', side_effect=error):
                    response = branch_module.BranchController().get_branch_hours(branch_id=branch_id)
            else:
                response = branch_module.BranchController().get_branch_hours(branch_id=branch_id)
            return json.loads(response.get_data(as_text=True))

    def test_branch_failure_is_not_a_zero_fee_or_default_schedule(self):
        with self.assertLogs(branch_module._logger, level='ERROR'):
            result = self._branch_details(self.branch.id, RuntimeError('Private database failure'))
        self.assertFalse(result['success'])
        self.assertIn('could not be loaded', result['error'])
        self.assertNotIn('Private', result['error'])
        self.assertNotIn('booking_fee', result)
        self.assertNotIn('start_hour', result)

    def test_unknown_branch_is_visible(self):
        for branch_id in [0, 2147483647]:
            result = self._branch_details(branch_id)
            self.assertFalse(result['success'])
            self.assertTrue(result['error'])
            self.assertNotIn('booking_fee', result)

    def test_healthy_branch_fee_and_schedule_are_preserved(self):
        for fee in [0.0, 10.0]:
            self.branch.booking_fee = fee
            result = self._branch_details(self.branch.id)
            self.assertEqual(result['booking_fee'], fee)
            self.assertEqual(result['branch_tz'], self.branch.tz or 'UTC')
            self.assertNotIn('error', result)

    def test_professional_check_failure_does_not_mark_staff_available(self):
        fake_request = SimpleNamespace(env=self.env, make_response=Mock(side_effect=lambda body, **kw: Response(body, headers=kw.get('headers'))))
        with patch.object(beautician_module, 'request', fake_request), \
                patch.object(beautician_module, '_validate_booking_resource_availability', return_value=(True, '')), \
                patch.object(type(self.Intent), '_plan_any_professionals', return_value=([self.staff.id], False)), \
                patch.object(type(self.staff), '_get_online_booking_availability', return_value={'available': True}), \
                patch.object(type(self.env['salon.appointment.service']), 'search', side_effect=RuntimeError('Private availability failure')), \
                self.assertLogs(beautician_module._logger, level='ERROR'):
            result = beautician_module.BeauticianController().get_beauticians_by_services(
                branch_id=str(self.branch.id), service_ids=str(self.product.id),
                selected_date=str(self.day), selected_time='10:00')
            result = json.loads(result.get_data(as_text=True))
        self.assertFalse(result['success'])
        self.assertEqual(result['beauticians'], [])
        self.assertIn('could not be checked', result['error'])
        self.assertNotIn('Private', result['error'])
