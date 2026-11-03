from datetime import date

from odoo.tests import TransactionCase


class TestAppointmentPricingService(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.pricing = cls.env['bb.appointment.pricing.service']

    def test_weekday_has_no_surcharge(self):
        totals = self.pricing.calculate_service_totals(
            100.0,
            appointment_date=date(2026, 8, 14),  # Friday
            saturday_surcharge_percent=10.0,
            sunday_surcharge_percent=15.0,
        )
        self.assertEqual(totals, {
            'services_subtotal': 100.0,
            'surcharge_percent': 0.0,
            'surcharge_amount': 0.0,
            'services_total': 100.0,
            'total_amount': 100.0,
        })

    def test_saturday_surcharge_is_read_as_a_fraction(self):
        """0.1 is 10%, matching what widget="percentage" stores."""
        totals = self.pricing.calculate_service_totals(
            100.0,
            appointment_date=date(2026, 8, 15),
            saturday_surcharge_percent=0.1,
        )
        self.assertEqual(totals['surcharge_percent'], 0.1)
        self.assertEqual(totals['surcharge_amount'], 10.0)
        self.assertEqual(totals['total_amount'], 110.0)

    def test_sunday_surcharge_is_read_as_a_fraction(self):
        totals = self.pricing.calculate_service_totals(
            80.0,
            appointment_date=date(2026, 8, 16),
            sunday_surcharge_percent=0.25,
        )
        self.assertEqual(totals['surcharge_percent'], 0.25)
        self.assertEqual(totals['surcharge_amount'], 20.0)
        self.assertEqual(totals['total_amount'], 100.0)

    def test_one_percent_surcharge_does_not_double_the_booking(self):
        """A branch set to 1% must charge 1%, not 100%.

        0.01 is what the branch form stores for 1%. The previous rule read any
        value up to and including 1 as a fraction, so a branch holding the
        whole number 1 was charged 100% and every Saturday booking doubled.
        """
        totals = self.pricing.calculate_service_totals(
            19.98,
            appointment_date=date(2026, 8, 15),
            saturday_surcharge_percent=0.01,
        )
        self.assertEqual(totals['surcharge_percent'], 0.01)
        self.assertAlmostEqual(totals['surcharge_amount'], 0.1998, places=4)
        self.assertAlmostEqual(totals['total_amount'], 20.1798, places=4)

    def test_empty_values_remain_zero(self):
        totals = self.pricing.calculate_service_totals(None)
        self.assertEqual(totals['services_subtotal'], 0.0)
        self.assertEqual(totals['surcharge_amount'], 0.0)
        self.assertEqual(totals['total_amount'], 0.0)

    def test_surcharge_is_the_fraction_applied_to_the_base_across_values(self):
        """The stored value is a fraction and is applied as-is, at every scale.

        Percentages are given as fractions here (0.01 is 1%) because that is
        what widget="percentage" on the branch form stores. 1.0 therefore
        means 100% and must behave like it, rather than being reinterpreted.
        """
        dates = [
            date(2026, 8, 14),  # Friday
            date(2026, 8, 15),  # Saturday
            date(2026, 8, 16),  # Sunday
            None,
        ]
        for base_total in [0.0, 0.01, 42.98, 100.0, 999.99]:
            for saturday_fraction in [0.0, 0.005, 0.01, 0.05, 0.125]:
                for sunday_fraction in [0.0, 0.01, 0.08, 0.1, 0.175]:
                    for appointment_date in dates:
                        with self.subTest(
                            base_total=base_total,
                            saturday_fraction=saturday_fraction,
                            sunday_fraction=sunday_fraction,
                            appointment_date=appointment_date,
                        ):
                            expected_fraction = 0.0
                            if appointment_date:
                                weekday = appointment_date.weekday()
                                if weekday == 5:
                                    expected_fraction = saturday_fraction or 0.0
                                elif weekday == 6:
                                    expected_fraction = sunday_fraction or 0.0
                            expected_surcharge = (
                                base_total * expected_fraction
                                if expected_fraction else 0.0
                            )
                            expected_total = base_total + expected_surcharge

                            totals = self.pricing.calculate_service_totals(
                                base_total,
                                appointment_date=appointment_date,
                                saturday_surcharge_percent=saturday_fraction,
                                sunday_surcharge_percent=sunday_fraction,
                            )
                            self.assertEqual(
                                totals,
                                {
                                    'services_subtotal': base_total,
                                    'surcharge_percent': expected_fraction,
                                    'surcharge_amount': expected_surcharge,
                                    'services_total': expected_total,
                                    'total_amount': expected_total,
                                },
                            )

    def test_appointment_compute_delegates_without_changing_field_results(self):
        # Fractions, as widget="percentage" stores them: 0.1 is 10%.
        branch = self.env['beauty.branch'].new({
            'saturday_surcharge_percent': 0.1,
            'sunday_surcharge_percent': 0.15,
        })
        service_line = self.env['salon.appointment.service'].new({
            'base_price': 90.0,
            'beautician_addon_price': 10.0,
        })
        service_line._compute_total_price()
        appointment = self.env['salon.appointment'].new({
            'appointment_date': date(2026, 8, 15),
            'branch_id': branch,
            'service_line_ids': service_line,
        })

        appointment._compute_totals()

        self.assertEqual(appointment.services_subtotal, 100.0)
        self.assertEqual(appointment.surcharge_percent, 0.1)
        self.assertEqual(appointment.surcharge_amount, 10.0)
        self.assertEqual(appointment.services_total, 110.0)
        self.assertEqual(appointment.total_amount, 110.0)

    def test_checkout_full_payment_preserves_legacy_values(self):
        totals = self.pricing.calculate_checkout_totals(
            service_total=100.0,
            booking_fee=10.0,
            discount_amount=15.0,
            payment_option='full',
        )
        self.assertEqual(totals, {
            'discount_amount': 15.0,
            'total_before_discount': 110.0,
            'total_after_discount': 95.0,
            'payment_amount': 95.0,
        })

    def test_checkout_half_payment_preserves_legacy_values(self):
        totals = self.pricing.calculate_checkout_totals(
            service_total=100.0,
            booking_fee=10.0,
            discount_amount=15.0,
            payment_option='half',
        )
        self.assertEqual(totals['payment_amount'], 47.5)

    def test_checkout_discount_is_capped_at_gross_total(self):
        totals = self.pricing.calculate_checkout_totals(
            service_total=40.0,
            booking_fee=10.0,
            discount_amount=75.0,
            payment_option='half',
        )
        self.assertEqual(totals['discount_amount'], 50.0)
        self.assertEqual(totals['total_after_discount'], 0.0)
        self.assertEqual(totals['payment_amount'], 0.0)

    def test_checkout_matches_both_legacy_controller_formulas(self):
        for service_total in [0.0, 0.01, 42.98, 100.0, 999.99]:
            for booking_fee in [0.0, 0.01, 5.0, 25.5]:
                gross = service_total + booking_fee
                for discount_amount in [0.0, 0.01, gross / 2, gross, gross + 10.0]:
                    for payment_option in ['full', 'half', 'unexpected']:
                        with self.subTest(
                            service_total=service_total,
                            booking_fee=booking_fee,
                            discount_amount=discount_amount,
                            payment_option=payment_option,
                        ):
                            legacy_discount = min(discount_amount, gross)
                            legacy_after_discount = max(
                                gross - legacy_discount,
                                0.0,
                            )
                            legacy_payment = (
                                legacy_after_discount / 2
                                if payment_option == 'half'
                                else legacy_after_discount
                            )
                            totals = self.pricing.calculate_checkout_totals(
                                service_total,
                                booking_fee=booking_fee,
                                discount_amount=discount_amount,
                                payment_option=payment_option,
                            )
                            self.assertEqual(totals, {
                                'discount_amount': legacy_discount,
                                'total_before_discount': gross,
                                'total_after_discount': legacy_after_discount,
                                'payment_amount': legacy_payment,
                            })

    def test_half_deposit_allocation_preserves_balance(self):
        allocation = self.pricing.calculate_deposit_allocation(
            service_total=100.0,
            discount_amount=10.0,
            deposit_amount=45.0,
            payment_option='half',
        )
        self.assertEqual(allocation, {
            'net_service_total': 90.0,
            'balance_due': 45.0,
            'credit_amount': 0.0,
        })

    def test_deposit_surplus_preserves_customer_credit(self):
        allocation = self.pricing.calculate_deposit_allocation(
            service_total=80.0,
            discount_amount=10.0,
            deposit_amount=100.0,
            payment_option='half',
        )
        self.assertEqual(allocation, {
            'net_service_total': 70.0,
            'balance_due': 0.0,
            'credit_amount': 30.0,
        })

    def test_full_payment_preserves_forced_zero_compatibility_rule(self):
        allocation = self.pricing.calculate_deposit_allocation(
            service_total=100.0,
            discount_amount=0.0,
            deposit_amount=25.0,
            payment_option='full',
        )
        self.assertEqual(allocation, {
            'net_service_total': 100.0,
            'balance_due': 0.0,
            'credit_amount': 0.0,
        })

    def test_deposit_allocation_matches_legacy_controller_formula(self):
        for service_total in [0.0, 0.01, 42.98, 100.0, 999.99]:
            for discount_amount in [0.0, 0.01, 25.0, 100.0, 1200.0]:
                for deposit_amount in [0.0, 0.01, 21.49, 100.0, 1500.0]:
                    for payment_option in ['half', 'full', 'unexpected']:
                        with self.subTest(
                            service_total=service_total,
                            discount_amount=discount_amount,
                            deposit_amount=deposit_amount,
                            payment_option=payment_option,
                        ):
                            legacy_net = max(
                                service_total - discount_amount,
                                0.0,
                            )
                            legacy_balance = max(
                                legacy_net - deposit_amount,
                                0.0,
                            )
                            legacy_credit = max(
                                deposit_amount - legacy_net,
                                0.0,
                            )
                            if payment_option == 'full':
                                legacy_balance = 0.0
                                legacy_credit = 0.0

                            allocation = self.pricing.calculate_deposit_allocation(
                                service_total=service_total,
                                discount_amount=discount_amount,
                                deposit_amount=deposit_amount,
                                payment_option=payment_option,
                            )
                            self.assertEqual(allocation, {
                                'net_service_total': legacy_net,
                                'balance_due': legacy_balance,
                                'credit_amount': legacy_credit,
                            })

    def test_negative_deposit_surplus_preserves_legacy_value(self):
        surplus = self.pricing.calculate_deposit_surplus(
            deposit_total=-20.0,
            service_total=15.98,
        )
        self.assertEqual(surplus, 4.02)

    def test_non_negative_deposit_total_has_no_surplus(self):
        self.assertEqual(
            self.pricing.calculate_deposit_surplus(20.0, 15.0),
            0.0,
        )

    def test_deposit_surplus_matches_legacy_pos_formula(self):
        for deposit_total in [-1500.0, -100.0, -20.0, -0.01, 0.0, 20.0]:
            for service_total in [-100.0, 0.0, 0.01, 15.98, 100.0, 2000.0]:
                with self.subTest(
                    deposit_total=deposit_total,
                    service_total=service_total,
                ):
                    legacy_surplus = 0.0
                    if deposit_total < 0.0:
                        legacy_surplus = max(
                            abs(deposit_total) - max(service_total, 0.0),
                            0.0,
                        )
                    self.assertEqual(
                        self.pricing.calculate_deposit_surplus(
                            deposit_total,
                            service_total,
                        ),
                        legacy_surplus,
                    )

    def test_change_credit_availability_matches_legacy_pos_formula(self):
        for amount_return in [-10.0, 0.0, 0.01, 5.0, 100.0]:
            for deposit_surplus in [-10.0, 0.0, 0.01, 4.02, 150.0]:
                for credited_amount in [0.0, 0.01, 4.02, 100.0, 200.0]:
                    with self.subTest(
                        amount_return=amount_return,
                        deposit_surplus=deposit_surplus,
                        credited_amount=credited_amount,
                    ):
                        legacy_credit = max(
                            amount_return,
                            deposit_surplus,
                            0.0,
                        )
                        legacy_change = max(
                            legacy_credit - credited_amount,
                            0.0,
                        )
                        self.assertEqual(
                            self.pricing.calculate_change_credit_availability(
                                amount_return,
                                deposit_surplus,
                                credited_amount,
                            ),
                            {
                                'available_credit': legacy_credit,
                                'available_change': legacy_change,
                            },
                        )

    def test_partial_forfeit_split_preserves_remaining_credit(self):
        self.assertEqual(
            self.pricing.calculate_forfeit_split(100.0, 25.0),
            {
                'forfeit_amount': 25.0,
                'remaining_amount': 75.0,
            },
        )

    def test_forfeit_split_caps_requested_amount(self):
        self.assertEqual(
            self.pricing.calculate_forfeit_split(100.0, 125.0),
            {
                'forfeit_amount': 100.0,
                'remaining_amount': 0.0,
            },
        )

    def test_forfeit_split_matches_legacy_wizard_formula(self):
        for deposit_amount in [0.0, 0.01, 10.0, 100.0, 999.99]:
            for requested_amount in [-25.0, 0.0, 0.01, 25.0, 100.0, 1200.0]:
                with self.subTest(
                    deposit_amount=deposit_amount,
                    requested_amount=requested_amount,
                ):
                    legacy_forfeit = min(
                        max(requested_amount, 0.0),
                        deposit_amount,
                    )
                    legacy_remaining = max(
                        deposit_amount - legacy_forfeit,
                        0.0,
                    )
                    self.assertEqual(
                        self.pricing.calculate_forfeit_split(
                            deposit_amount,
                            requested_amount,
                        ),
                        {
                            'forfeit_amount': legacy_forfeit,
                            'remaining_amount': legacy_remaining,
                        },
                    )

    def test_payment_status_evidence_precedence_matches_legacy_rules(self):
        expected_statuses = {
            (False, False): 'unpaid',
            (False, True): 'partial',
            (True, False): 'paid',
            (True, True): 'paid',
        }
        for evidence, expected_status in expected_statuses.items():
            with self.subTest(
                has_full_payment_evidence=evidence[0],
                has_partial_payment_evidence=evidence[1],
            ):
                self.assertEqual(
                    self.pricing.determine_payment_status(*evidence),
                    expected_status,
                )

    def test_balance_and_credit_preserves_representative_pos_values(self):
        self.assertEqual(
            self.pricing.calculate_balance_and_credit(100.0, 40.0),
            {'balance_due': 60.0, 'credit_amount': 0.0},
        )
        self.assertEqual(
            self.pricing.calculate_balance_and_credit(40.0, 100.0),
            {'balance_due': 0.0, 'credit_amount': 60.0},
        )
        self.assertEqual(
            self.pricing.calculate_balance_and_credit(42.98, 42.98),
            {'balance_due': 0.0, 'credit_amount': 0.0},
        )

    def test_balance_and_credit_matches_all_pos_legacy_formulas(self):
        for service_total in [-25.0, 0.0, 0.01, 15.98, 100.0, 999.99]:
            for applied_amount in [-10.0, 0.0, 0.01, 4.02, 100.0, 1200.0]:
                with self.subTest(
                    service_total=service_total,
                    applied_amount=applied_amount,
                ):
                    self.assertEqual(
                        self.pricing.calculate_balance_and_credit(
                            service_total,
                            applied_amount,
                        ),
                        {
                            'balance_due': max(
                                service_total - applied_amount,
                                0.0,
                            ),
                            'credit_amount': max(
                                applied_amount - service_total,
                                0.0,
                            ),
                        },
                    )

    def test_deposit_redemption_state_evidence_matches_legacy_rules(self):
        expected_states = {
            (False, False): 'active',
            (True, False): 'partial',
            (False, True): 'redeemed',
            (True, True): 'redeemed',
        }
        for evidence, expected_state in expected_states.items():
            with self.subTest(
                has_redemption_evidence=evidence[0],
                has_full_redemption_evidence=evidence[1],
            ):
                self.assertEqual(
                    self.pricing.determine_deposit_redemption_state(*evidence),
                    expected_state,
                )
