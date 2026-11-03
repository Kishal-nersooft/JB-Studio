from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAppointmentPerformanceIndexes(TransactionCase):
    """Pin the 2026-08-08 fix: salon.appointment had no index on branch_id/
    appointment_date, the exact filter every hot pos-api endpoint uses
    (calendar-data, waiting-list, active-breaks, needs-beautician-count,
    upcoming-appointments). Measured via EXPLAIN ANALYZE on a ~700-row
    proxy dataset: sequential scan -> bitmap index scan, 0.685ms -> 0.128ms
    (81% reduction). A single-column branch_id index alone was tested and
    NOT used by the planner at this selectivity, confirming the composite
    index is the smallest fix that's actually effective."""

    def test_branch_date_composite_index_is_installed(self):
        self.env.cr.execute("""
            SELECT indexname, indexdef
              FROM pg_indexes
             WHERE schemaname = current_schema()
               AND tablename = 'salon_appointment'
               AND indexname = 'salon_appointment_branch_id_appointment_date_idx'
        """)
        rows = self.env.cr.fetchall()
        self.assertEqual(len(rows), 1)
        indexdef = rows[0][1]
        self.assertIn("branch_id", indexdef)
        self.assertIn("appointment_date", indexdef)