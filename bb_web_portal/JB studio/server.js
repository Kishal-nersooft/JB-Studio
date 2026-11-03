// Local preview server for the Browz & Beauty booking portal.
//
// Serves the HTML pages in ./pages, the module's CSS/JS/images in
// ./bnb_portal_appointment/static, and answers the /salon/* requests that
// base.js makes with sample data from ./mock-data.js instead of Odoo.
//
// Pages, partials, styles and mock data are re-read on every request, so
// edit a file and refresh the browser to see the change.

const http = require('http');
const fs = require('fs');
const path = require('path');
const { URL } = require('url');

const ROOT = __dirname;
const PAGES = path.join(ROOT, 'pages');
const PARTIALS = path.join(PAGES, 'partials');
const PORT = Number(process.env.PORT) || 8080;

let sass = null;
try {
    sass = require('sass');
} catch {
    console.warn('The "sass" package is missing: run "npm install" in this folder. .scss files will not load until then.');
}

const MIME = {
    '.html': 'text/html; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.scss': 'text/css; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.webp': 'image/webp',
    '.svg': 'image/svg+xml',
    '.gif': 'image/gif',
    '.ico': 'image/x-icon',
    '.woff2': 'font/woff2',
};

// Bookings "paid" during this session, so the result page can show them.
const bookings = new Map();
let bookingSequence = 0;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function loadData() {
    const file = require.resolve('./mock-data.js');
    delete require.cache[file];
    return require(file);
}

const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[char]));

const money = value => `$${(Number(value) || 0).toFixed(2)}`;

function fill(template, values) {
    return template.replace(/\{\{(\w+)\}\}/g, (match, key) => (key in values ? values[key] : match));
}

function render(page, values = {}, flags = {}) {
    let html = fs.readFileSync(path.join(PAGES, page), 'utf8');
    // <!-- include: name --> pulls in pages/partials/name.html (nested includes allowed)
    for (let depth = 0; depth < 10 && html.includes('<!-- include:'); depth++) {
        html = html.replace(/<!-- include: ([\w-]+) -->/g, (match, name) =>
            fs.readFileSync(path.join(PARTIALS, `${name}.html`), 'utf8'));
    }
    // <!-- if:flag --> ... <!-- endif:flag --> is kept only when flags[flag] is true
    // (blocks may be nested, so repeat until none are left)
    const ifBlock = /[ \t]*<!-- if:(\w+) -->([\s\S]*?)<!-- endif:\1 -->\n?/g;
    while (ifBlock.test(html)) {
        html = html.replace(ifBlock, (match, flag, body) => (flags[flag] ? body : ''));
    }
    return fill(html, values);
}

function partial(name, values) {
    return fill(fs.readFileSync(path.join(PARTIALS, `${name}.html`), 'utf8'), values);
}

function send(res, status, body, type = MIME['.html']) {
    res.writeHead(status, { 'Content-Type': type, 'Cache-Control': 'no-store' });
    res.end(body);
}

const sendJSON = (res, data) => send(res, 200, JSON.stringify(data), MIME['.json']);

function redirect(res, location) {
    res.writeHead(302, { Location: location });
    res.end();
}

function readBody(req) {
    return new Promise(resolve => {
        const chunks = [];
        req.on('data', chunk => chunks.push(chunk));
        req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    });
}

// Parses url-encoded and multipart (FormData) bodies; text fields only.
async function readForm(req) {
    const body = await readBody(req);
    const type = req.headers['content-type'] || '';
    const boundary = /boundary=(?:"([^"]+)"|([^;]+))/.exec(type);
    if (!boundary) return Object.fromEntries(new URLSearchParams(body));
    const fields = {};
    for (const part of body.split(`--${boundary[1] || boundary[2]}`)) {
        const name = /name="([^"]*)"/.exec(part);
        const split = part.indexOf('\r\n\r\n');
        if (!name || split === -1) continue;
        fields[name[1]] = part.slice(split + 4).replace(/\r\n$/, '');
    }
    return fields;
}

function durationHours(display) {
    const hours = /(\d+)\s*h/.exec(display);
    const minutes = /(\d+)\s*min/.exec(display);
    return (hours ? Number(hours[1]) : 0) + (minutes ? Number(minutes[1]) / 60 : 0);
}

function allServices(data) {
    return data.serviceCategories.flatMap(category => category.products.map(product => ({
        ...product, category_id: category.id, parent_id: category.parent_id,
    })));
}

function findBranch(data, id) {
    return data.branches.find(branch => String(branch.id) === String(id));
}

function surchargePercent(branch, isoDate) {
    const day = new Date(isoDate).getDay();
    const fraction = day === 6 ? branch.saturday_surcharge_percent : (day === 0 ? branch.sunday_surcharge_percent : 0);
    return (fraction || 0) * 100;
}

// ---------------------------------------------------------------------------
// Pages
// ---------------------------------------------------------------------------
function bookOnlinePage(res, url, step) {
    const data = loadData();
    const branchId = url.searchParams.get('branch_id');
    const allowed = ['location', 'service', 'date', 'beautician', 'customer', 'payment', 'confirmation'];
    if (step && !allowed.includes(step)) return redirect(res, branchId ? `/book-online?branch_id=${branchId}` : '/book-online');
    if (step && step !== 'location' && !branchId) return redirect(res, '/book-online');

    const branch = branchId ? findBranch(data, branchId) : null;
    if (branchId && !branch) return redirect(res, '/book-online');

    // Odoo leaves the timezone blank until a salon is chosen.
    const values = { BRANCH_TZ: '' };
    if (!branch) {
        values.LOCATION_CARDS = data.branches.map(b => partial('location-card', {
            id: esc(b.id), name: esc(b.name), city: esc(b.city), state: esc(b.state), image: esc(b.image),
        })).join('\n');
    } else {
        values.BRANCH_NAME = esc(branch.name);
        values.BRANCH_IMAGE = esc(branch.image);
        values.BRANCH_ADDRESS = esc([branch.street, branch.city, branch.country, branch.zip].filter(Boolean).join(', '));
        values.BRANCH_SHORT_ADDRESS = esc([branch.street, branch.city].filter(Boolean).join(', '));
        values.BRANCH_TZ = esc(branch.tz);
        values.PARENT_OPTIONS = data.parentCategories
            .map(parent => `<option value="${esc(parent.id)}">${esc(parent.name)}</option>`).join('\n');
        values.CATEGORY_TABS = data.serviceCategories.map(category => `
                            <button class="service-tab"
                                    data-category-id="${esc(category.id)}"
                                    data-parent-id="${esc(category.parent_id)}"
                                    role="tab">
                                ${esc(category.name)}
                            </button>`).join('');
        values.SERVICE_CARDS = allServices(data).map(service => partial('service-card', {
            id: esc(service.id),
            sold_quantity: esc(service.sold_quantity || 0),
            parent_id: esc(service.parent_id),
            category_id: esc(service.category_id),
            name: esc(service.name),
            formatted_price: esc(money(service.price)),
            duration: esc(service.duration),
            description: esc(service.description || ''),
        })).join('\n');
    }
    send(res, 200, render('book-online.html', values, { location: !branch, services: !!branch, branch: !!branch }));
}

function homePage(res) {
    const data = loadData();
    send(res, 200, render('home.html', {
        BRANCH_OPTIONS: data.branches.map(b => `<option value="${esc(b.id)}">${esc(b.name)}</option>`).join('\n'),
    }));
}

function giftVoucherPage(res) {
    const amounts = loadData().giftVoucherAmounts;
    send(res, 200, render('gift-voucher.html', {
        FIRST_AMOUNT: esc(amounts[0]),
        AMOUNT_OPTIONS: amounts.map((amount, i) => `<div class="col-4"><label class="bnb-gift-amount"><input type="radio" name="amount_fixed" value="${esc(amount)}"${i === 0 ? ' checked="checked"' : ''}/> $${esc(amount)}</label></div>`).join(''),
    }));
}

function messagePage(res, title, message) {
    send(res, 200, render('message.html', { TITLE: esc(title), MESSAGE: esc(message) }));
}

function checkoutResultPage(res, id) {
    const booking = bookings.get(id);
    if (!booking) return messagePage(res, 'Booking not found', 'This preview only remembers bookings made since the server was started.');
    const [year, month, day] = booking.date.split('-');
    send(res, 200, render('checkout-result.html', {
        BRANCH_NAME: esc(booking.branch.name),
        BRANCH_CITY: esc(booking.branch.city),
        DATE: esc(`${day}/${month}/${year}`),
        TIME: esc(booking.time),
        CUSTOMER_NAME: esc(booking.customerName),
        CUSTOMER_EMAIL: esc(booking.customerEmail),
        SERVICE_LINES: booking.lines.map(line => `
                                    <div class="spc-service-line">
                                        <div>
                                            <span class="spc-detail-value">${esc(line.name)}</span>
                                            ${line.staff ? `<span class="spc-detail-meta"> with ${esc(line.staff)}</span>` : ''}
                                        </div>
                                        <span class="spc-service-price">${esc(money(line.price))}</span>
                                    </div>`).join(''),
        PAYMENT_TYPE_ROW: booking.paymentOption === 'half' ? `
                                    <div class="spc-payment-row">
                                        <span>Payment Type</span>
                                        <span class="spc-badge spc-badge-pending" style="font-size: 11px; padding: 3px 10px;">Pay advance (50% deposit)</span>
                                    </div>` : '',
        AMOUNT_PAID: esc(money(booking.amount)),
        REMAINING_ROW: booking.paymentOption === 'half' ? `
                                    <div class="spc-payment-row spc-payment-row-muted">
                                        <span>Remaining Balance (pay at salon)</span>
                                        <span>${esc(money(booking.totalAfterDiscount - booking.amount))}</span>
                                    </div>` : '',
        REFERENCE: esc(booking.reference),
    }));
}

// ---------------------------------------------------------------------------
// Mock /salon/* API (same response shapes as the Odoo controllers)
// ---------------------------------------------------------------------------
async function api(req, res, url) {
    const data = loadData();
    const q = Object.fromEntries(url.searchParams);
    const form = req.method === 'POST' ? await readForm(req) : {};
    const branch = findBranch(data, q.branch_id || form.branch_id || form.salon_id);
    const services = allServices(data);

    switch (url.pathname) {
    case '/salon/get-branch-hours':
        if (!branch) return sendJSON(res, { success: false, error: 'Please select a valid location.' });
        return sendJSON(res, {
            start_hour: branch.start_hour,
            end_hour: branch.end_hour,
            booking_fee: branch.booking_fee,
            branch_name: branch.name,
            branch_tz: branch.tz,
            saturday_surcharge_percent: branch.saturday_surcharge_percent,
            sunday_surcharge_percent: branch.sunday_surcharge_percent,
        });

    case '/salon/get-resource-unavailable-slots':
        return sendJSON(res, { success: true, unavailable_start_hours: data.unavailableStartHours });

    case '/salon/check-resource-availability': {
        const available = !data.unavailableStartHours.includes(Number(q.start_hour));
        return sendJSON(res, { success: true, available, error: available ? '' : 'This time is already booked for the selected service.' });
    }

    case '/salon/get-beauticians-by-services':
    case '/salon/get-beauticians': {
        const toCard = b => ({ id: b.id, name: b.name, price: b.price, image: b.image || null, reason: b.reason });
        return sendJSON(res, {
            beauticians: data.beauticians.filter(b => !b.busy).map(toCard),
            busy_beauticians: data.beauticians.filter(b => b.busy).map(toCard),
            message: '',
            any_professional_available: true,
            waiting_list_available: false,
        });
    }

    case '/salon/get-all-related-products':
    case '/salon/get-related-services': {
        const selected = JSON.parse(form.service_ids || '[]').map(String);
        const relatedIds = [...new Set(selected.flatMap(id => data.relatedServices[id] || []))]
            .filter(id => !selected.includes(String(id)));
        const related = relatedIds.map(id => services.find(s => s.id === id)).filter(Boolean).map(s => ({
            id: s.id,
            name: s.name,
            duration: durationHours(s.duration),
            duration_display: s.duration,
            base_price: s.price,
            formatted_price: money(s.price),
            formatted_total_price: money(s.price),
            addon_price: 0,
            description: s.description || '',
        }));
        if (url.pathname === '/salon/get-all-related-products') {
            return sendJSON(res, { success: true, related_products: related, message: `Found ${related.length} related products` });
        }
        const beautician = data.beauticians.find(b => String(b.id) === String(form.beautician_id));
        return sendJSON(res, { success: true, related_services: related, beautician_name: beautician ? beautician.name : '' });
    }

    case '/salon/promo/validate': {
        const code = data.promoCodes[(form.promo_code || '').trim().toUpperCase()];
        if (!code) return sendJSON(res, { valid: false, message: 'Invalid gift/discount code' });
        const total = Number(form.total_amount) || 0;
        const discount = Math.min(total, code.amount ?? total * code.percent / 100);
        return sendJSON(res, { valid: true, message: code.message, discount_amount: Number(discount.toFixed(2)) });
    }

    case '/salon/create-booking-payment':
    case '/salon/complete-booking': {
        if (!branch) return sendJSON(res, { success: false, error: 'Invalid branch' });
        const ids = JSON.parse(form.selected_services || '[]').map(String);
        const staffIds = Object.values(JSON.parse(form.selected_beauticians || '{}'));
        const staff = data.beauticians.find(b => String(b.id) === String(staffIds[0]));
        const addon = staff ? Number(String(staff.price).replace(/[^\d.]/g, '')) || 0 : 0;
        const timeslots = JSON.parse(form.selected_timeslots || '{}');
        const lines = ids.map(id => services.find(s => String(s.id) === id)).filter(Boolean)
            .map(s => ({ name: s.name, price: s.price + addon, staff: staff ? staff.name : '' }));
        const subtotal = lines.reduce((sum, line) => sum + line.price, 0);
        const surcharge = subtotal * surchargePercent(branch, form.appointment_date) / 100;
        const id = String(++bookingSequence);
        bookings.set(id, {
            branch,
            date: form.appointment_date,
            time: (Object.values(timeslots)[0] || {}).time || '',
            customerName: `${form.first_name || ''} ${form.last_name || ''}`.trim(),
            customerEmail: form.email || '',
            lines,
            paymentOption: form.payment_option || 'full',
            amount: Number(form.amount_to_pay) || 0,
            totalAfterDiscount: subtotal + surcharge + (branch.booking_fee || 0) - (Number(form.discount_amount) || 0),
            reference: `BB/${new Date().getFullYear()}/${id.padStart(4, '0')}`,
        });
        // The real portal sends the customer to the secure card-payment page
        // first; this preview skips straight to the "paid" result page.
        return sendJSON(res, { success: true, redirect_url: `/salon/checkout-result/${id}` });
    }

    default:
        return sendJSON(res, { success: false, error: `The local preview has no sample data for ${url.pathname}` });
    }
}

// ---------------------------------------------------------------------------
// Static files (.scss is compiled to CSS on the fly)
// ---------------------------------------------------------------------------
function staticFile(res, pathname) {
    const file = path.normalize(path.join(ROOT, decodeURIComponent(pathname)));
    if (!file.startsWith(ROOT + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
        return send(res, 404, 'Not found', 'text/plain');
    }
    const ext = path.extname(file).toLowerCase();
    if (ext === '.scss') {
        if (!sass) return send(res, 200, '/* run "npm install" to enable .scss */', MIME['.css']);
        try {
            return send(res, 200, sass.compile(file, { style: 'expanded' }).css, MIME['.css']);
        } catch (error) {
            console.error(`\nSCSS error in ${path.relative(ROOT, file)}:\n${error.message}\n`);
            return send(res, 200, `/* SCSS error: ${error.message.replace(/\*\//g, '* /')} */`, MIME['.css']);
        }
    }
    send(res, 200, fs.readFileSync(file), MIME[ext] || 'application/octet-stream');
}

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------
const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, `http://${req.headers.host}`);
    const p = url.pathname;
    try {
        if (p === '/' || p === '/bnb-home' || p === '/custom-home') return homePage(res);
        const booking = /^\/book-online(?:\/\d+)?(?:\/(\w+))?\/?$/.exec(p);
        if (booking) return bookOnlinePage(res, url, booking[1]);
        if (p === '/gift-voucher') return giftVoucherPage(res);
        if (p === '/gift-voucher/submit') return messagePage(res, 'Gift voucher', 'In the live site this goes to payment. Nothing is charged in the local preview.');
        if (p === '/bnb/newsletter/subscribe') return messagePage(res, 'Thanks for subscribing', 'In the live site this adds you to the mailing list. Nothing is saved in the local preview.');
        const result = /^\/salon\/checkout-result\/(\w+)/.exec(p);
        if (result) return checkoutResultPage(res, result[1]);
        if (p.startsWith('/salon/')) return await api(req, res, url);
        // Called on every booking page load to restore an Apple/Google sign-in; nobody is signed in here.
        if (p === '/auth/social/userdata') return sendJSON(res, { jsonrpc: '2.0', id: null, result: { success: false } });
        if (p.startsWith('/auth/')) return messagePage(res, 'Social login', 'Apple and Google sign-in need the live Odoo server and are not available in the local preview.');
        if (p === '/web/static/img/placeholder.png') return redirect(res, '/bnb_portal_appointment/static/img/salon.png');
        if (p === '/site.css') return staticFile(res, p);
        if (p.startsWith('/bnb_portal_appointment/static/')) return staticFile(res, p);
        return messagePage(res, 'Page not in the preview', `${p} is an Odoo page that isn't part of this module's preview.`);
    } catch (error) {
        console.error(error);
        send(res, 500, `<pre>${esc(error.stack)}</pre>`);
    }
});

server.on('error', error => {
    if (error.code !== 'EADDRINUSE') throw error;
    console.error(`\nPort ${PORT} is already in use. Start on another port, e.g.:  PORT=8090 node server.js\n`);
    process.exit(1);
});

server.listen(PORT, () => {
    console.log(`\nBrowz & Beauty portal preview is running:\n`);
    console.log(`  Home page     http://localhost:${PORT}/`);
    console.log(`  Book online   http://localhost:${PORT}/book-online`);
    console.log(`  Gift voucher  http://localhost:${PORT}/gift-voucher\n`);
    console.log('Edit files, then refresh the browser. Press Ctrl+C to stop.\n');
});
