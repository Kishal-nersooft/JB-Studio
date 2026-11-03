// Execute real booking handlers with mocked browser and HTTP dependencies.
// Run: node bnb_portal_appointment/tests/test_booking_errors.mjs
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { test } from "node:test";

const source = readFileSync(new URL("../static/src/js/base.js", import.meta.url), "utf8");
const socialSource = readFileSync(new URL("../static/src/js/social_login_auth.js", import.meta.url), "utf8");
function app(fetch = async () => ({ ok: true, json: async () => ({}) })) {
    const popups = [], events = {}, logs = [], modals = [];
    const body = {appendChild: modal => modals.push(modal), classList: {add() {}, remove() {}}};
    const context = vm.createContext({
        Error, TypeError, SyntaxError, URL, URLSearchParams, FormData, fetch,
        setTimeout() {}, clearTimeout() {},
        console: { error: (...args) => logs.push(args), warn: (...args) => logs.push(args), log() {} },
        sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
        window: { location: { pathname: "/book-online/customer", search: "?branch_id=3", href: "https://example.invalid/book-online/customer?branch_id=3" },
            addEventListener: (name, fn) => { events[name] = fn; }, alert: () => { throw new Error('Native alerts are forbidden'); } },
        document: { readyState: "loading", addEventListener() {}, querySelector: () => null,
            querySelectorAll: () => [], getElementById: () => null,
            body, createElement: () => ({style:{}, querySelectorAll: () => []}), head: { appendChild() {} } },
    });
    vm.runInContext(source, context);
    context.window.bnbShowBookingError = (message) => popups.push(message);
    const api = vm.runInContext('({Utils, BookingState, LocationHandler, DateTimeHandler, CustomerPaymentHandler, reportBookingError})', context);
    return { context, api, popups, events, logs, modals };
}
const reply = data => ({ ok: true, json: async () => data });

test("HTTP errors are visible and reject instead of returning usable booking data", async () => {
    const a = app(async () => ({ ok: false, status: 500 }));
    await assert.rejects(a.api.Utils.fetchJSON('/salon/get-branch-hours'));
    assert.equal(a.popups.length, 1);
    assert.match(a.popups[0], /could not be loaded/);
    assert.ok(a.logs.length);
});
test("Network and malformed JSON failures produce a visible recovery message", async () => {
    for (const error of [new TypeError('Network disconnected'), new SyntaxError('Invalid JSON')]) {
        const a = app(async () => { throw error; });
        await assert.rejects(a.api.Utils.fetchJSON('/salon/get-branch-hours'));
        assert.match(a.popups[0], /check your connection/);
    }
});
test("Failed availability and related-service payloads are never accepted as success", async () => {
    for (const data of [{success:false,error:'Availability could not be checked.'},
        {beauticians:[],error:'Professional availability could not be checked.'},
        {success:false,message:'Related services could not be loaded.'}]) {
        const a = app(async () => reply(data));
        await assert.rejects(a.api.Utils.fetchJSON('/salon/availability'));
        assert.equal(a.popups.length, 1);
    }
});
test("Expected unavailable resource result remains available to the slot handler", async () => {
    const data = {success:true,available:false,error:'Equipment is already booked.'};
    const a = app(async () => reply(data));
    assert.equal(await a.api.Utils.fetchJSON('/salon/check-resource-availability'), data);
    assert.equal(a.popups.length, 0);
});
test("Branch load failure preserves a known fee and stops location navigation", async () => {
    const a = app(async () => { throw new TypeError('Offline'); });
    a.api.BookingState.data.bookingFee = 5;
    const handler = Object.create(a.api.LocationHandler.prototype);
    await handler.selectBranch(null, {dataset:{salonId:'3'}});
    assert.equal(a.api.BookingState.data.bookingFee, 5);
    assert.match(a.context.window.location.href, /customer/);
    assert.equal(a.popups.length, 1);
});
test("Missing fee cannot silently become zero or proceed to booking creation", async () => {
    const calls = [];
    const a = app(async url => { calls.push(url); throw new TypeError('Offline'); });
    const handler = Object.create(a.api.CustomerPaymentHandler.prototype);
    await handler.completeBooking();
    assert.equal(a.api.BookingState.data.bookingFee, null);
    assert.ok(calls.every(url => url.startsWith('/salon/get-branch-hours')));
    assert.equal(a.popups.length, 1);
});
test("Failed resource refresh does not generate assumed calendar times", async () => {
    const a = app(async url => reply(url.startsWith('/salon/get-branch-hours')
        ? {start_hour:9,end_hour:18,branch_tz:'Australia/Sydney'}
        : {success:false,error:'Available times could not be loaded.'}));
    a.api.BookingState.data.selectedServices = [{id:1}];
    const handler = Object.create(a.api.DateTimeHandler.prototype);
    handler.selectedDate = '2026-12-01';
    let generated = 0, cleared = 0;
    handler.generateTimeSlots = () => generated++;
    handler.restoreTimeSelection = () => generated++;
    handler.clearSelectedTime = () => cleared++;
    await handler.loadBranchSlots();
    assert.equal(generated, 0);
    assert.equal(cleared, 1);
    assert.equal(a.popups.length, 1);
});
test("A real zero fee is accepted as known configuration", async () => {
    const a = app(async () => reply({booking_fee:0,branch_tz:'Australia/Sydney'}));
    const handler = Object.create(a.api.CustomerPaymentHandler.prototype);
    assert.equal(await handler.initializeBookingFee(), true);
    assert.equal(a.api.BookingState.data.bookingFee, 0);
    assert.equal(a.popups.length, 0);
});
test("The same propagated failure is displayed once through the themed renderer fallback", () => {
    const a = app();
    a.context.window.bnbShowBookingError = () => { throw new Error('Popup unavailable'); };
    const error = new Error('Failure');
    a.api.reportBookingError('Please try again.', error);
    a.api.reportBookingError('Please try again.', error);
    assert.equal(a.modals.length, 1);
    assert.match(a.modals[0].innerHTML, /Please try again/);
    assert.equal(a.modals[0].style.display, 'flex');
});
test("Unexpected booking failures are visible without suppressing browser errors", () => {
    const a = app();
    a.events.error({error:new TypeError('Private internal error')});
    a.events.unhandledrejection({reason:new Error('Private traceback')});
    assert.equal(a.popups.length, 2);
    assert.ok(a.popups.every(message => !message.includes('Private')));
    a.context.window.location.pathname = '/shop';
    a.events.error({error:new Error('Unrelated')});
    assert.equal(a.popups.length, 2);
});
test("Anonymous social-data absence is normal; transport failure is visible", async () => {
    for (const failed of [false, true]) {
        const a = app(async () => {
            if (failed) throw new TypeError('Offline');
            return reply({result:{success:false,message:'No user data found'}});
        });
        vm.runInContext(socialSource, a.context);
        a.context.document.getElementById = id => id === 'customerForm' ? {} : null;
        const handler = a.context.window.socialLoginHandler;
        await handler.restoreSocialUserData();
        assert.equal(a.popups.length, failed ? 1 : 0);
    }
});
test("Social RPC failures expose expected validation only", async () => {
    for (const name of ['odoo.exceptions.ValidationError', 'builtins.KeyError']) {
        const a = app(async () => reply({error:{data:{name,message:'Checkout expired'}}}));
        vm.runInContext(socialSource, a.context);
        await assert.rejects(a.context.window.socialLoginHandler.fetchSocialUserData(),
            name === 'odoo.exceptions.ValidationError' ? /Checkout expired/ : /could not be loaded/);
    }
});

test("Themed popup escapes messages and defers until the page body is ready", () => {
    const a = app();
    a.api.Utils.showBookingPopup({message:'<script>unsafe</script>', actionText:'Close'});
    assert.match(a.modals[0].innerHTML, /&lt;script&gt;unsafe&lt;\/script&gt;/);
    assert.match(a.modals[0].innerHTML, /booking-availability-popup-card/);
    a.context.document.body = null;
    let ready;
    a.context.document.addEventListener = (name, handler) => { if (name === 'DOMContentLoaded') ready = handler; };
    a.api.Utils.showBookingPopup({message:'Wait for the theme'});
    assert.equal(a.modals.length, 1);
    a.context.document.body = {appendChild: modal => a.modals.push(modal), classList:{add(){},remove(){}}};
    ready();
    assert.match(a.modals[1].innerHTML, /Wait for the theme/);
});
test("Booking and wallet customer flows contain no native alert calls", () => {
    for (const path of ['../static/src/js/base.js','../static/src/js/social_login_auth.js',
        '../static/src/js/category_filter.js','../../payment_nab_gateway/static/src/js/nab_web_wallets.js',
        '../../payment_nab_gateway/static/src/js/nab_payment_form.js','../views/payment_view.xml']) {
        assert.doesNotMatch(readFileSync(new URL(path, import.meta.url), 'utf8'), /\balert\s*\(/);
    }
});

test("Failed-payment result uses the theme immediately or queues until theme initialization", () => {
    const template = readFileSync(new URL('../views/payment_view.xml', import.meta.url), 'utf8');
    const script = template.match(/<script type="text\/javascript">([\s\S]*?Online appointment payment failed[\s\S]*?)<\/script>/)[1];
    for (const ready of [true, false]) {
        const messages = [];
        const window = ready ? {bnbShowBookingError: message => messages.push(message)} : {};
        vm.runInNewContext(script, {window, document:{getElementById: () => ({getAttribute: () => 'Please select a future time.'})}});
        assert.deepEqual(Array.from(ready ? messages : window.bnbPendingBookingErrors), ['Online appointment payment failed: Please select a future time.']);
    }
});

test('Opening booking landing page clears the completed booking before location selection', () => {
    const a = app();
    let reads = 0, clears = 0;
    a.context.window.location.pathname = '/book-online';
    a.context.window.location.search = '';
    a.context.sessionStorage.getItem = () => { reads++; return JSON.stringify({branchId:'3',selectedServices:[{id:1}],paymentData:{payment_option:'full'}}); };
    a.context.sessionStorage.removeItem = () => clears++;
    Object.assign(a.api.BookingState.data,{branchId:'3',selectedServices:[{id:1}],paymentData:{payment_option:'full'},bookingFee:10});
    a.api.BookingState.load();
    assert.equal(reads,0);assert.equal(clears,1);
    assert.equal(a.api.BookingState.data.branchId,null);
    assert.equal(a.api.BookingState.data.selectedServices.length,0);
    assert.equal(a.api.BookingState.data.paymentData,null);
    assert.equal(a.api.BookingState.data.bookingFee,null);
    assert.equal(a.popups.length,0);
});
test('An explicit booking step restores selections without resetting the booking', () => {
    const a = app();
    const saved={branchId:'3',selectedServices:[{id:1}],bookingFee:0,currentStep:'customer'};
    a.context.sessionStorage.getItem=()=>JSON.stringify(saved);
    a.api.BookingState.load();
    assert.equal(a.api.BookingState.data.branchId,'3');
    assert.equal(a.api.BookingState.data.selectedServices.length,1);
    assert.equal(a.api.BookingState.data.bookingFee,0);
    assert.equal(a.popups.length,0);
});
test('Hidden calendar does not request missing location or show an error on initial entry', async () => {
    const calls=[];const a=app(async url=>{calls.push(url);return reply({success:false,error:'Please select a valid location.'});});
    a.api.BookingState.data.branchId=null;
    const handler=Object.create(a.api.DateTimeHandler.prototype);
    handler.selectedDate='2026-12-01';handler.slotLoadKey='previous-location';
    await handler.loadBranchSlots();
    assert.equal(calls.length,0);assert.equal(a.popups.length,0);
    assert.notEqual(handler.slotLoadKey,'previous-location');
});
test('Selecting an invalid location still shows the real error and blocks slot generation', async () => {
    const a=app(async()=>reply({success:false,error:'This location is unavailable. Please select another location.'}));
    a.api.BookingState.data.branchId='999';
    const handler=Object.create(a.api.DateTimeHandler.prototype);
    handler.selectedDate='2026-12-01';let generated=0;
    handler.generateTimeSlots=()=>generated++;handler.clearSelectedTime=()=>{};
    await handler.loadBranchSlots();
    assert.equal(generated,0);assert.equal(a.popups.length,1);
    assert.match(a.popups[0],/location is unavailable/);
});
