from datetime import datetime, time

import pytz

from odoo import models, fields

from .branch import _TZ_SELECTION


class ResCompany(models.Model):
    _inherit = 'res.company'

    reporting_tz = fields.Selection(
        selection=_TZ_SELECTION,
        string='Reporting Time Zone',
        default='Australia/Adelaide',
        help="The timezone every dashboard and report reads its dates in. Day, "
             "week, month and custom ranges all take their start and end from "
             "this, so the whole business is reported on one clock however many "
             "timezones its branches sit in.\n\n"
             "Branches keep their own timezone for appointment times, reminders "
             "and the portal. This is only about reporting.",
    )

    def _bb_reporting_tz(self):
        """Return the timezone reporting reads its dates in.

        Falls back to the working-hours calendar and then the company contact,
        which is where the rest of the system looks, and finally to UTC. Those
        two are unreliable - every company's calendar still reads Asia/Colombo
        from setup - so the field above is what should actually be set.
        """
        self.ensure_one()
        tz_name = (
            self.reporting_tz
            or self.resource_calendar_id.tz
            or self.partner_id.tz
            or 'UTC'
        )
        try:
            pytz.timezone(tz_name)
        except pytz.UnknownTimeZoneError:
            return 'UTC'
        return tz_name

    def _bb_reporting_window_utc(self, date_from, date_to):
        """Turn a local date range into the UTC instants that bound it.

        Reporting asks about local days, but the datetimes are stored in UTC,
        so the boundaries are converted rather than the column. Comparing
        `date_order >= start AND date_order < end` keeps the index on
        pos_order.date_order usable; wrapping the column in AT TIME ZONE would
        not, and there are around sixty of those comparisons.

        `date_to` is inclusive, so the returned end is local midnight after it.
        """
        self.ensure_one()
        tz = pytz.timezone(self._bb_reporting_tz())
        start_date = fields.Date.to_date(date_from)
        end_date = fields.Date.to_date(date_to)
        # localize() rather than replace(tzinfo=...): only localize applies the
        # offset in force on that date, which matters either side of a daylight
        # saving change.
        local_start = tz.localize(datetime.combine(start_date, time.min))
        local_end = tz.localize(
            datetime.combine(fields.Date.add(end_date, days=1), time.min)
        )
        return (
            local_start.astimezone(pytz.UTC).replace(tzinfo=None),
            local_end.astimezone(pytz.UTC).replace(tzinfo=None),
        )
