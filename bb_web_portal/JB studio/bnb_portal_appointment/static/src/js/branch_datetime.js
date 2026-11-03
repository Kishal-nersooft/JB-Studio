(function (root, factory) {
    const api = factory();
    if (typeof module === "object" && module.exports) {
        module.exports = api;
    }
    root.BnbBranchDateTime = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
    "use strict";

    function getZonedDateTimeParts(now, timeZone) {
        const instant = now instanceof Date ? now : new Date(now);
        let formatter;
        try {
            formatter = new Intl.DateTimeFormat("en-CA-u-nu-latn", {
                timeZone: timeZone || "UTC",
                year: "numeric",
                month: "2-digit",
                day: "2-digit",
                hour: "2-digit",
                minute: "2-digit",
                hourCycle: "h23",
            });
        } catch (error) {
            formatter = new Intl.DateTimeFormat("en-CA-u-nu-latn", {
                timeZone: "UTC",
                year: "numeric",
                month: "2-digit",
                day: "2-digit",
                hour: "2-digit",
                minute: "2-digit",
                hourCycle: "h23",
            });
        }

        const values = {};
        for (const part of formatter.formatToParts(instant)) {
            if (part.type !== "literal") {
                values[part.type] = part.value;
            }
        }
        return {
            date: `${values.year}-${values.month}-${values.day}`,
            hour: Number(values.hour),
            minute: Number(values.minute),
        };
    }

    function isTimeSlotPast(selectedDate, timeString, timeZone, now = new Date()) {
        if (!selectedDate || !timeString) {
            return false;
        }

        const branchNow = getZonedDateTimeParts(now, timeZone);
        if (selectedDate < branchNow.date) {
            return true;
        }
        if (selectedDate > branchNow.date) {
            return false;
        }

        const match = /^(\d{1,2}):(\d{2})$/.exec(timeString);
        if (!match) {
            return false;
        }
        const slotMinutes = Number(match[1]) * 60 + Number(match[2]);
        const currentMinutes = branchNow.hour * 60 + branchNow.minute;
        return slotMinutes <= currentMinutes;
    }

    return {
        getZonedDateTimeParts,
        isTimeSlotPast,
    };
});
