/** @odoo-module **/

import { registry } from '@web/core/registry';
import { serializeDateTime, deserializeDateTime } from '@web/core/l10n/dates';
import { calendarView } from '@web/views/calendar/calendar_view';
import { CalendarModel } from '@web/views/calendar/calendar_model';
import { CalendarRenderer } from '@web/views/calendar/calendar_renderer';
import { CalendarCommonRenderer } from '@web/views/calendar/calendar_common/calendar_common_renderer';
import { ganttView } from '@web_gantt/gantt_view';
import { GanttModel } from '@web_gantt/gantt_model';
import { GanttRenderer } from '@web_gantt/gantt_renderer';

// These coordinates are branch wall-clock fields, never actual UTC timestamps.
// Adapt only these two dedicated views; do not change Luxon's global timezone.
export function wallBoundary(value) {
    return serializeDateTime(value.setZone('UTC', { keepLocalTime: true }));
}
export function wallForBrowser(value) {
    if (!value) return value;
    return serializeDateTime(deserializeDateTime(value, { tz: 'UTC' })
        .setZone('default', { keepLocalTime: true }));
}
export function displayRecord(record, startField, endField) {
    return { ...record, [startField]: wallForBrowser(record[startField]),
        [endField]: wallForBrowser(record[endField]) };
}

export class BranchCalendarModel extends CalendarModel {
    computeRangeDomain(data) {
        return [
            [this.fieldMapping.date_start, '<=', wallBoundary(data.range.end)],
            [this.fieldMapping.date_stop, '>=', wallBoundary(data.range.start)],
        ];
    }
    normalizeRecord(rawRecord) {
        const record = super.normalizeRecord(displayRecord(rawRecord,
            this.fieldMapping.date_start, this.fieldMapping.date_stop));
        record.title += ` · ${rawRecord.branch_display_timezone || 'UTC'}`;
        return record;
    }
}
class BranchCommonRenderer extends CalendarCommonRenderer {
    get options() {
        // A single now marker would be misleading across different branch zones.
        return { ...super.options, nowIndicator: false };
    }
}
class BranchCalendarRenderer extends CalendarRenderer {
    static components = { ...CalendarRenderer.components,
        day: BranchCommonRenderer, week: BranchCommonRenderer, month: BranchCommonRenderer };
}
export class BranchGanttModel extends GanttModel {
    _getDomain(metaData) {
        // Preserve user filters, convert only the generated timeline boundaries.
        return super._getDomain({ ...metaData,
            globalStart: metaData.globalStart.setZone('UTC', { keepLocalTime: true }),
            globalStop: metaData.globalStop.setZone('UTC', { keepLocalTime: true }) });
    }
    _parseServerData(metaData, records) {
        return super._parseServerData(metaData, records.map(record => displayRecord(record,
            metaData.dateStartField, metaData.dateStopField)));
    }
}
class BranchGanttRenderer extends GanttRenderer {
    getPill(record) {
        // Service lines own the booking window; these display coordinates are read-only.
        return { ...super.getPill(record), disableDrag: true,
            disableStartResize: true, disableStopResize: true };
    }
}
registry.category('views').add('bnb_branch_calendar', {
    ...calendarView, Model: BranchCalendarModel, Renderer: BranchCalendarRenderer,
});
registry.category('views').add('bnb_branch_gantt', { ...ganttView, Model: BranchGanttModel, Renderer: BranchGanttRenderer });
