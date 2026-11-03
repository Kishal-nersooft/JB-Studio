// Sample data that stands in for the Odoo database.
// Edit anything here and refresh the browser (the server re-reads this file
// on every request). Shapes match what the real Odoo controllers return.

const IMG = '/bnb_portal_appointment/static/img';

module.exports = {
    branches: [
        { id: 1, name: 'Browz & Beauty Westfield Belconnen', street: 'Westfield Belconnen, Benjamin Way', city: 'Belconnen', state: 'ACT', zip: '2617', country: 'Australia', tz: 'Australia/Sydney', image: `${IMG}/salon.png`, booking_fee: 5.00, start_hour: 9.0, end_hour: 17.5, saturday_surcharge_percent: 0.10, sunday_surcharge_percent: 0.15 },
        { id: 2, name: 'Browz & Beauty Westfield Marion', street: '297 Diagonal Road', city: 'Oaklands Park', state: 'SA', zip: '5046', country: 'Australia', tz: 'Australia/Adelaide', image: `${IMG}/salon.png`, booking_fee: 5.00, start_hour: 9.0, end_hour: 17.5, saturday_surcharge_percent: 0, sunday_surcharge_percent: 0 },
        { id: 3, name: 'Browz & Beauty Westfield Woden', street: 'Keltie Street', city: 'Phillip', state: 'ACT', zip: '2606', country: 'Australia', tz: 'Australia/Sydney', image: `${IMG}/salon.png`, booking_fee: 0, start_hour: 9.0, end_hour: 17.0, saturday_surcharge_percent: 0, sunday_surcharge_percent: 0 },
        { id: 4, name: 'Browz & Beauty Mitchell Centre', street: '55-59 Mitchell Street', city: 'Darwin', state: 'NT', zip: '0800', country: 'Australia', tz: 'Australia/Darwin', image: `${IMG}/salon.png`, booking_fee: 5.00, start_hour: 9.0, end_hour: 17.0, saturday_surcharge_percent: 0, sunday_surcharge_percent: 0 },
        { id: 5, name: 'Browz & Beauty Gateway Shopping Centre', street: '1 Roystonea Avenue', city: 'Palmerston', state: 'NT', zip: '0830', country: 'Australia', tz: 'Australia/Darwin', image: `${IMG}/salon.png`, booking_fee: 5.00, start_hour: 9.0, end_hour: 17.5, saturday_surcharge_percent: 0, sunday_surcharge_percent: 0 },
        { id: 6, name: 'Browz & Beauty Casuarina Square', street: '247 Trower Road', city: 'Casuarina', state: 'NT', zip: '0810', country: 'Australia', tz: 'Australia/Darwin', image: `${IMG}/salon.png`, booking_fee: 5.00, start_hour: 9.0, end_hour: 17.5, saturday_surcharge_percent: 0, sunday_surcharge_percent: 0 },
    ],

    // Parent categories fill the dropdown; child categories become the pills.
    parentCategories: [
        { id: 100, name: 'Brows' },
        { id: 200, name: 'Lashes' },
        { id: 300, name: 'Face & Body' },
    ],

    // sold_quantity > 0 puts a service in the "Top Selling" tab.
    serviceCategories: [
        { id: 101, name: 'Threading', parent_id: 100, products: [
            { id: 1001, name: 'Eyebrow Threading', price: 22, duration: '15 mins', sold_quantity: 340, description: 'Precise shaping using a twisted cotton thread to remove hair from the follicle. Suitable for sensitive skin and gives clean, defined lines that last 3 to 4 weeks.' },
            { id: 1002, name: 'Upper Lip Threading', price: 12, duration: '10 mins', sold_quantity: 180, description: 'Quick, gentle removal of upper lip hair.' },
            { id: 1003, name: 'Full Face Threading', price: 55, duration: '30 mins', sold_quantity: 95, description: 'Brows, upper lip, chin, cheeks, forehead and sides of the face.' },
        ] },
        { id: 102, name: 'Tinting', parent_id: 100, products: [
            { id: 1011, name: 'Eyebrow Tint', price: 18, duration: '15 mins', sold_quantity: 120, description: 'Semi-permanent tint to define and darken brows.' },
            { id: 1012, name: 'Henna Brow Tint', price: 35, duration: '30 mins', sold_quantity: 75, description: 'Plant-based henna that stains both hair and skin for a fuller, longer-lasting brow.' },
            { id: 1013, name: 'Hybrid Brow Tint', price: 38, duration: '30 mins', sold_quantity: 0, description: '' },
        ] },
        { id: 103, name: 'Brow Lamination', parent_id: 100, products: [
            { id: 1021, name: 'Brow Lamination', price: 75, duration: '45 mins', sold_quantity: 60, description: 'Sets brow hairs in a brushed-up position for a fuller, fluffy look that lasts 6 to 8 weeks.' },
            { id: 1022, name: 'Brow Lamination + Tint', price: 89, duration: '1h', sold_quantity: 0, description: 'Lamination finished with a tint for extra definition.' },
        ] },
        { id: 201, name: 'Lash Lift', parent_id: 200, products: [
            { id: 2001, name: 'Lash Lift & Tint', price: 79, duration: '1h', sold_quantity: 88, description: 'Curls and tints your natural lashes. Results last 6 to 8 weeks.' },
            { id: 2002, name: 'Eyelash Tint', price: 20, duration: '15 mins', sold_quantity: 40, description: 'Darkens natural lashes for a mascara-free look.' },
        ] },
        { id: 202, name: 'Lash Extensions', parent_id: 200, products: [
            { id: 2011, name: 'Classic Eyelash Extensions', price: 120, duration: '1h 30 mins', sold_quantity: 0, description: 'One extension applied to each natural lash for a natural, lengthened look.' },
            { id: 2012, name: 'Volume Eyelash Extensions', price: 150, duration: '2h', sold_quantity: 0, description: 'Several fine extensions fanned onto each natural lash for a fuller look.' },
        ] },
        { id: 301, name: 'Facials', parent_id: 300, products: [
            { id: 3001, name: 'Express Facial', price: 55, duration: '30 mins', sold_quantity: 25, description: 'Cleanse, exfoliate, mask and moisturise.' },
            { id: 3002, name: 'Deluxe Facial', price: 95, duration: '1h', sold_quantity: 0, description: 'Includes extraction, massage and a treatment mask chosen for your skin.' },
        ] },
        { id: 302, name: 'Waxing', parent_id: 300, products: [
            { id: 3011, name: 'Half Leg Wax', price: 35, duration: '30 mins', sold_quantity: 30, description: '' },
            { id: 3012, name: 'Underarm Wax', price: 18, duration: '15 mins', sold_quantity: 22, description: '' },
        ] },
        { id: 303, name: 'Spray Tanning', parent_id: 300, products: [
            { id: 3021, name: 'Full Body Spray Tan', price: 45, duration: '30 mins', sold_quantity: 0, description: 'A natural-looking, streak-free tan.' },
        ] },
    ],

    // Shown in the "Add an extra service?" popup after booking a service.
    relatedServices: {
        1001: [1011, 1002],
        1011: [1001],
        1021: [1011],
        2001: [1001],
    },

    // price is the extra charge for choosing that professional ("$0.00" = none).
    // Add image: '/bnb_portal_appointment/static/img/...' to show a photo; without one the card shows initials.
    beauticians: [
        { id: 11, name: 'Priya', price: '$0.00' },
        { id: 12, name: 'Rj', price: '$0.00' },
        { id: 13, name: 'Anjali', price: '$5.00' },
        { id: 14, name: 'Sarah', price: '$0.00', busy: true, reason: 'Busy at this time' },
    ],

    // Start times (decimal hours) shown greyed out as "Unavailable" on every date.
    unavailableStartHours: [11.0, 11.25, 14.5],

    // Codes accepted in the "Gift / Discount Code" box on the payment step.
    promoCodes: {
        WELCOME10: { percent: 10, message: '10% discount applied' },
        GIFT20: { amount: 20, message: '$20.00 gift voucher applied' },
    },

    giftVoucherAmounts: [40, 60, 100],
};
