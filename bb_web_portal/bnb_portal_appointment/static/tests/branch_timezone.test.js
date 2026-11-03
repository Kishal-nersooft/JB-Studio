const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const branchDateTime = require("../src/js/branch_datetime.js");
const moduleRoot = path.resolve(__dirname, "../..");

function withDeviceTimezone(timezone, callback) {
    const previous = process.env.TZ;
    process.env.TZ = timezone;
    try {
        return callback();
    } finally {
        if (previous === undefined) {
            delete process.env.TZ;
        } else {
            process.env.TZ = previous;
        }
    }
}

test("past-slot blocking uses every branch timezone, independent of device timezone", () => {
    const cases = [
        { branchTimezone: "Australia/ACT", instant: "2026-09-21T06:17:00Z", date: "2026-09-21", past: "16:15", future: "16:30" },
        { branchTimezone: "Asia/Colombo", instant: "2026-09-21T06:17:00Z", date: "2026-09-21", past: "11:45", future: "12:00" },
        { branchTimezone: "Europe/London", instant: "2026-09-21T06:17:00Z", date: "2026-09-21", past: "07:15", future: "07:30" },
        { branchTimezone: "America/Los_Angeles", instant: "2026-09-21T18:17:00Z", date: "2026-09-21", past: "11:15", future: "11:30" },
        { branchTimezone: "Pacific/Auckland", instant: "2026-09-21T06:17:00Z", date: "2026-09-21", past: "18:15", future: "18:30" },
    ];
    const deviceTimezones = ["UTC", "Australia/Sydney", "Asia/Colombo", "America/New_York"];

    for (const scenario of cases) {
        for (const deviceTimezone of deviceTimezones) {
            withDeviceTimezone(deviceTimezone, () => {
                const instant = new Date(scenario.instant);
                assert.equal(
                    branchDateTime.isTimeSlotPast(
                        scenario.date,
                        scenario.past,
                        scenario.branchTimezone,
                        instant
                    ),
                    true,
                    `${deviceTimezone} must block the past slot for ${scenario.branchTimezone}`
                );
                assert.equal(
                    branchDateTime.isTimeSlotPast(
                        scenario.date,
                        scenario.future,
                        scenario.branchTimezone,
                        instant
                    ),
                    false,
                    `${deviceTimezone} must keep the future slot for ${scenario.branchTimezone}`
                );
            });
        }
    }
});

test("branch-local dates are used across both sides of the international date boundary", () => {
    const scenarios = [
        { branchTimezone: "Australia/ACT", instant: "2026-09-20T15:45:00Z", date: "2026-09-21", past: "01:30", future: "02:00" },
        { branchTimezone: "Pacific/Honolulu", instant: "2026-09-21T05:45:00Z", date: "2026-09-20", past: "19:30", future: "20:00" },
    ];
    for (const scenario of scenarios) {
        for (const deviceTimezone of ["Pacific/Auckland", "Asia/Colombo", "America/Los_Angeles"]) {
            withDeviceTimezone(deviceTimezone, () => {
                const instant = new Date(scenario.instant);
                assert.equal(
                    branchDateTime.isTimeSlotPast(
                        scenario.date,
                        scenario.past,
                        scenario.branchTimezone,
                        instant
                    ),
                    true
                );
                assert.equal(
                    branchDateTime.isTimeSlotPast(
                        scenario.date,
                        scenario.future,
                        scenario.branchTimezone,
                        instant
                    ),
                    false
                );
            });
        }
    }
});

test("website calendar loads and uses the branch-time helper", () => {
    const manifest = fs.readFileSync(path.join(moduleRoot, "__manifest__.py"), "utf8");
    const bookingSource = fs.readFileSync(path.join(moduleRoot, "static/src/js/base.js"), "utf8");
    assert.ok(
        manifest.indexOf("branch_datetime.js") < manifest.indexOf("base.js"),
        "the branch-time helper must load before the booking calendar"
    );
    assert.match(bookingSource, /BnbBranchDateTime\.isTimeSlotPast/);
});
