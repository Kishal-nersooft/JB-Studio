# JB studio: Browz & Beauty portal preview

This folder runs the online booking portal from the Odoo module
`bnb_portal_appointment` as a plain HTML website on your own computer, with
no Odoo needed. It is meant for UI work: change the look, see it straight
away, then hand the changed files back to the developer.

It uses the module's real CSS, SCSS, JavaScript and images. Only the data is
pretend: `mock-data.js` stands in for the Odoo database.

## Run it

**Easiest:** double-click `start.command` in Finder. It opens the site in your
browser at http://localhost:8080. (The first time, macOS may ask you to
allow it: right-click the file, choose **Open**, then **Open** again.)

**From a terminal:**

```bash
cd "JB studio"
npm install      # first time only
npm start        # then open http://localhost:8080
```

You need Node.js (https://nodejs.org). Stop the server with `Ctrl+C`. If
port 8080 is taken, run `PORT=8090 npm start`.

## Pages

| URL | What it is |
| --- | --- |
| `/` | Home page |
| `/book-online` | Booking: choose a salon |
| `/book-online/service?branch_id=1` | Booking: services, then time, professional, your details, payment |
| `/salon/checkout-result/<n>` | "Booking Confirmed" page shown after paying |
| `/gift-voucher` | Gift voucher form |

Booking test tips:

- Times **11:00, 11:15 and 14:30** are always shown as unavailable.
- **Sarah** is always shown as busy.
- Gift/discount codes **WELCOME10** (10% off) and **GIFT20** ($20 off) work on the payment step.
- Belconnen has Saturday and Sunday surcharges, to show the surcharge row.
- Pressing **Pay Now** goes straight to the "Booking Confirmed" page. The real site shows a card-payment page in between, which isn't part of this preview.

## Where to make changes

Save the file and refresh the browser. There's no build step; `.scss` files
are compiled each time the page loads. If an `.scss` file has a mistake, the
terminal shows the error.

| To change… | Edit this file | Copy back to (in the Odoo module) |
| --- | --- | --- |
| Booking flow styles | `bnb_portal_appointment/static/src/css/main-booking.scss` | same path |
| Home page styles | `bnb_portal_appointment/static/src/scss/homepage_snippets.scss` | same path |
| Footer styles | `bnb_portal_appointment/static/src/scss/bnb_footer.scss` | same path |
| Social login / popup styles | `bnb_portal_appointment/static/src/css/login_auth.css`, `notification_styles.css` | same path |
| Booking behaviour | `bnb_portal_appointment/static/src/js/base.js` | same path |
| Images | `bnb_portal_appointment/static/img/` | same path |
| Location step markup | `pages/partials/step-location.html`, `location-card.html` | `views/location_view.xml` |
| Services step markup | `pages/partials/step-service.html`, `service-card.html` | `views/service_view.xml` |
| Time step markup | `pages/partials/step-date.html` | `views/date_view.xml` |
| Professional step markup | `pages/partials/step-beautician.html` | `views/beautician_view.xml` |
| Customer step markup | `pages/partials/step-customer.html` | `views/customer_view.xml` |
| Payment step markup | `pages/partials/step-payment.html`, `payment-booking-card.html` | `views/payment_view.xml`, `views/base_view.xml` |
| Booking summary card (right side) | `pages/partials/booking-card.html` | `views/base_view.xml` |
| Breadcrumb | `pages/partials/breadcrumb.html` | `views/base_view.xml` |
| Booking page frame / hero text | `pages/book-online.html` | `views/base_view.xml` |
| Inline confirmation step | `pages/partials/step-confirmation.html` | `views/booking_confirm.xml` |
| "Booking Confirmed" page | `pages/checkout-result.html`, `partials/checkout-result-styles.html` | `views/payment_intent.xml` (`checkout_result`) |
| Home page sections | `pages/partials/home-sections.html` | `views/snippets/homepage_snippets.xml` |
| Footer | `pages/partials/footer.html` | `views/footer.xml` |
| Gift voucher page | `pages/gift-voucher.html` | `views/gift_card.xml` |
| Salons, services, prices, staff | `mock-data.js` | (real data lives in Odoo, not in code) |

Every page and partial starts with a comment naming the Odoo template it
copies, so the developer can find the matching place.

**Handing changes back:** the CSS, SCSS, JS and image files are exact copies,
so the developer can drop them straight into the module. Markup changes in
`pages/` must be copied into the matching `views/*.xml` by hand. Those files
are QWeb templates: `{{NAME}}` placeholders here are `t-out`/`t-foreach` code
there, so send the developer a description of the change too.

## Files that aren't part of the Odoo module

These exist only to make the preview work. Changes to them won't reach the
live site:

- `pages/partials/header.html`, `head.html`, `scripts.html`, `site.css`: in
  Odoo the header, Bootstrap and theme colours come from the website builder
  settings. That is why buttons such as "Contact Us" use plain Bootstrap blue
  here.
- `server.js`, `mock-data.js`, `start.command`, `package.json`.

## Not included

- Apple / Google sign-in (needs the real Odoo server).
- The secure card-payment page (Stripe/NAB) between "Pay Now" and the result page.
- Odoo back-office screens (appointments, settings) from the other module, `bb_salon_appoitments`.
