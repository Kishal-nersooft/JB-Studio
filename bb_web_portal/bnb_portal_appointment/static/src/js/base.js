// ============================================================================
// STATE & UTILITIES
// ============================================================================
function reportBookingError(message, error = null) {
    console.error('[Online Booking]', message, error);
    if (error?.bnbDisplayed) return;
    if (error) error.bnbDisplayed = true;
    try {
        if (window.bnbShowBookingError) {
            window.bnbShowBookingError(message);
        } else {
            Utils.showBookingPopup({ title: 'Unable to continue booking', message, actionText: 'Close', variant: 'error' });
        }
    } catch (displayError) {
        console.error('[Online Booking] Could not show error popup', displayError);
        Utils.showBookingPopup({ title: 'Unable to continue booking', message, actionText: 'Close', variant: 'error' });
    }
}

const BookingState = {
    data: {
        selectedServices: [],
        selectedDateTime: null,
        selectedBeautician: null,
        customerData: null,
        paymentData: null,
        currentStep: null,
        branchId: new URLSearchParams(window.location.search).get('branch_id'),
        bookingFee: null,
        branchTz: 'UTC',
        saturdaySurchargePercent: 0,
        sundaySurchargePercent: 0
    },
    persist() {
        try {
            const data = {
                selectedServices: this.data.selectedServices,
                selectedDateTime: this.data.selectedDateTime,
                selectedBeautician: this.data.selectedBeautician,
                branchId: this.data.branchId,
                bookingFee: this.data.bookingFee,
                branchTz: this.data.branchTz,
                saturdaySurchargePercent: this.data.saturdaySurchargePercent,
                sundaySurchargePercent: this.data.sundaySurchargePercent,
                customerData: this.data.customerData,
                paymentData: this.data.paymentData,
                currentStep: this.data.currentStep
            };
            sessionStorage.setItem('bnb_booking_state', JSON.stringify(data));
        } catch (error) {
            reportBookingError('Your browser could not save your booking selections. Please keep this page open; your selections may need to be entered again.', error);
        }
        window.bnbMobileBookingController?.refresh();
    },
    load() {
        // Opening the location landing page starts a new booking. Explicit
        // branch/step URLs still restore a booking in progress.
        if (/^\/book-online(?:\/\d+)?\/?$/.test(window.location.pathname)
                && !new URLSearchParams(window.location.search).get('branch_id')) {
            this.reset();
            this.data.branchId = null;
            this.data.branchTz = 'UTC';
            return;
        }
        try {
            const raw = sessionStorage.getItem('bnb_booking_state');
            if (!raw) return;
            const saved = JSON.parse(raw);
            const branchIdFromUrl = new URLSearchParams(window.location.search).get('branch_id');

            this.data.selectedServices = Array.isArray(saved.selectedServices) ? saved.selectedServices : [];
            this.data.selectedDateTime = saved.selectedDateTime || null;
            this.data.selectedBeautician = saved.selectedBeautician || null;
            this.data.bookingFee = typeof saved.bookingFee === 'number' ? saved.bookingFee : this.data.bookingFee;
            this.data.branchTz = saved.branchTz || this.data.branchTz;
            this.data.saturdaySurchargePercent = typeof saved.saturdaySurchargePercent === 'number'
                ? saved.saturdaySurchargePercent
                : this.data.saturdaySurchargePercent;
            this.data.sundaySurchargePercent = typeof saved.sundaySurchargePercent === 'number'
                ? saved.sundaySurchargePercent
                : this.data.sundaySurchargePercent;
            this.data.customerData = saved.customerData || null;
            this.data.paymentData = saved.paymentData || null;
            this.data.currentStep = saved.currentStep || null;

            if (branchIdFromUrl) {
                this.data.branchId = branchIdFromUrl;
            } else if (saved.branchId) {
                this.data.branchId = saved.branchId;
            }
        } catch (error) {
            reportBookingError('Your saved booking selections could not be restored. Please select your services and appointment time again.', error);
        }
    },
    reset() {
        Object.assign(this.data, {
            selectedServices: [],
            selectedDateTime: null,
            selectedBeautician: null,
            customerData: null,
            paymentData: null,
            currentStep: null,
            bookingFee: null,
            saturdaySurchargePercent: 0,
            sundaySurchargePercent: 0
        });
        try {
            sessionStorage.removeItem('bnb_booking_state');
        } catch (error) {
            reportBookingError('Your browser could not clear the saved booking selections. Please check the details before starting another booking.', error);
        }
    }
};


const Utils = {
    async fetchJSON(url, options = {}) {
        const opts = { ...options };
        const method = (opts.method || 'GET').toUpperCase();
        if (!opts.headers) opts.headers = {};
        if (method !== 'GET' && method !== 'HEAD' && method !== 'OPTIONS') {
            const csrfToken = Utils.getCsrfToken();
            if (csrfToken) {
                if (opts.body instanceof FormData) {
                    if (!opts.body.has('csrf_token')) {
                        opts.body.append('csrf_token', csrfToken);
                    }
                } else if (typeof opts.body === 'string'
                    && (opts.headers['Content-Type'] || opts.headers['content-type'])?.includes('application/json')) {
                    try {
                        const parsed = JSON.parse(opts.body);
                        if (!parsed.csrf_token) {
                            parsed.csrf_token = csrfToken;
                            opts.body = JSON.stringify(parsed);
                        }
                    } catch (e) {
                        reportBookingError('The booking request could not be prepared. Please refresh the page and try again.', e);
                        throw e;
                    }
                    opts.headers['X-CSRFToken'] = csrfToken;
                } else {
                    opts.headers['X-CSRFToken'] = csrfToken;
                }
            }
        }
        try {
            const res = await fetch(url, opts);
            if (!res.ok) throw new Error('Booking information could not be loaded. Please try again or contact the salon.');
            const data = await res.json();
            if ((data.error && data.success !== true) || data.success === false) {
                throw new Error(typeof data.error === 'string' ? data.error : data.message || 'Booking information could not be loaded. Please try again.');
            }
            return data;
        } catch (error) {
            reportBookingError(error instanceof SyntaxError || error instanceof TypeError
                ? 'Booking information could not be loaded. Please check your connection and try again.'
                : error.message, error);
            throw error;
        }
    },
    getCsrfToken() {
        const input = document.querySelector('#bnb_csrf_token');
        if (input && input.value) return input.value;
        const meta = document.querySelector('meta[name="csrf_token"]');
        if (meta && meta.content) return meta.content;
        if (window.odoo && window.odoo.csrf_token) return window.odoo.csrf_token;
        return '';
    },
    $(selector) {
        return document.querySelector(selector);
    },
    $$(selector) {
        return document.querySelectorAll(selector);
    },
    hide(el) {
        (typeof el === 'string' ? this.$(el) : el).style.display = 'none';
    },
    show(el, display = 'block') {
        (typeof el === 'string' ? this.$(el) : el).style.display = display;
    },
    formatPrice: val => `$${parseFloat(val).toFixed(2)}`,
    parsePrice: str => parseFloat(str.replace(/[^\d.]/g, '')) || 0,
    escapeHTML: value => String(value || '').replace(/[&<>"']/g, char => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    }[char])),
    showBookingPopup({
        title = 'Booking unavailable',
        kicker = 'Booking',
        message = '',
        detail = '',
        actionText = 'Choose another time',
        variant = 'warning',
        onClose = null
    } = {}) {
        if (!document.body) {
            document.addEventListener('DOMContentLoaded', () => this.showBookingPopup({title, kicker, message, detail, actionText, variant, onClose}), {once: true});
            return;
        }
        let modal = document.getElementById('bookingAvailabilityPopup');
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'bookingAvailabilityPopup';
            modal.className = 'booking-availability-popup';
            document.body.appendChild(modal);
        }

        const safeTitle = this.escapeHTML(title);
        const safeMessage = this.escapeHTML(message);
        const safeDetail = this.escapeHTML(detail);
        const safeActionText = this.escapeHTML(actionText);
        const icon = variant === 'error' ? '!' : '&#128339;';

        modal.innerHTML = `
      <div class="booking-availability-popup-overlay" data-action="close-booking-popup"></div>
      <div class="booking-availability-popup-card" role="dialog" aria-modal="true" aria-labelledby="bookingAvailabilityPopupTitle">
        <button class="booking-availability-popup-close" type="button" data-action="close-booking-popup" aria-label="Close">×</button>
        <div class="booking-availability-popup-icon ${variant}">${icon}</div>
        <div class="booking-availability-popup-kicker">${this.escapeHTML(kicker)}</div>
        <h3 class="booking-availability-popup-title" id="bookingAvailabilityPopupTitle">${safeTitle}</h3>
        ${safeMessage ? `<p class="booking-availability-popup-message">${safeMessage}</p>` : ''}
        ${safeDetail ? `<div class="booking-availability-popup-detail">${safeDetail}</div>` : ''}
        <div class="booking-availability-popup-actions">
          <button class="booking-availability-popup-btn" type="button" data-action="close-booking-popup">${safeActionText}</button>
        </div>
      </div>
    `;

        const close = () => {
            modal.style.display = 'none';
            document.body.classList.remove('booking-popup-open');
            if (typeof onClose === 'function') {
                onClose();
            }
        };
        modal.querySelectorAll('[data-action="close-booking-popup"]').forEach(el => {
            el.addEventListener('click', close, { once: true });
        });
        modal.style.display = 'flex';
        document.body.classList.add('booking-popup-open');
    },
    formatDate: str => new Date(str).toLocaleDateString('en-US', {
        weekday: 'long',
        month: 'long',
        day: 'numeric'
    }),
    convertTimeToHour: str => str.split(':').reduce((h, m, i) => h + (i ? m / 60 : +m), 0),
    maskCardNumber: num => '**** **** **** ' + num.replace(/\D/g, '').slice(-4),
    getSurchargePercentForDate: (dateStr) => {
        if (!dateStr) return 0;
        const dateObj = new Date(dateStr);
        if (Number.isNaN(dateObj.getTime())) return 0;
        const day = dateObj.getDay(); // 0=Sun, 6=Sat
        const raw = day === 6
            ? parseFloat(BookingState.data.saturdaySurchargePercent) || 0
            : (day === 0 ? parseFloat(BookingState.data.sundaySurchargePercent) || 0 : 0);
        if (!raw) return 0;
        // Branch surcharge fields store a fraction (widget="percentage"), so
        // 1% arrives as 0.01. Return whole percent for the caller, which
        // divides by 100 when applying it. Reading values above 1 as whole
        // percentages made the meaning flip at exactly 1 and charged 100%.
        return raw * 100;
    },
    calculateServiceTotals: (selectedServices, selectedBeautician, selectedDateTime) => {
        const baseTotal = (selectedServices || []).reduce((sum, s) => sum + Utils.parsePrice(s.price), 0);
        let beauticianAdd = 0;
        if (selectedBeautician?.id && selectedBeautician.id !== 'any' && selectedBeautician.price) {
            beauticianAdd = Utils.parsePrice(selectedBeautician.price);
        }
        const subtotal = baseTotal + beauticianAdd;
        const surchargePercent = Utils.getSurchargePercentForDate(selectedDateTime?.date);
        const surchargeAmount = surchargePercent ? (subtotal * surchargePercent / 100) : 0;
        return {
            baseTotal: subtotal,
            surchargePercent,
            surchargeAmount,
            totalWithSurcharge: subtotal + surchargeAmount,
        };
    }
};

window.bnbShowBookingError = message => Utils.showBookingPopup({
    title: 'Unable to continue booking', message, actionText: 'Close', variant: 'error'
});
BookingState.load();
window.bookingData = BookingState.data;
window.addEventListener('beforeunload', () => BookingState.persist());
(window.bnbPendingBookingErrors || []).splice(0).forEach(message => window.bnbShowBookingError(message));

// Preserve normal browser error logging while making booking failures visible.
const isBookingPage = () => /^\/(book-online(?:\/|$)|salon\/(secure-checkout|checkout-result)\/)/.test(window.location.pathname);
window.addEventListener('error', event => {
    if (isBookingPage() && event.error) {
        reportBookingError('Something went wrong while loading the booking page. Please refresh or contact the salon.', event.error);
    }
});
window.addEventListener('unhandledrejection', event => {
    if (!isBookingPage()) return;
    const error = event.reason;
    const expected = ['odoo.exceptions.ValidationError', 'odoo.exceptions.UserError'].includes(error?.exceptionName);
    reportBookingError(expected && error.data?.message ? error.data.message
        : 'The booking request could not be completed. Please contact the salon before retrying a payment.',
        error instanceof Error ? error : null);
});

const BookingUrl = {
    stepSlugs: new Set(['location', 'service', 'date', 'beautician', 'customer', 'payment', 'confirmation']),
    getCurrentStep() {
        const parts = window.location.pathname.split('/').filter(Boolean);
        const last = parts[parts.length - 1];
        return this.stepSlugs.has(last) ? last : null;
    },
    update(step, replace = false) {
        if (!this.stepSlugs.has(step)) return;
        if (this.getCurrentStep() === step) return;
        const url = new URL(window.location.href);
        const parts = url.pathname.split('/').filter(Boolean);
        const last = parts[parts.length - 1];
        if (this.stepSlugs.has(last)) {
            parts.pop();
        }
        parts.push(step);
        url.pathname = `/${parts.join('/')}`;
        if (replace) {
            history.replaceState({ step }, '', url.toString());
        } else {
            history.pushState({ step }, '', url.toString());
        }
        BookingState.data.currentStep = step;
        BookingState.persist();
    }
};

const StepGuard = {
    stepOrder: ['location', 'service', 'date', 'beautician', 'customer', 'payment', 'confirmation'],

    getMaxAllowedStep() {
        const d = BookingState.data;
        if (d.paymentData) return 'confirmation';
        if (d.customerData) return 'payment';
        if (d.selectedBeautician) return 'customer';
        if (d.selectedDateTime) return 'beautician';
        if (d.selectedServices?.length) return 'date';
        if (d.branchId) return 'service';
        return 'location';
    },

    canAccessStep(step) {
        const maxIdx = this.stepOrder.indexOf(this.getMaxAllowedStep());
        const reqIdx = this.stepOrder.indexOf(step);
        return reqIdx <= maxIdx;
    },

    isConfirmation() {
        return BookingUrl.getCurrentStep() === 'confirmation';
    }
};

// ============================================================================
// BASE HANDLER
// ============================================================================
class BaseHandler {
    constructor() {
        this.bindEvents();
    }
    bindEvents() {}
    delegate(event, selector, handler) {
        document.addEventListener(event, e => {
            const target = e.target.closest(selector);
            if (target) handler.call(this, e, target);
        });
    }
}

// ============================================================================
// LOCATION HANDLER
// ============================================================================
class LocationHandler extends BaseHandler {
    bindEvents() {
        this.delegate('click', '.location-salon-card', this.selectBranch);
        if (BookingState.data.branchId) this.fetchBookingFee(BookingState.data.branchId);
    }

    async fetchBookingFee(branchId) {
        try {
            const data = await Utils.fetchJSON(`/salon/get-branch-hours?branch_id=${branchId}`);
            Object.assign(BookingState.data, {
                bookingFee: parseFloat(data.booking_fee) || 0,
                branchTz: data.branch_tz || 'UTC'
            });
            BookingState.persist();
            return true;
        } catch (error) {
            reportBookingError('Location details could not be loaded. Please try again.', error);
            return false;
        }
    }

    async selectBranch(e, card) {
        const branchId = card.dataset.salonId || card.dataset.branchId;
        if (branchId) {
            if (!await this.fetchBookingFee(branchId)) return;
            window.location.href = `/book-online?branch_id=${branchId}`;
        }
    }
}

// ============================================================================
// SERVICE HANDLER
// ============================================================================
class ServiceHandler extends BaseHandler {
    constructor() {
        super();
        // Listen for service changes
        document.addEventListener('servicesUpdated', () => this.updateCard());
    }
    bindEvents() {
        this.modal = Utils.$('#serviceDetailModal');
        this.delegate('click', '.service-book-btn', (e, btn) => {
            e.preventDefault();
            e.stopPropagation();
            this.handleBookClick(btn);
        });
        this.delegate('click', '.remove-service-btn', (e, btn) => this.removeService(btn));
        this.delegate('click', '.service-item-card', (e, card) => {
            if (e.target.closest('.service-book-btn')) return;
            if (e.target.closest('.service-details-btn')) return;
            const btn = card.querySelector('.service-book-btn');
            if (btn) this.handleBookClick(btn);
        });
        this.delegate('click', '.service-details-btn', (e, btn) => {
            e.stopPropagation();
            const card = btn.closest('.service-item-card');
            if (card) this.showModal(card);
        });
        this.delegate('click', '.service-modal-close, .service-modal-overlay', () => this.closeModal());
        this.delegate('click', '.service-modal-action-btn', (e, btn) => this.handleModalAction(btn));
        this.delegate('click', '.service-modal-read-more', (e, btn) => this.toggleReadMore(btn));
        this.delegate('click', '.service-tab', (e, tab) => this.filterByChild(tab));
        this.delegate('change', '#parentCategoryDropdown', (e, dropdown) => this.filterByParent(dropdown));
        this.delegate('click', '.category-nav-prev', () => this.scrollCategories(-1));
        this.delegate('click', '.category-nav-next', () => this.scrollCategories(1));
        this.delegate('click', '.service-continue-btn', e => {
            if (e.target.closest('#step-service')) this.continue();
        });
        this.serviceCatalog = Array.from(Utils.$$('.service-item-card'));
        const activeTab = Utils.$('.service-tab.active');
        if (activeTab) this.filterByChild(activeTab);
    }

    // Handle Book button click - add service and show related products
    async handleBookClick(btn) {
        const card = btn.closest('.service-item-card');
        const {
            serviceId: id,
            serviceName: name,
            servicePrice: price
        } = card.dataset;

        const index = BookingState.data.selectedServices.findIndex(s => s.id === id);

        if (index === -1) {
            // Service not selected - add it
            BookingState.data.selectedServices.push({
                id,
                name,
                price
            });
            BookingState.persist();
            btn.textContent = 'Remove';
            btn.classList.add('selected');
            card.classList.add('selected');

            this.updateCard();

            // Show related products modal immediately
            if (window.relatedServicesHandler) {
                try {
                    await window.relatedServicesHandler.showRelatedProductsForService(id);
                } catch (err) {
                    reportBookingError('Related services could not be loaded. Please try again.', err);
                }
            }

        } else {
            // Service already selected - remove it
            BookingState.data.selectedServices.splice(index, 1);
            BookingState.persist();
            btn.textContent = 'Book';
            btn.classList.remove('selected');
            card.classList.remove('selected');

            this.updateCard();
        }
    }

    scrollCategories(direction) {
        const container = Utils.$('.service-categories-tabs');
        if (!container) return;

        const pills = container.querySelectorAll('.service-tab');
        if (pills.length === 0) return;

        const pillWidth = pills[0].offsetWidth + 8;
        const scrollAmount = pillWidth * 2;

        container.scrollLeft += direction * scrollAmount;
    }

    filterByParent(dropdown) {
        const parentId = dropdown.value;
        const tabs = Utils.$$('.service-tab');

        tabs.forEach(tab => {
            if (parentId === 'all' || tab.dataset.categoryId === 'all' || tab.dataset.parentId === parentId) {
                tab.style.display = '';
            } else {
                tab.style.display = 'none';
            }
        });

        const firstVisible = Array.from(tabs).find(t => t.style.display !== 'none');
        if (firstVisible) firstVisible.click();
    }

    filterByChild(tab) {
        Utils.$$('.service-tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        const categoryId = tab.dataset.categoryId;
        const parentId = Utils.$('#parentCategoryDropdown')?.value || 'all';
        const topSelling = categoryId === 'all';
        const cards = this.serviceCatalog;
        let visible = cards.filter(card =>
            (parentId === 'all' || card.dataset.parentId === parentId)
            && (topSelling || card.dataset.categoryId === categoryId));
        if (topSelling) {
            visible = visible.filter(card => Number(card.dataset.soldQuantity) > 0)
                .sort((a, b) => Number(b.dataset.soldQuantity) - Number(a.dataset.soldQuantity)
                    || Number(a.dataset.serviceId) - Number(b.dataset.serviceId))
                .slice(0, 10);
        }
        const visibleSet = new Set(visible);
        cards.forEach(card => {
            card.style.display = visibleSet.has(card) ? '' : 'none';
        });
        // Reorder real cards so booking, details and selected-state handlers stay attached.
        const list = Utils.$('.service-items-list');
        (topSelling ? [...visible, ...cards.filter(card => !visibleSet.has(card))] : cards)
            .forEach(card => list.appendChild(card));
        const empty = Utils.$('.top-selling-empty');
        if (empty) empty.style.display = topSelling && !visible.length ? '' : 'none';
    }

    toggleReadMore(btn) {
        const desc = this.modal.querySelector('.service-modal-description');
        desc.classList.toggle('collapsed');
        btn.textContent = desc.classList.contains('collapsed') ? 'Read more' : 'Read less';
    }

    showModal(card) {
        const {
            serviceId,
            serviceName,
            servicePrice,
            serviceDuration,
            serviceDescription
        } = card.dataset;

        if (!serviceDescription || serviceDescription.trim() === '' || serviceDescription === 'No description available.') {
            console.log('No description available for this service, skipping modal');
            return;
        }

        const isSelected = BookingState.data.selectedServices.some(s => s.id === serviceId);

        this.modal.querySelector('.service-modal-title').textContent = serviceName;
        this.modal.querySelector('.service-modal-duration').textContent = serviceDuration;
        this.modal.querySelector('.service-modal-price').textContent = servicePrice;

        const desc = this.modal.querySelector('.service-modal-description');
        desc.textContent = serviceDescription;
        desc.classList.add('collapsed');

        const readMore = this.modal.querySelector('.service-modal-read-more');
        readMore.textContent = 'Read more';
        readMore.style.display = 'inline-block';

        const actionBtn = this.modal.querySelector('.service-modal-action-btn');
        actionBtn.textContent = isSelected ? 'Remove' : 'Add to booking';
        actionBtn.classList.toggle('remove', isSelected);
        Object.assign(actionBtn.dataset, {
            serviceId,
            serviceName,
            servicePrice
        });

        this.modal.style.display = 'block';
    }

    closeModal() {
        this.modal.style.display = 'none';
    }

    async handleModalAction(btn) {
        const {
            serviceId: id,
            serviceName: name,
            servicePrice: price
        } = btn.dataset;
        const index = BookingState.data.selectedServices.findIndex(s => s.id === id);

        if (index === -1) {
            BookingState.data.selectedServices.push({
                id,
                name,
                price
            });
            BookingState.persist();

            // Show related products modal
            if (window.relatedServicesHandler) {
                try {
                    await window.relatedServicesHandler.showRelatedProductsForService(id);
                } catch (err) {
                    reportBookingError('Related services could not be loaded. Please try again.', err);
                }
            }
        } else {
            BookingState.data.selectedServices.splice(index, 1);
            BookingState.persist();
        }

        const card = Utils.$(`[data-service-id="${id}"]`);
        if (card) {
            const bookBtn = card.querySelector('.service-book-btn');
            if (bookBtn) {
                bookBtn.textContent = index === -1 ? 'Remove' : 'Book';
                bookBtn.classList.toggle('selected', index === -1);
                card.classList.toggle('selected', index === -1);
            }
        }

        this.updateCard();
        this.closeModal();
    }

    removeService(btn) {
        const id = btn.dataset.serviceId;
        BookingState.data.selectedServices = BookingState.data.selectedServices.filter(s => s.id !== id);
        BookingState.persist();
        const card = Utils.$(`[data-service-id="${id}"]`);
        if (card) {
            const serviceBtn = card.querySelector('.service-book-btn');
            if (serviceBtn) {
                serviceBtn.textContent = 'Book';
                serviceBtn.classList.remove('selected');
            }
            card.classList.remove('selected');
        }
        this.updateCard();
    }

    updateCard() {
        const card = Utils.$('.service-booking-card');
        if (!card) return;

        card.querySelector('.selected-services')?.remove();
        const services = BookingState.data.selectedServices;

        if (services.length > 0) {
            const subtotal = services.reduce((sum, s) => sum + Utils.parsePrice(s.price), 0);
            const html = `
        <hr class="salon-booking-divider">
        <div class="salon-booking-services-container">
          ${services.map(s => `
            <div class="salon-booking-service-item">
              <div class="salon-booking-service-content">
                <div class="salon-booking-service-name">${s.name}</div>
              </div>
              <div class="salon-booking-service-price-container">
                <div class="salon-booking-service-price">${s.price}</div>
                <button class="salon-booking-remove-btn remove-service-btn" data-service-id="${s.id}">×</button>
              </div>
            </div>
          `).join('')}
          <div class="salon-booking-total-section">
            <div class="salon-booking-total-row">
              <span>Total</span><span>${Utils.formatPrice(subtotal)}</span>
            </div>
          </div>
        </div>
      `;
            card.querySelector('.service-continue-btn').insertAdjacentHTML('beforebegin', `<div class="selected-services">${html}</div>`);
        }
    }

    continue () {
        if (BookingState.data.selectedServices.length === 0) {
            window.bnbShowBookingError('Please select at least one service');
            return;
        }
        Utils.hide('#step-service');
        Utils.show('#step-date');
        BookingUrl.update('date');
        // Reset date/time selection when returning to date step, then re-render
        // so the auto-selected date (today) is real state, not just a highlighted
        // card. Without this the UI shows today as selected while selectedDate is
        // null, forcing the user to click the date again (Ticket 9).
        if (window.dateTimeHandler) {
            window.dateTimeHandler.selectedDate = null;
            window.dateTimeHandler.selectedTime = null;
            window.dateTimeHandler.updateDates();      // re-selects today AND sets selectedDate
            window.dateTimeHandler.loadBranchSlots();  // regenerate slots for that date
        }
        this.updateDateStepCard();
    }

    updateDateStepCard() {
        const dateCard = Utils.$('#step-date .service-booking-card');
        if (!dateCard) return;

        const infoSection = dateCard.querySelector('.service-booking-info');
        if (infoSection) infoSection.style.display = 'none';

        dateCard.querySelector('.selected-services')?.remove();

        const bookNowBtn = dateCard.querySelector('.service-continue-btn');
        if (!bookNowBtn) return;

        const services = BookingState.data.selectedServices;
        const subtotal = services.reduce((sum, s) => sum + Utils.parsePrice(s.price), 0);

        const html = `
      <div class="salon-booking-services-container">
        ${services.map(s => `
          <div class="salon-booking-service-item salon-booking-service-item--bordered">
            <div class="salon-booking-service-content">
              <div class="salon-booking-service-name">${s.name}</div>
            </div>
            <div class="salon-booking-service-price-container">
              <div class="salon-booking-service-price">${s.price}</div>
            </div>
          </div>
        `).join('')}
        <div class="salon-booking-total-section">
          <div class="salon-booking-total-row">
            <span>Total</span><span>${Utils.formatPrice(subtotal)}</span>
          </div>
        </div>
      </div>
    `;

        bookNowBtn.insertAdjacentHTML('beforebegin', `<div class="selected-services">${html}</div>`);
    }
}

// ============================================================================
// DATE/TIME HANDLER
// ============================================================================
class DateTimeHandler extends BaseHandler {
    constructor() {
        super();
        this.today = new Date();
        this.currentStartDate = new Date(this.today);
        this.selectedDate = null;
        this.selectedTime = null;
        this.slotLoadKey = null;
        setTimeout(() => {
            this.restorePreviousSelection(); // Restore before updating
            this.updateDates();
            this.loadBranchSlots();
        }, 100);
    }

    bindEvents() {
        this.delegate('click', '.fresha-date-item', (e, el) => this.selectDate(el));
        this.delegate('click', '.fresha-time-slot', (e, el) => this.selectTime(el));
        document.addEventListener('click', e => {
            if (e.target.closest('.date-nav-prev')) {
                e.preventDefault();
                e.stopPropagation();
                this.navigateDates(-1);
            }
            if (e.target.closest('.date-nav-next')) {
                e.preventDefault();
                e.stopPropagation();
                this.navigateDates(1);
            }
        });
        this.delegate('click', '.service-continue-btn', e => {
            if (e.target.closest('#step-date')) this.continue(e);
        });
    }

    /*NEW*/


    restorePreviousSelection() {
        // Restore from BookingState if exists
        if (BookingState.data.selectedDateTime) {
            this.selectedDate = BookingState.data.selectedDateTime.date;
            this.selectedTime = BookingState.data.selectedDateTime.time;

            // Set currentStartDate to show the week containing selected date
            if (this.selectedDate) {
                const selectedDateObj = new Date(this.selectedDate);
                // Make sure the selected date is visible in the calendar
                if (selectedDateObj >= this.today) {
                    this.currentStartDate = new Date(selectedDateObj);
                }
            }
        }
    }

    async loadBranchSlots() {
        const branchId = BookingState.data.branchId;
        const selectedServices = BookingState.data.selectedServices || [];
        const serviceIds = selectedServices.map(service => service.id).filter(Boolean);
        const loadKey = `${branchId || ''}|${this.selectedDate || ''}|${serviceIds.join(',')}`;
        this.slotLoadKey = loadKey;
        // No location is a normal initial state, not a failed server request.
        // Updating the key also invalidates a response for an earlier location.
        if (!branchId) return;
        try {
            const data = await Utils.fetchJSON(`/salon/get-branch-hours?branch_id=${branchId}`);
            BookingState.data.branchTz = data.branch_tz || 'UTC';

            let unavailableStartHours = [];
            if (branchId && this.selectedDate && serviceIds.length) {
                try {
                    const params = new URLSearchParams({
                        branch_id: branchId,
                        appointment_date: this.selectedDate,
                        selected_services: serviceIds.join(','),
                    });
                    const availability = await Utils.fetchJSON(
                        `/salon/get-resource-unavailable-slots?${params.toString()}`
                    );
                    if (availability.success) {
                        unavailableStartHours = availability.unavailable_start_hours || [];
                    }
                } catch (error) {
                    console.error('Resource slot loading failed:', error);
                    throw error;
                }
            }

            if (this.slotLoadKey !== loadKey) return;
            this.generateTimeSlots(
                data.start_hour || 9.0,
                data.end_hour || 18.0,
                unavailableStartHours
            );

            // After generating time slots, restore the selected time
            this.restoreTimeSelection();
        } catch (error) {
            if (this.slotLoadKey !== loadKey) return;
            reportBookingError('Available times could not be loaded. Please select the date again to retry.', error);
            this.clearSelectedTime();
            const slots = Utils.$('.fresha-time-slots');
            if (slots) slots.textContent = 'Available times could not be loaded. Please select the date again to retry.';
        }
    }

    generateTimeSlots(startHour, endHour, unavailableStartHours = []) {
        const timeSlots = Utils.$('.fresha-time-slots');
        if (!timeSlots) return;

        const unavailableHours = new Set(
            unavailableStartHours
                .map(hour => Number(hour))
                .filter(hour => Number.isFinite(hour))
                .map(hour => Math.round(hour * 100) / 100)
        );

        const slots = [];
        for (let current = startHour; current <= endHour; current += 0.25) {
            let h = Math.floor(current);
            let m = Math.round((current - h) * 60);
            if (m === 60) {
                h += 1;
                m = 0;
            }
            slots.push(`${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`);
        }

        timeSlots.innerHTML = `
      <div class="salon-booking-timeslots-grid">
        ${slots.map(time => {
            // Check if slot is in the past
            const isPast = this.isTimeSlotPast(time);
            const slotHour = Math.round(Utils.convertTimeToHour(time) * 100) / 100;
            const isResourceUnavailable = unavailableHours.has(slotHour);
            const isBlocked = isPast || isResourceUnavailable;
            return `
          <div class="salon-booking-timeslot fresha-time-slot ${isPast ? 'past-slot' : ''} ${isResourceUnavailable ? 'resource-unavailable-slot' : ''}" data-time="${time}" ${isBlocked ? 'aria-disabled="true" style="pointer-events:none;opacity:0.4;cursor:not-allowed;"' : ''} ${isResourceUnavailable ? 'title="Unavailable"' : ''}>
            <div class="fresha-time">${time}</div>
          </div>
        `;
        }).join('')}
      </div>
    `;

        if (
            this.selectedTime &&
            unavailableHours.has(
                Math.round(Utils.convertTimeToHour(this.selectedTime) * 100) / 100
            )
        ) {
            this.clearSelectedTime();
        }
    }

    clearSelectedTime() {
        this.selectedTime = null;
        BookingState.data.selectedDateTime = null;
        BookingState.persist();
        Utils.$('#step-date .selected-datetime')?.remove();
    }

    markTimeUnavailable(time) {
        const timeSlot = Utils.$(`.fresha-time-slot[data-time="${time}"]`);
        if (!timeSlot) return;
        timeSlot.classList.remove('selected');
        timeSlot.classList.add('resource-unavailable-slot');
        timeSlot.setAttribute('aria-disabled', 'true');
        timeSlot.setAttribute('title', 'Unavailable');
        timeSlot.style.pointerEvents = 'none';
        timeSlot.style.opacity = '0.4';
        timeSlot.style.cursor = 'not-allowed';
    }

    // Compare against the branch clock, regardless of the visitor's device timezone.
    isTimeSlotPast(timeString) {
        // If no date selected yet, nothing is past
        if (!this.selectedDate) return false;
        return window.BnbBranchDateTime.isTimeSlotPast(
            this.selectedDate,
            timeString,
            BookingState.data.branchTz || 'UTC'
        );
    }

    restoreTimeSelection() {
        if (this.selectedTime) {
            const timeSlot = Utils.$(`.fresha-time-slot[data-time="${this.selectedTime}"]`);
            if (timeSlot) {
                timeSlot.classList.add('selected');
            }
        }
    }

    updateDates() {
        const monthTitle = Utils.$('.fresha-month-title');
        const datesRow = Utils.$('.fresha-dates-row');
        if (!monthTitle || !datesRow) return;

        const months = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
        const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

        monthTitle.textContent = `${months[this.currentStartDate.getMonth()]} ${this.currentStartDate.getFullYear()}`;

        const dates = Array.from({
            length: 8
        }, (_, i) => {
            const date = new Date(this.currentStartDate);
            date.setDate(this.currentStartDate.getDate() + i);
            return date;
        });

        const canGoBack = this.currentStartDate.getTime() > this.today.getTime();

        // Check which date should be selected
        let selectedIndex = -1;
        if (this.selectedDate) {
            const selectedDateObj = new Date(this.selectedDate);
            selectedIndex = dates.findIndex(d =>
                d.getDate() === selectedDateObj.getDate() &&
                d.getMonth() === selectedDateObj.getMonth() &&
                d.getFullYear() === selectedDateObj.getFullYear()
            );
        }

        // If no previous selection or not in current view, select first date
        if (selectedIndex === -1) {
            selectedIndex = 0;
        }

        datesRow.innerHTML = `
      <button class="salon-booking-date-nav-btn date-nav-prev ${!canGoBack ? 'salon-booking-date-nav-btn--disabled' : ''}">
        <span class="icon-symbol">&#10094;</span>
      </button>
      ${dates.map((date, i) => `
        <div class="fresha-date-item available ${i === selectedIndex ? 'selected' : ''}" data-date="${date.getDate()}" data-full-date="${date.toISOString().split('T')[0]}">
          <div class="fresha-date-number">${date.getDate()}</div>
          <div class="fresha-date-day">${days[date.getDay()]}</div>
          <span class="fresha-date-check" aria-hidden="true">&#10003;</span>
        </div>
      `).join('')}
      <button class="salon-booking-date-nav-btn date-nav-next">
        <span class="icon-symbol">&#10095;</span>
      </button>
    `;

        // Update selectedDate if it changed due to navigation
        if (selectedIndex >= 0 && selectedIndex < dates.length) {
            this.selectedDate = dates[selectedIndex].toISOString().split('T')[0];
        }

        // Update the booking card to reflect current selection
        if (this.selectedDate && this.selectedTime) {
            this.updateBookingCard();
        }
    }

    navigateDates(direction) {
        const newStartDate = new Date(this.currentStartDate);
        newStartDate.setDate(newStartDate.getDate() + (direction * 8));
        if (direction === -1 && newStartDate < this.today) {
            // A page back always steps a full 8 days. When the calendar was
            // restored to a future selected date (returning to this step via
            // refresh or the browser back button -- restorePreviousSelection
            // anchors currentStartDate on the selected date, not on today),
            // that fixed jump can overshoot past today and get permanently
            // stuck: the button never disables and today becomes unreachable.
            // Snap to today instead of refusing the click outright, so
            // "previous" always terminates on today rather than a dead click.
            if (this.currentStartDate <= this.today) return; // already the earliest reachable window
            newStartDate.setTime(this.today.getTime());
        }
        this.currentStartDate = newStartDate;
        this.updateDates();
        this.restoreTimeSelection(); // Restore time selection after navigation
    }

    selectDate(dateEl) {
        Utils.$$('.fresha-date-item').forEach(el => el.classList.remove('selected'));
        dateEl.classList.add('selected');
        this.selectedDate = dateEl.dataset.fullDate;

        // IMPORTANT: Regenerate time slots when date changes
        // This will update which slots are greyed out
        const branch = BookingState.data.branchId;
        if (branch) {
            this.loadBranchSlots(); // This will call generateTimeSlots with updated date
        }

        this.updateBookingCard();

        // Clear beautician cache when date changes
        if (window.beauticianHandler) {
            window.beauticianHandler.hasLoaded = false;
            window.beauticianHandler.cachedData = null;
        }
    }

    selectTime(timeEl) {
        // Prevent selecting past time slots
        if (
            timeEl.classList.contains('past-slot') ||
            timeEl.classList.contains('resource-unavailable-slot')
        ) return;

        Utils.$$('.fresha-time-slot').forEach(el => el.classList.remove('selected'));
        timeEl.classList.add('selected');
        this.selectedTime = timeEl.dataset.time;
        this.updateBookingCard();

        // Clear beautician cache when time changes
        if (window.beauticianHandler) {
            window.beauticianHandler.hasLoaded = false;
            window.beauticianHandler.cachedData = null;
        }
    }

    updateBookingCard() {
        const dateCard = Utils.$('#step-date .service-booking-card');
        const bookNowBtn = dateCard?.querySelector('.service-continue-btn');
        if (!dateCard || !bookNowBtn || !this.selectedDate || !this.selectedTime) return;

        dateCard.querySelector('.selected-datetime')?.remove();

        const dateObj = new Date(this.selectedDate);
        const days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
        const months = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
        const dateStr = `${days[dateObj.getDay()]}, ${months[dateObj.getMonth()]} ${dateObj.getDate()}`;

        const div = document.createElement('div');
        div.className = 'selected-datetime';
        div.innerHTML = `
      <div class="salon-booking-datetime-display">
        <div>
          <div class="salon-booking-service-name">${dateStr}</div>
          <div class="salon-booking-service-meta">${this.selectedTime}</div>
        </div>
      </div>
    `;

        const totalSection = dateCard.querySelector('.salon-booking-total-section');
        const parent = bookNowBtn.parentElement;
        if (!parent) return;
        const referenceNode = totalSection && totalSection.parentElement === parent
            ? totalSection
            : bookNowBtn;
        parent.insertBefore(div, referenceNode);
    }

    async continue (event) {
        if (!this.selectedDate || !this.selectedTime) {
            event?.preventDefault();
            window.bnbShowBookingError('Please select both date and time');
            return;
        }
        const selectedServices = BookingState.data.selectedServices || [];
        if (!selectedServices.length) {
            event?.preventDefault();
            window.bnbShowBookingError('Please select at least one service');
            return;
        }
        if (!BookingState.data.branchId) {
            event?.preventDefault();
            window.bnbShowBookingError('Please select a location');
            return;
        }
        try {
            const params = new URLSearchParams({
                branch_id: BookingState.data.branchId,
                appointment_date: this.selectedDate,
                selected_services: selectedServices.map(service => service.id).join(','),
                start_hour: String(Utils.convertTimeToHour(this.selectedTime)),
            });
            const result = await Utils.fetchJSON(`/salon/check-resource-availability?${params.toString()}`);
            if (!result.available) {
                this.markTimeUnavailable(this.selectedTime);
                this.clearSelectedTime();
                Utils.showBookingPopup({
                    title: 'This time is unavailable',
                    message: result.error || 'Please choose another appointment time.',
                    actionText: 'Choose another time',
                });
                Utils.$('.fresha-time-slots')?.scrollIntoView({
                    behavior: 'smooth',
                    block: 'center'
                });
                return;
            }
        } catch (error) {
            console.error('Resource availability check failed:', error);
            reportBookingError('We could not confirm availability for this time. Please try again or choose another time.', error);
            return;
        }
        BookingState.data.selectedDateTime = {
            date: this.selectedDate,
            time: this.selectedTime
        };
        BookingState.persist();
        Utils.hide('#step-date');
        Utils.show('#step-beautician');
        BookingUrl.update('beautician');
        // Force reload beauticians when time/date changes
        if (window.beauticianHandler) {
            window.beauticianHandler.hasLoaded = false;
            window.beauticianHandler.triggerLoad();
        }
    }
}

// ============================================================================
// BEAUTICIAN HANDLER
// ============================================================================
class BeauticianHandler extends BaseHandler {
    constructor() {
        super();
        this.selectedBeautician = null;
        this.isLoading = false;
        this.hasLoaded = false;
        this.cachedData = null; // Store cached data
        this.lastRequestParams = null; // Track last request
    }

    bindEvents() {
        this.delegate('click', '.fresha-beautician-card', (e, card) => this.selectBeautician(card));
        this.delegate('click', '.service-continue-btn', e => {
            if (e.target.closest('#step-beautician')) this.continue();
        });
    }

    triggerLoad() {
        // Always reload if we don't have cached data or params changed
        const currentParams = this.getCurrentRequestParams();
        const paramsChanged = JSON.stringify(currentParams) !== JSON.stringify(this.lastRequestParams);

        if (!this.isLoading && (!this.hasLoaded || paramsChanged || !this.cachedData)) {
            this.loadBeauticians();
        } else if (this.cachedData) {
            // Use cached data if params haven't changed
            this.render(
                this.cachedData.beauticians || [],
                this.cachedData.busy_beauticians || [],
                this.cachedData.message || '',
                this.cachedData.any_professional_available !== false,
                !!this.cachedData.waiting_list_available
            );
        }
    }

    getCurrentRequestParams() {
        const {
            selectedServices,
            branchId,
            selectedDateTime
        } = BookingState.data;
        return {
            serviceIds: selectedServices.map(s => s.id).join(','),
            branchId: branchId,
            date: selectedDateTime?.date,
            time: selectedDateTime?.time
        };
    }

    async loadBeauticians() {
        if (this.isLoading) return;
        this.isLoading = true;

        const {
            selectedServices,
            branchId,
            selectedDateTime
        } = BookingState.data;

        if (!branchId) {
            this.render([], [], 'Please select a branch first');
            this.isLoading = false;
            this.hasLoaded = true;
            return;
        }

        this.showLoading();

        try {
            const serviceIds = selectedServices.map(s => s.id).join(',');
            let url = `/salon/get-beauticians-by-services?branch_id=${branchId}`;
            if (serviceIds) {
                url += `&service_ids=${serviceIds}`;
            }

            // IMPORTANT: Always include date and time if available
            if (selectedDateTime?.date && selectedDateTime?.time) {
                url += `&selected_date=${selectedDateTime.date}&selected_time=${selectedDateTime.time}`;
                console.log('Loading beauticians for:', selectedDateTime.date, selectedDateTime.time);
            }

            const data = await Utils.fetchJSON(url);

            // Cache the response
            this.cachedData = data;
            this.lastRequestParams = this.getCurrentRequestParams();

            console.log('Beautician data loaded:', {
                available: data.beauticians?.length || 0,
                busy: data.busy_beauticians?.length || 0,
                message: data.message
            });

            this.render(
                data.beauticians || [],
                data.busy_beauticians || [],
                data.message || '',
                data.any_professional_available !== false,
                !!data.waiting_list_available
            );
        } catch (error) {
            reportBookingError('Professionals could not be loaded. Please try again.', error);
            this.render([], [], 'Failed to load professionals. Please try again.', false);
        } finally {
            this.isLoading = false;
            this.hasLoaded = true;
        }
    }

    showLoading() {
        const container = Utils.$('.fresha-beautician-list');
        if (container) {
            container.innerHTML = '<div class="salon-booking-loading"><span class="salon-booking-loading-icon" aria-hidden="true">&#8635;</span><div>Loading professionals...</div></div>';
        }
    }

    render(beauticians, busyBeauticians, message, anyProfessionalAvailable = true, waitingListAvailable = false) {
        const container = Utils.$('.fresha-beautician-list');
        if (!container) return;

        this.anyIsWaitingList = !anyProfessionalAvailable && waitingListAvailable;

        console.log('Rendering beauticians:', {
            available: beauticians.length,
            busy: busyBeauticians.length,
            selectedTime: BookingState.data.selectedDateTime?.time
        });

        let html = message ? `<div class="salon-booking-availability-message info"><span aria-hidden="true">&#9432;</span><span>${message}</span></div>` : '';

        html += `
      <div class="fresha-beautician-card any-professional ${anyProfessionalAvailable || waitingListAvailable ? '' : 'busy'}" data-id="any">
        <div class="fresha-beautician-avatar"><div class="fresha-avatar-placeholder"><span aria-hidden="true">&#128101;</span></div></div>
        <div class="fresha-beautician-info">
          <h3 class="fresha-beautician-name">Any professional</h3>
          <div class="fresha-beautician-details"><span class="fresha-beautician-availability">${anyProfessionalAvailable ? 'Available' : (waitingListAvailable ? 'No professional is free at this time. Join the waiting list and our team will contact you to confirm a professional and time.' : 'Unavailable for all selected services')}</span></div>
        </div>
        <div class="fresha-beautician-pricing"><div class="fresha-beautician-price">$0.00</div></div>
        <button class="fresha-select-btn" ${anyProfessionalAvailable || waitingListAvailable ? '' : 'disabled'}><span aria-hidden="true">${anyProfessionalAvailable ? '&#10003;' : (waitingListAvailable ? '&#10003;' : '&#128339;')}</span></button>
      </div>
    `;

        beauticians.forEach(b => {
            html += `
        <div class="fresha-beautician-card available" data-id="${b.id}">
          <div class="fresha-beautician-avatar"><img src="${b.image}" alt="${b.name}" class="fresha-avatar-img" onerror="this.style.display='none'" /></div>
          <div class="fresha-beautician-info">
            <h3 class="fresha-beautician-name">${b.name}</h3>
            <div class="fresha-beautician-details"><div class="fresha-beautician-experience">Available</div></div>
          </div>
          <div class="fresha-beautician-pricing"><div class="fresha-beautician-price">${b.price}</div></div>
          <button class="fresha-select-btn"><span aria-hidden="true">+</span></button>
        </div>
      `;
        });

        if (busyBeauticians?.length > 0) {
            busyBeauticians.forEach(b => {
                html += `
          <div class="fresha-beautician-card busy" data-id="${b.id}">
            <div class="fresha-beautician-avatar"><img src="${b.image}" alt="${b.name}" class="fresha-avatar-img" onerror="this.style.display='none'" /></div>
            <div class="fresha-beautician-info">
              <h3 class="fresha-beautician-name">${b.name}</h3>
              <div class="fresha-beautician-details">
                <div class="salon-booking-busy-reason">${b.reason || 'Busy at this time'}</div>
              </div>
            </div>
            <div class="fresha-beautician-pricing"><div class="fresha-beautician-price">${b.price}</div></div>
            <button class="fresha-select-btn" disabled><span aria-hidden="true">&#128339;</span></button>
          </div>
        `;
            });
        }

        container.innerHTML = html;

        // Restore previous selection if still valid
        const previousSelection = BookingState.data.selectedBeautician;
        if (previousSelection && previousSelection.id === 'any') {
            // "Any" is always re-decided from this slot, so a stale waiting-list
            // choice from another time cannot carry over.
            this.resetToAny(anyProfessionalAvailable, waitingListAvailable);
        } else if (previousSelection && previousSelection.id) {
            const previousCard = container.querySelector(`[data-id="${previousSelection.id}"]`);
            if (previousCard && !previousCard.classList.contains('busy')) {
                previousCard.classList.add('selected');
                this.selectedBeautician = previousSelection;
            } else {
                // Previous selection not available, reset to "any"
                this.resetToAny(anyProfessionalAvailable, waitingListAvailable);
            }
        } else {
            this.resetToAny(anyProfessionalAvailable, waitingListAvailable);
        }

        this.updateBookingCard();
    }

    resetToAny(anyProfessionalAvailable = true, waitingListAvailable = false) {
        const anyCard = Utils.$('.fresha-beautician-card[data-id="any"]');
        const waitingList = !anyProfessionalAvailable && waitingListAvailable;
        if (anyCard && (anyProfessionalAvailable || waitingList)) anyCard.classList.add('selected');

        if (!anyProfessionalAvailable && !waitingList) {
            this.selectedBeautician = null;
            BookingState.data.selectedBeautician = null;
            BookingState.persist();
            return;
        }

        this.selectedBeautician = {
            id: 'any',
            name: 'Any professional',
            price: '$0.00',
            waitingList
        };
        BookingState.data.selectedBeautician = this.selectedBeautician;
        BookingState.persist();
    }

    selectBeautician(card) {
        if (card.classList.contains('busy')) return;

        Utils.$$('.fresha-beautician-card').forEach(c => c.classList.remove('selected'));
        card.classList.add('selected');

        this.selectedBeautician = {
            id: card.dataset.id,
            name: card.querySelector('.fresha-beautician-name').textContent,
            price: card.querySelector('.fresha-beautician-price').textContent,
            waitingList: card.dataset.id === 'any' && !!this.anyIsWaitingList
        };

        BookingState.data.selectedBeautician = this.selectedBeautician;
        BookingState.persist();
        this.updateBookingCard();
    }

    updateBookingCard() {
        const card = Utils.$('#step-beautician .service-booking-card');
        const bookNowBtn = card?.querySelector('.service-continue-btn');
        if (!card || !bookNowBtn) return;

        card.querySelector('.selected-booking-info')?.remove();

        const {
            selectedServices = [], selectedDateTime
        } = BookingState.data;
        const totals = Utils.calculateServiceTotals(selectedServices, this.selectedBeautician, selectedDateTime);
        let total = totals.totalWithSurcharge;
        let content = '<hr class="salon-booking-divider">';

        selectedServices.forEach(s => {
            content += `
        <div class="salon-booking-service-item salon-booking-service-item--bordered">
          <div class="salon-booking-service-content">
            <div class="salon-booking-service-name">${s.name}</div>
            <div class="salon-booking-service-meta">with ${this.selectedBeautician?.waitingList ? 'any professional (waiting list)' : (this.selectedBeautician?.name || 'any professional')}</div>
          </div>
          <div class="salon-booking-service-price-container">
            <div class="salon-booking-service-price">${s.price}</div>
          </div>
        </div>
      `;
        });

        if (selectedDateTime?.date) {
            const dateObj = new Date(selectedDateTime.date);
            const dateStr = dateObj.toLocaleDateString('en-US', {
                weekday: 'long',
                month: 'long',
                day: 'numeric'
            });
            content += `
        <div class="salon-booking-service-item salon-booking-service-item--bordered">
          <div class="salon-booking-service-content">
            <div class="salon-booking-service-name">${dateStr}</div>
            <div class="salon-booking-service-meta">${selectedDateTime.time}</div>
          </div>
        </div>
      `;
        }

        if (this.selectedBeautician && this.selectedBeautician.id !== 'any' && this.selectedBeautician.price !== '$0.00') {
            const beauticianPrice = Utils.parsePrice(this.selectedBeautician.price);
            if (beauticianPrice > 0) {
                content += `
          <div class="salon-booking-service-item salon-booking-service-item--bordered">
            <div class="salon-booking-service-content">
              <div class="salon-booking-service-name">${this.selectedBeautician.name}</div>
              <div class="salon-booking-service-meta">Professional fee</div>
            </div>
            <div class="salon-booking-service-price-container">
              <div class="salon-booking-service-price">${this.selectedBeautician.price}</div>
            </div>
          </div>
        `;
            }
        }

        content += `
      <div class="salon-booking-total-section">
        <div class="salon-booking-total-row">
          <span>Total</span>
          <span>${Utils.formatPrice(total)}</span>
        </div>
        ${totals.surchargeAmount > 0 ? `
        <div class="salon-booking-subtotal-row">
          <span>Surcharge:</span>
          <span>${Utils.formatPrice(totals.surchargeAmount)}</span>
        </div>
        ` : ''}
      </div>
    `;

        bookNowBtn.insertAdjacentHTML('beforebegin', `<div class="selected-booking-info">${content}</div>`);
    }

    continue () {
        if (!this.selectedBeautician) {
            window.bnbShowBookingError('Please select a professional');
            return;
        }

        BookingState.data.selectedBeautician = this.selectedBeautician;
        BookingState.persist();

        if (this.selectedBeautician.id !== 'any') {
            if (window.relatedServicesHandler) {
                window.relatedServicesHandler.checkAndShowModalForBeautician();
            } else {
                Utils.hide('#step-beautician');
                Utils.show('#step-customer');
                BookingUrl.update('customer');
                if (window.customerPaymentHandler) {
                    window.customerPaymentHandler.updateCustomerCard();
                }
            }
        } else {
            Utils.hide('#step-beautician');
            Utils.show('#step-customer');
            BookingUrl.update('customer');
            if (window.customerPaymentHandler) {
                window.customerPaymentHandler.updateCustomerCard();
            }
        }
    }
}

// ============================================================================
// CUSTOMER & PAYMENT HANDLER
// ============================================================================
class CustomerPaymentHandler extends BaseHandler {
    constructor() {
        super();
        this.initializeBookingFee();
    }

    async initializeBookingFee() {
        if (BookingState.data.bookingFee === null && BookingState.data.branchId) {
            try {
                const data = await Utils.fetchJSON(`/salon/get-branch-hours?branch_id=${BookingState.data.branchId}`);
                BookingState.data.bookingFee = parseFloat(data.booking_fee) || 0;
                BookingState.data.saturdaySurchargePercent = parseFloat(data.saturday_surcharge_percent) || 0;
                BookingState.data.sundaySurchargePercent = parseFloat(data.sunday_surcharge_percent) || 0;
            } catch (error) {
                reportBookingError('The booking fee could not be loaded. Please retry before continuing.', error);
                return false;
            }
        }
        return BookingState.data.bookingFee !== null;
    }

    bindEvents() {
        this.delegate('click', '.service-continue-btn', (e, btn) => {
            e.preventDefault();
            if (btn.closest('#step-customer')) this.handleCustomerContinue();
            else if (btn.closest('#step-payment')) this.handlePaymentContinue();
        });

        document.addEventListener('input', e => {
            if (e.target.id === 'card_number') {
                e.target.value = e.target.value.replace(/\s+/g, '').replace(/[^0-9]/gi, '').replace(/(.{4})/g, '$1 ').trim();
            }
            if (e.target.id === 'cvv') {
                e.target.value = e.target.value.replace(/[^0-9]/gi, '');
            }
        });
    }

    handleCustomerContinue() {
        const form = Utils.$('#customerForm');
        if (this.validateForm(form, ['first_name', 'last_name', 'email', 'mobile_phone'], 'agree_policy')) {
            this.saveCustomerData(form);
            Utils.hide('#step-customer');
            Utils.show('#step-payment');
            BookingUrl.update('payment');
            this.updatePaymentCard();
        }
    }

    handlePaymentContinue() {
        const form = Utils.$('#paymentForm');
        this.savePaymentData(form);
        this.completeBooking();
    }

    validateForm(form, requiredFields, checkboxField = null) {
        const formData = new FormData(form);
        for (let field of requiredFields) {
            if (!formData.get(field)?.trim()) {
                window.bnbShowBookingError(`Please fill in the ${field.replace('_', ' ')} field`);
                return false;
            }
        }
        if (checkboxField && !formData.get(checkboxField)) {
            window.bnbShowBookingError('Please agree to the terms and policy');
            return false;
        }
        return true;
    }

    saveCustomerData(form) {
        const formData = new FormData(form);
        BookingState.data.customerData = {
            first_name: formData.get('first_name'),
            last_name: formData.get('last_name'),
            email: formData.get('email'),
            mobile_phone: formData.get('mobile_phone'),
            other_phone: formData.get('other_phone') || '',
            pronouns: formData.get('pronouns') || '',
            agree_policy: !!formData.get('agree_policy'),
            remember_me: !!formData.get('remember_me')
        };
        BookingState.persist();
    }

    savePaymentData(form) {
        const formData = new FormData(form);
        // Get promo_code and payment_option from the payment card (right side)
        const card = Utils.$('#step-payment .service-booking-card');
        const promoCode = card?.querySelector('#promo_code')?.value || '';
        const paymentOption = card?.querySelector('#payment_option')?.value || 'full';
        const paymentAmount = card?.querySelector('#payment_amount')?.value || '0';
        const discountAmount = card?.querySelector('#discount_amount')?.value || '0';

        BookingState.data.paymentData = {
            billing_address: formData.get('billing_address'),
            city: formData.get('city'),
            state: formData.get('state'),
            postcode: formData.get('postcode'),
            promo_code: promoCode,
            payment_option: paymentOption,
            payment_amount: parseFloat(paymentAmount),
            discount_amount: parseFloat(discountAmount)
        };
        BookingState.persist();
    }

    async completeBooking() {
        const continueBtn = Utils.$('#step-payment .service-continue-btn');

        try {
            if (!await this.initializeBookingFee()) return;
            const {
                selectedServices,
                selectedDateTime,
                selectedBeautician,
                customerData,
                paymentData,
                branchId,
                bookingFee
            } = BookingState.data;

            // Defensive null checks
            if (!selectedServices || !selectedServices.length) {
                window.bnbShowBookingError('Please select at least one service');
                return;
            }
            if (!selectedDateTime || !selectedDateTime.date) {
                window.bnbShowBookingError('Please select a date and time');
                return;
            }
            if (!customerData || !customerData.email) {
                window.bnbShowBookingError('Please fill in your contact details first');
                return;
            }
            if (!branchId) {
                window.bnbShowBookingError('Please select a location');
                return;
            }

            // Show loading state
            if (continueBtn) {
                continueBtn.disabled = true;
                continueBtn.innerHTML = '<span aria-hidden="true">&#8635;</span> Processing...';
            }

            // Calculate total amount
            const totals = Utils.calculateServiceTotals(selectedServices, selectedBeautician, selectedDateTime);
            const serviceTotal = totals.totalWithSurcharge;
            const totalAmount = serviceTotal + (bookingFee || 0);
            const paymentOption = paymentData?.payment_option || 'full';
            const discountAmount = paymentData?.discount_amount || 0;
            const amountToPay = paymentOption === 'half'
                ? (totalAmount - discountAmount) / 2
                : (totalAmount - discountAmount);

            const bookingData = {
                first_name: customerData.first_name || '',
                last_name: customerData.last_name || '',
                email: customerData.email || '',
                mobile_phone: customerData.mobile_phone || '',
                other_phone: customerData.other_phone || '',
                pronouns: customerData.pronouns || '',
                agree_policy: customerData.agree_policy ? 'on' : 'off',
                remember_me: customerData.remember_me ? 'on' : 'off',
                salon_id: branchId,
                appointment_date: selectedDateTime.date,
                selected_services: JSON.stringify(selectedServices.map(s => s.id)),
                selected_beauticians: JSON.stringify(
                    selectedServices.reduce((acc, service) => {
                        acc[service.id] = (selectedBeautician && selectedBeautician.id !== 'any')
                            ? selectedBeautician.id : null;
                        return acc;
                    }, {})
                ),
                accept_waiting_list: selectedBeautician?.waitingList ? 'on' : 'off',
                selected_timeslots: JSON.stringify({
                    [selectedBeautician?.id || 'any']: {
                        start_hour: Utils.convertTimeToHour(selectedDateTime.time),
                        time: selectedDateTime.time
                    }
                }),
                amount_to_pay: amountToPay.toFixed(2),
                billing_address: paymentData?.billing_address || '',
                city: paymentData?.city || '',
                state: paymentData?.state || '',
                postcode: paymentData?.postcode || '',
                promo_code: paymentData?.promo_code || '',
                payment_option: paymentOption,
                discount_amount: discountAmount.toString(),
            };

            const formData = new FormData();
            Object.entries(bookingData).forEach(([key, value]) => {
                if (value !== null && value !== undefined) {
                    formData.append(key, value);
                }
            });

            // Create appointment on server
            const result = await Utils.fetchJSON('/salon/create-booking-payment', {
                method: 'POST',
                body: formData
            });

            if (!result.success) {
                const errorMessage = result.error || 'Failed to create booking';
                if (errorMessage.includes('cannot be booked') || errorMessage.includes('already booked')) {
                    Utils.showBookingPopup({
                        title: 'This time is no longer available',
                        message: errorMessage,
                        detail: 'Another booking may have taken this resource. Please go back and choose a different time, date, or service.',
                        actionText: 'Choose another time',
                        onClose: () => {
                            Utils.hide('#step-payment');
                            Utils.show('#step-date');
                            BookingUrl.update('date');
                        }
                    });
                    return;
                }
                throw new Error(errorMessage);
            }

            // If redirect to Odoo checkout (payment required)
            if (result.redirect_url) {
                BookingState.reset();
                window.location.href = result.redirect_url;
                return;
            }

            // No payment needed (free booking) - show inline confirmation
            BookingState.reset();
            this.showConfirmation();

        } catch (error) {
            console.error('Booking error:', error);
            reportBookingError(error.message || 'Booking could not be completed. Please contact the salon.', error);
            if (continueBtn) {
                continueBtn.disabled = false;
                continueBtn.innerHTML = 'Continue';
            }
        }
    }

    updateCustomerCard() {
        this.updateBookingSummaryCard('#step-customer');
    }

    updatePaymentCard() {
        // Update the payment booking card with services, date/time, and amounts
        const card = Utils.$('#step-payment .service-booking-card');
        if (!card) return;

        const {
            selectedServices,
            selectedDateTime,
            selectedBeautician,
            bookingFee
        } = BookingState.data;

        // Calculate service total
        const totals = Utils.calculateServiceTotals(selectedServices, selectedBeautician, selectedDateTime);
        const serviceTotal = totals.totalWithSurcharge;
        const surchargeAmount = totals.surchargeAmount;

        const currentBookingFee = bookingFee || 0;

        // Populate selected services summary
        const servicesSummary = card.querySelector('#selectedServicesSummary');
        if (servicesSummary && selectedServices.length) {
            let servicesHtml = '';
            selectedServices.forEach(s => {
                servicesHtml += `
                    <div class="d-flex justify-content-between align-items-start mb-2">
                        <div>
                            <div class="fw-semibold">${s.name}</div>
                            <div class="small text-muted">with ${selectedBeautician?.waitingList ? 'Any professional (waiting list)' : (selectedBeautician?.name || 'Any professional')}</div>
                            <div class="small text-primary">Pay at appointment</div>
                        </div>
                        <div class="fw-semibold">${Utils.formatPrice(serviceTotal)}</div>
                    </div>
                `;
            });
            servicesSummary.innerHTML = servicesHtml;
        }

        // Populate date/time summary
        const dateTimeSummary = card.querySelector('#dateTimeSummary');
        if (dateTimeSummary && selectedDateTime?.date && selectedDateTime?.time) {
            dateTimeSummary.innerHTML = `
                <div class="fw-semibold">${Utils.formatDate(selectedDateTime.date)}</div>
                <div class="small text-muted">${selectedDateTime.time}</div>
            `;
        }

        // Update amounts
        this.updatePaymentAmounts(serviceTotal, currentBookingFee, surchargeAmount);

        // Setup payment option change listener
        const paymentOptionSelect = card.querySelector('#payment_option');
        if (paymentOptionSelect) {
            paymentOptionSelect.removeEventListener('change', this._paymentOptionHandler);
            this._paymentOptionHandler = () => this.updatePaymentAmounts(serviceTotal, currentBookingFee, surchargeAmount);
            paymentOptionSelect.addEventListener('change', this._paymentOptionHandler);
        }

        // Setup promo code apply button
        const applyPromoBtn = card.querySelector('#applyPromoBtn');
        if (applyPromoBtn) {
            applyPromoBtn.removeEventListener('click', this._promoHandler);
            this._promoHandler = () => this.applyPromoCode(serviceTotal, currentBookingFee, surchargeAmount);
            applyPromoBtn.addEventListener('click', this._promoHandler);
        }
        const clearPromoBtn = card.querySelector('#clearPromoBtn');
        if (clearPromoBtn) {
            clearPromoBtn.removeEventListener('click', this._promoClearClickHandler);
            this._promoClearClickHandler = () => {
                const promoCodeInput = card.querySelector('#promo_code');
                const discountAmountInput = card.querySelector('#discount_amount');
                const promoFeedback = card.querySelector('#promoCodeFeedback');
                if (promoCodeInput) promoCodeInput.value = '';
                if (discountAmountInput) discountAmountInput.value = 0;
                if (promoFeedback) promoFeedback.innerHTML = '';
                this.updatePaymentAmounts(serviceTotal, currentBookingFee, surchargeAmount);
            };
            clearPromoBtn.addEventListener('click', this._promoClearClickHandler);
        }
        const promoCodeInput = card.querySelector('#promo_code');
        if (promoCodeInput) {
            promoCodeInput.removeEventListener('input', this._promoClearHandler);
            promoCodeInput.removeEventListener('change', this._promoClearHandler);
            this._promoClearHandler = () => {
                if (!promoCodeInput.value.trim()) {
                    const discountAmountInput = card.querySelector('#discount_amount');
                    const promoFeedback = card.querySelector('#promoCodeFeedback');
                    if (discountAmountInput) discountAmountInput.value = 0;
                    if (promoFeedback) promoFeedback.innerHTML = '';
                    this.updatePaymentAmounts(serviceTotal, currentBookingFee, surchargeAmount);
                }
            };
            promoCodeInput.addEventListener('input', this._promoClearHandler);
            promoCodeInput.addEventListener('change', this._promoClearHandler);
        }
    }

    updatePaymentAmounts(serviceTotal, bookingFee, surchargeAmount = 0) {
        const card = Utils.$('#step-payment .service-booking-card');
        if (!card) return;

        const paymentOption = card.querySelector('#payment_option')?.value || 'full';
        const promoCodeInput = card.querySelector('#promo_code');
        const discountAmountInput = card.querySelector('#discount_amount');
        const clearPromoBtn = card.querySelector('#clearPromoBtn');
        let discountAmount = parseFloat(discountAmountInput?.value || 0);
        if (promoCodeInput && !promoCodeInput.value.trim()) {
            discountAmount = 0;
            if (discountAmountInput) discountAmountInput.value = 0;
            if (clearPromoBtn) clearPromoBtn.style.display = 'none';
        } else if (clearPromoBtn) {
            clearPromoBtn.style.display = 'inline-block';
        }

        // Calculate amounts based on payment option
        let totalWithBookingFee = serviceTotal + bookingFee - discountAmount;
        if (totalWithBookingFee < 0) totalWithBookingFee = 0;
        let amountToPay = paymentOption === 'full' ? totalWithBookingFee : (totalWithBookingFee / 2);
        let remainingBalance = paymentOption === 'full' ? 0 : (totalWithBookingFee / 2);

        // Update display elements
        const serviceTotalDisplay = card.querySelector('#serviceTotalDisplay');
        const bookingFeeDisplay = card.querySelector('#bookingFeeDisplay');
        const surchargeRow = card.querySelector('#surchargeRow');
        const surchargeDisplay = card.querySelector('#surchargeDisplay');
        const amountToPayDisplay = card.querySelector('#amountToPayDisplay');
        const remainingBalanceDisplay = card.querySelector('#remainingBalanceDisplay');
        const remainingBalanceRow = card.querySelector('#remainingBalanceRow');
        const payAdvanceNote = card.querySelector('#payAdvanceNote');
        const paymentAmountInput = card.querySelector('#payment_amount');

        if (serviceTotalDisplay) serviceTotalDisplay.textContent = Utils.formatPrice(serviceTotal);
        if (bookingFeeDisplay) bookingFeeDisplay.textContent = Utils.formatPrice(bookingFee);
        if (surchargeDisplay) surchargeDisplay.textContent = Utils.formatPrice(surchargeAmount);
        if (surchargeRow) {
            surchargeRow.style.display = surchargeAmount > 0 ? 'flex' : 'none';
        }
        if (amountToPayDisplay) amountToPayDisplay.textContent = Utils.formatPrice(amountToPay);
        if (remainingBalanceDisplay) remainingBalanceDisplay.textContent = Utils.formatPrice(remainingBalance);
        if (paymentAmountInput) paymentAmountInput.value = amountToPay.toFixed(2);

        // Show/hide remaining balance row
        if (remainingBalanceRow) {
            remainingBalanceRow.style.display = paymentOption === 'half' ? 'block' : 'none';
        }
        if (payAdvanceNote) {
            payAdvanceNote.style.display = paymentOption === 'half' ? 'block' : 'none';
        }

        // Update discount row if there's a discount
        const discountRow = card.querySelector('#discountRow');
        const discountDisplay = card.querySelector('#discountDisplay');
        if (discountRow && discountDisplay) {
            if (discountAmount > 0 && promoCodeInput && promoCodeInput.value.trim()) {
                discountRow.style.display = 'flex';
                discountDisplay.textContent = `-${Utils.formatPrice(discountAmount)}`;
            } else {
                discountRow.style.display = 'none';
            }
        }
    }

    async applyPromoCode(serviceTotal, bookingFee, surchargeAmount = 0) {
        const card = Utils.$('#step-payment .service-booking-card');
        if (!card) return;

        const promoCodeInput = card.querySelector('#promo_code');
        const promoFeedback = card.querySelector('#promoCodeFeedback');
        const discountAmountInput = card.querySelector('#discount_amount');
        const promoCode = promoCodeInput?.value?.trim();

        if (!promoCode) {
            if (promoFeedback) {
                promoFeedback.innerHTML = '<span class="text-danger">Please enter a gift/discount code</span>';
            }
            return;
        }

        try {
            const formData = new FormData();
            formData.append('promo_code', promoCode);
            formData.append('total_amount', (serviceTotal + bookingFee).toString());
            formData.append('branch_id', BookingState.data.branchId || '');
            const result = await Utils.fetchJSON('/salon/promo/validate', {
                method: 'POST',
                body: formData
            });

            if (result.valid) {
                if (promoFeedback) {
                    promoFeedback.innerHTML = `<span class="text-success">${result.message}</span>`;
                }
                if (discountAmountInput) {
                    discountAmountInput.value = result.discount_amount;
                }
                this.updatePaymentAmounts(serviceTotal, bookingFee, surchargeAmount);
            } else {
                if (promoFeedback) {
                    promoFeedback.innerHTML = `<span class="text-danger">${result.message || 'Invalid gift/discount code'}</span>`;
                }
                if (discountAmountInput) {
                    discountAmountInput.value = 0;
                }
                this.updatePaymentAmounts(serviceTotal, bookingFee, surchargeAmount);
            }
        } catch (error) {
            reportBookingError('Your gift/discount code could not be checked. Please try again.', error);
            if (promoFeedback) {
                promoFeedback.innerHTML = '<span class="text-danger">Error validating gift/discount code</span>';
            }
        }
    }

    updateBookingSummaryCard(stepSelector) {
        const card = Utils.$(`${stepSelector} .service-booking-card`);
        const bookNowBtn = card?.querySelector('.service-continue-btn');
        if (!card || !bookNowBtn) return;

        card.querySelector('.selected-booking-info')?.remove();

        const {
            selectedServices,
            selectedDateTime,
            selectedBeautician,
            bookingFee
        } = BookingState.data;
        if (!selectedServices.length) return;

        const totals = Utils.calculateServiceTotals(selectedServices, selectedBeautician, selectedDateTime);
        const serviceTotal = totals.totalWithSurcharge;
        const surchargeAmount = totals.surchargeAmount;

        const currentBookingFee = bookingFee || 0;

        let html = '<hr class="salon-booking-divider">';

        selectedServices.forEach(s => {
            html += `
        <div class="salon-booking-service-item salon-booking-service-item--bordered">
          <div class="salon-booking-service-content">
            <div class="salon-booking-service-name">${s.name}</div>
            <div class="salon-booking-service-meta">with ${selectedBeautician?.waitingList ? 'any professional (waiting list)' : (selectedBeautician?.name || 'any professional')}</div>
            ${currentBookingFee > 0 ? '<div class="salon-booking-service-payment-note">Pay at appointment</div>' : ''}
          </div>
          <div class="salon-booking-service-price-container">
            <div class="salon-booking-service-price">${Utils.formatPrice(serviceTotal)}</div>
          </div>
        </div>
      `;
        });

        if (selectedDateTime?.date && selectedDateTime?.time) {
            html += `
        <div class="salon-booking-datetime-display">
          <div>
            <div class="salon-booking-service-name">${Utils.formatDate(selectedDateTime.date)}</div>
            <div class="salon-booking-service-meta">${selectedDateTime.time}</div>
          </div>
        </div>
      `;
        }

        if (currentBookingFee > 0) {
            html += `
        <div class="salon-booking-fee-section">
          <div>
            <div class="salon-booking-fee-title">Booking Fee</div>
            <div class="salon-booking-fee-subtitle">Pay now to secure appointment</div>
          </div>
          <div class="salon-booking-fee-amount">${Utils.formatPrice(currentBookingFee)}</div>
        </div>
        <div class="salon-booking-total-section">
          <div class="salon-booking-subtotal-row">
            <span class="salon-booking-subtotal-label">Service Total:</span>
            <span class="salon-booking-subtotal-value">${Utils.formatPrice(serviceTotal)}</span>
          </div>
          ${surchargeAmount > 0 ? `
          <div class="salon-booking-subtotal-row">
            <span class="salon-booking-subtotal-label">Surcharge:</span>
            <span class="salon-booking-subtotal-value">${Utils.formatPrice(surchargeAmount)}</span>
          </div>
          ` : ''}
          <div class="salon-booking-paynow-row">
            <span>Pay Now:</span>
            <span>${Utils.formatPrice(currentBookingFee)}</span>
          </div>
          <div class="salon-booking-remaining-note">
            Remaining ${Utils.formatPrice(serviceTotal)} due at appointment
          </div>
        </div>
      `;
        } else {
            html += `
        <div class="salon-booking-total-section">
          <div class="salon-booking-total-row">
            <span>Total</span>
            <span>${Utils.formatPrice(serviceTotal)}</span>
          </div>
          <div class="salon-booking-payment-note">Pay at appointment</div>
        </div>
      `;
        }

        bookNowBtn.insertAdjacentHTML('beforebegin', `<div class="selected-booking-info">${html}</div>`);
    }

    showConfirmation() {
        // Hide all steps
        StepGuard.stepOrder.forEach(s => {
            const el = Utils.$(`#step-${s}`);
            if (el) el.style.display = 'none';
        });
        Utils.show('#step-confirmation');
        BookingUrl.update('confirmation');
        this.populateConfirmationDetails();
        BookingState.reset();

        // Hide breadcrumbs on confirmation
        const breadcrumb = Utils.$('.fresha-breadcrumb');
        if (breadcrumb) breadcrumb.style.display = 'none';

        // Push extra history entries to trap back button on confirmation
        for (let i = 0; i < 3; i++) {
            history.pushState({ step: 'confirmation' }, '', window.location.href);
        }
    }

    populateConfirmationDetails() {
        const summaryEl = Utils.$('#confirmed-booking-summary');
        if (!summaryEl) return;

        const {
            selectedServices,
            selectedDateTime,
            selectedBeautician,
            bookingFee
        } = BookingState.data;

        const totals = Utils.calculateServiceTotals(selectedServices, selectedBeautician, selectedDateTime);
        const serviceTotal = totals.totalWithSurcharge;
        const surchargeAmount = totals.surchargeAmount;

        const currentBookingFee = bookingFee || 0;

        let html = '';

        if (selectedServices.length) {
            html += `
        <div class="confirmation-item">
            <div class="confirmation-label">Services</div>
            <div class="confirmation-value">${selectedServices.map(s => s.name).join(', ')}</div>
        </div>`;
        }

        if (selectedDateTime?.date && selectedDateTime?.time) {
            html += `
        <div class="confirmation-item">
            <div class="confirmation-label">Date & Time</div>
            <div class="confirmation-value">${Utils.formatDate(selectedDateTime.date)} at ${selectedDateTime.time}</div>
        </div>`;
        }

        if (selectedBeautician?.name) {
            html += `
        <div class="confirmation-item">
            <div class="confirmation-label">Professional</div>
            <div class="confirmation-value">${selectedBeautician.waitingList ? 'Waiting list: our team will contact you to confirm your professional and time' : selectedBeautician.name}</div>
        </div>`;
        }

        html += '<div class="payment-summary-section">';

        if (currentBookingFee > 0) {
            html += `
        <div class="payment-row">
            <span>Service Total (Pay at appointment):</span>
            <span style="color:#ff6b35;">${Utils.formatPrice(serviceTotal)}</span>
        </div>
        ${surchargeAmount > 0 ? `
        <div class="payment-row">
            <span>Surcharge:</span>
            <span style="color:#ff6b35;">${Utils.formatPrice(surchargeAmount)}</span>
        </div>` : ''}
        <div class="payment-row payment-total">
            <span>Booking Fee (Paid):</span>
            <span style="color:#10b981;">${Utils.formatPrice(currentBookingFee)}</span>
        </div>`;
        } else {
            html += `
        <div class="payment-row payment-total">
            <span>Service Total (Pay at appointment):</span>
            <span style="color:#10b981;">${Utils.formatPrice(serviceTotal)}</span>
        </div>`;
        }

        html += '</div>';

        summaryEl.innerHTML = html;
    }
}

// ============================================================================
// RELATED SERVICES HANDLER - Works for both Service and Beautician steps
// ============================================================================
class RelatedServicesHandler extends BaseHandler {
    constructor() {
        super();
        this.selectedAdditionalServices = [];
        this.relatedServicesData = null;
        this.isLoading = false;
        this.modal = null;
        this.currentContext = null; // 'service' or 'beautician'
    }

    bindEvents() {
        this.delegate('click', '.related-service-card', (e, card) => {
            if (!e.target.closest('.related-service-radio')) {
                this.toggleServiceSelection(card);
            }
        });

        this.delegate('click', '.related-service-radio', (e, radio) => {
            e.stopPropagation();
            const card = radio.closest('.related-service-card');
            if (card) {
                this.toggleServiceSelection(card);
            }
        });

        this.delegate('click', '.related-modal-no-thanks', (e, btn) => {
            e.preventDefault();
            this.closeModalAndContinue();
        });

        this.delegate('click', '.related-modal-add-btn', (e, btn) => {
            e.preventDefault();
            this.addServicesAndContinue();
        });

        this.delegate('click', '.related-modal-close-x', (e, btn) => {
            e.preventDefault();
            this.closeModalAndContinue();
        });

        this.delegate('click', '.related-services-modal-overlay', (e) => {
            if (e.target.classList.contains('related-services-modal-overlay')) {
                this.closeModalAndContinue();
            }
        });
    }

    // NEW: Called from Service step when Book is clicked
    async showRelatedProductsForService(serviceId) {
        this.currentContext = 'service';

        try {
            const formData = new FormData();
            formData.append('service_ids', JSON.stringify([serviceId]));
            formData.append('branch_id', BookingState.data.branchId || '');
            const data = await Utils.fetchJSON('/salon/get-all-related-products', {
                method: 'POST',
                body: formData
            });

            if (data.success && data.related_products && data.related_products.length > 0) {
                const formattedData = {
                    success: true,
                    related_services: data.related_products.map(product => ({
                        id: product.id,
                        name: product.name,
                        duration: product.duration,
                        duration_display: product.duration_display,
                        formatted_total_price: product.formatted_price,
                        addon_price: 0
                    })),
                    beautician_name: ''
                };

                this.showModalDirectly(formattedData);
            }
        } catch (error) {
            reportBookingError('Related services could not be loaded. Please try again.', error);
        }
    }

    // NEW: Called from Beautician step
    async checkAndShowModalForBeautician() {
        this.currentContext = 'beautician';

        const bookingData = BookingState.data;
        const selectedServices = bookingData.selectedServices;
        const selectedBeautician = bookingData.selectedBeautician;
        const selectedDateTime = bookingData.selectedDateTime;
        const branchId = bookingData.branchId;

        if (!selectedBeautician || selectedBeautician.id === 'any') {
            this.proceedToNextStep();
            return;
        }

        if (!selectedServices || selectedServices.length === 0) {
            this.proceedToNextStep();
            return;
        }

        if (!selectedDateTime || !selectedDateTime.date || !selectedDateTime.time) {
            this.proceedToNextStep();
            return;
        }

        if (!branchId) {
            this.proceedToNextStep();
            return;
        }

        this.showLoadingModal();
        await this.fetchRelatedServices();
    }

    showLoadingModal() {
        let modal = document.getElementById('relatedServicesModal');

        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'relatedServicesModal';
            modal.className = 'related-services-modal';
            document.body.appendChild(modal);
        }

        this.modal = modal;

        modal.innerHTML = `
      <div class="related-services-modal-overlay"></div>
      <div class="related-services-modal-content" role="dialog" aria-modal="true" aria-label="Extra services">
        <div class="related-modal-loading">
          <span style="font-size: 32px; color: #666;" aria-hidden="true">&#8635;</span>
          <p style="margin-top: 16px; color: #666;">Loading available services...</p>
        </div>
      </div>
    `;

        modal.style.display = 'flex';
        document.body.style.overflow = 'hidden';
    }

    async fetchRelatedServices() {
        const bookingData = BookingState.data;

        const serviceIds = bookingData.selectedServices.map(function(service) {
            return service.id;
        });

        const formData = new FormData();
        formData.append('service_ids', JSON.stringify(serviceIds));
        formData.append('beautician_id', bookingData.selectedBeautician.id);
        formData.append('selected_date', bookingData.selectedDateTime.date);
        formData.append('selected_time', bookingData.selectedDateTime.time);
        formData.append('branch_id', bookingData.branchId);

        try {
            const data = await Utils.fetchJSON('/salon/get-related-services', {
                method: 'POST',
                body: formData
            });
            this.relatedServicesData = data;

            const relatedCount = (data.related_services && data.related_services.length) || 0;

            if (data.success && relatedCount > 0) {
                this.renderModal(data);
            } else {
                this.closeModalAndContinue();
            }

        } catch (error) {
            reportBookingError('Related services could not be loaded. Please try again.', error);
            this.closeModalAndContinue();
        }
    }

    showModalDirectly(data) {
        if (!this.modal) {
            this.modal = document.getElementById('relatedServicesModal');
            if (!this.modal) {
                this.modal = document.createElement('div');
                this.modal.id = 'relatedServicesModal';
                this.modal.className = 'related-services-modal';
                document.body.appendChild(this.modal);
            }
        }

        this.renderModal(data);
        this.modal.style.display = 'flex';
        document.body.style.overflow = 'hidden';
    }

    renderModal(data) {
        if (!this.modal) {
            return;
        }

        const relatedServices = data.related_services || [];
        const beauticianName = data.beautician_name || '';

        let modalHTML = `
      <div class="related-services-modal-overlay"></div>
      <div class="related-services-modal-content" role="dialog" aria-modal="true" aria-label="Extra services">
        <button type="button" class="related-modal-close-x" aria-label="Close extra services">
          <span aria-hidden="true">&#10005;</span>
        </button>

        <div class="related-modal-header">
          <h2 class="related-modal-title">Add an extra service?</h2>
        </div>

        <div class="related-modal-body">
    `;

        if (relatedServices.length > 0) {
            for (let i = 0; i < relatedServices.length; i++) {
                const service = relatedServices[i];
                modalHTML += this.renderServiceCard(service);
            }
        } else {
            modalHTML += `
        <div style="text-align: center; padding: 40px 20px; color: #666;">
          <p>No additional services available</p>
        </div>
      `;
        }

        modalHTML += `
        </div>

        <div class="related-modal-footer">
          <button class="related-modal-no-thanks">No, thanks</button>
          <button class="related-modal-add-btn" disabled>Add to booking</button>
        </div>
      </div>
    `;

        this.modal.innerHTML = modalHTML;
        this.modal.style.display = 'flex';
    }

    renderServiceCard(service) {
        const hasDiscount = service.addon_price > 0;
        const discountText = hasDiscount ? `Save up to 10%` : '';

        let cardHTML = `
      <div class="related-service-card" data-service-id="${service.id}" data-service-name="${service.name}" data-service-price="${service.formatted_total_price}" data-service-duration="${service.duration}">
        <div class="related-service-info">
          <div class="related-service-header">
            <h3 class="related-service-name">${service.name}</h3>
            <button class="related-service-radio">
              <span class="radio-circle"></span>
            </button>
          </div>

          <div class="related-service-duration">${service.duration_display}</div>

          <div class="related-service-price-row">
            <span class="related-service-price">${service.formatted_total_price}</span>
    `;

        if (discountText) {
            cardHTML += `<span class="related-service-discount">${discountText}</span>`;
        }

        cardHTML += `
          </div>
        </div>
      </div>
    `;

        return cardHTML;
    }

    toggleServiceSelection(card) {
        const serviceId = card.dataset.serviceId;
        const serviceName = card.dataset.serviceName;
        const servicePrice = card.dataset.servicePrice;
        const serviceDuration = parseFloat(card.dataset.serviceDuration);

        const isCurrentlySelected = card.classList.contains('selected');

        if (isCurrentlySelected) {
            card.classList.remove('selected');
            this.selectedAdditionalServices = this.selectedAdditionalServices.filter(function(service) {
                return service.id !== serviceId;
            });
        } else {
            card.classList.add('selected');
            this.selectedAdditionalServices.push({
                id: serviceId,
                name: serviceName,
                price: servicePrice,
                duration: serviceDuration
            });
        }

        this.updateAddButton();
    }

    updateAddButton() {
        const addButton = this.modal.querySelector('.related-modal-add-btn');

        if (!addButton) {
            return;
        }

        if (this.selectedAdditionalServices.length > 0) {
            addButton.disabled = false;
            addButton.textContent = 'Add to booking';
        } else {
            addButton.disabled = true;
            addButton.textContent = 'Add to booking';
        }
    }

    addServicesAndContinue() {
        if (this.selectedAdditionalServices.length === 0) {
            this.closeModalAndContinue();
            return;
        }

        for (let i = 0; i < this.selectedAdditionalServices.length; i++) {
            const additionalService = this.selectedAdditionalServices[i];
            BookingState.data.selectedServices.push(additionalService);
        }
        BookingState.persist();

        // Dispatch event - card will update automatically
        document.dispatchEvent(new Event('servicesUpdated'));

        this.selectedAdditionalServices = [];
        this.closeModalAndContinue();
    }

    closeModalAndContinue() {
        if (this.modal) {
            this.modal.style.display = 'none';
            document.body.style.overflow = '';
        }

        // Determine where to go based on context
        if (this.currentContext === 'service') {
            // We're in service step, just close modal and stay there
            // User can continue selecting more services or click continue
            return;
        } else if (this.currentContext === 'beautician') {
            // We're in beautician step, proceed to customer step
            this.proceedToNextStep();
        }
    }

    proceedToNextStep() {
        Utils.hide('#step-beautician');
        Utils.show('#step-customer');
        BookingUrl.update('customer');

        if (window.customerPaymentHandler) {
            window.customerPaymentHandler.updateCustomerCard();
        }
    }
}

// ============================================================================
// INITIALIZATION
// ============================================================================
class MobileBookingActions {
    constructor(root, bar) {
        this.root = root;
        this.bar = bar;
        this.button = bar.querySelector('#bookingMobileContinue');
        this.summary = bar.querySelector('#bookingMobileSummary');
        this.button.addEventListener('click', () => {
            // Use the original step handler: validation and payment submission
            // stay in one place, including the existing double-submit guard.
            const original = this.currentStep()?.querySelector('.service-continue-btn, .fresha-continue-btn');
            if (original && !original.disabled) original.click();
            this.refresh();
        });
        this.observer = new MutationObserver(() => this.refresh());
        this.observer.observe(root, {childList: true, subtree: true, attributes: true, attributeFilter: ['style', 'disabled', 'class']});
        const updateKeyboard = () => {
            const editing = this.root.contains(document.activeElement)
                && document.activeElement.matches('input:not([type="checkbox"]):not([type="radio"]), textarea, select');
            document.body.classList.toggle('bnb-booking-keyboard-open', !!editing
                && !!window.visualViewport && window.innerHeight - window.visualViewport.height > 150);
        };
        window.visualViewport?.addEventListener('resize', updateKeyboard);
        document.addEventListener('focusin', updateKeyboard);
        document.addEventListener('focusout', () => setTimeout(updateKeyboard, 0));
        this.refresh();
    }

    currentStep() {
        return Array.from(this.root.children).find(el => el.id?.startsWith('step-')
            && el.style.display !== 'none' && getComputedStyle(el).display !== 'none');
    }

    refresh() {
        const step = this.currentStep();
        const original = step?.querySelector('.service-continue-btn, .fresha-continue-btn');
        const visible = !!original && !['step-location', 'step-confirmation'].includes(step.id);
        this.bar.hidden = !visible;
        document.body.classList.toggle('bnb-mobile-booking-active', visible);
        if (!visible) return;
        const count = BookingState.data.selectedServices.length;
        this.summary.textContent = count ? `${count} ${count === 1 ? 'service' : 'services'} selected` : 'Choose your services';
        this.button.textContent = step.id === 'step-payment' ? 'Secure checkout' : 'Continue';
        this.button.disabled = original.disabled;
    }

    static init() {
        const root = document.getElementById('fresha-booking-steps');
        const bar = document.getElementById('bookingMobileActions');
        if (root && bar) window.bnbMobileBookingController = new MobileBookingActions(root, bar);
    }
}

class BookingApp {
    static init() {
        console.log('Initializing Booking App...');

        // Step validation on page load — prevent URL manipulation
        const currentStep = BookingUrl.getCurrentStep();
        let initialStep = currentStep;
        if (!initialStep) {
            if (Utils.$('#step-service') && StepGuard.canAccessStep('service')) {
                initialStep = 'service';
            } else if (Utils.$('#step-location')) {
                initialStep = 'location';
            }
        }
        if (initialStep && StepGuard.canAccessStep(initialStep)) {
            if (!currentStep) {
                BookingUrl.update(initialStep, true);
            } else {
                BookingState.data.currentStep = currentStep;
                BookingState.persist();
            }
            StepGuard.stepOrder.forEach(s => {
                const el = document.querySelector(`#step-${s}`);
                if (el) el.style.display = (s === initialStep) ? 'block' : 'none';
            });
        }
        if (currentStep && currentStep !== 'location' && currentStep !== 'service') {
            if (!StepGuard.canAccessStep(currentStep)) {
                const allowed = StepGuard.getMaxAllowedStep();
                if (allowed === 'location') {
                    window.location.href = '/book-online';
                    return;
                }
                BookingUrl.update(allowed, true);
                StepGuard.stepOrder.forEach(s => {
                    const el = document.querySelector(`#step-${s}`);
                    if (el) el.style.display = (s === allowed) ? 'block' : 'none';
                });
            }
        }

        

        if (Utils.$('.location-salon-card')) {
            console.log('Initializing Location Handler');
            new LocationHandler();
        }

        if (Utils.$('.service-tab')) {
            console.log('Initializing Service Handler');
            new ServiceHandler();
        }

        if (Utils.$('.fresha-datetime-wrapper')) {
            console.log('Initializing DateTime Handler');
            window.dateTimeHandler = new DateTimeHandler();
        }

        if (Utils.$('.fresha-beautician-wrapper')) {
            console.log('Initializing Beautician Handler');
            window.beauticianHandler = new BeauticianHandler();
        }

        // Initialize related services handler (always initialize)
        console.log('Initializing Related Services Handler');
        window.relatedServicesHandler = new RelatedServicesHandler();

        if (Utils.$('.fresha-customer-wrapper') || Utils.$('.fresha-payment-wrapper')) {
            console.log('Initializing Customer Payment Handler');
            window.customerPaymentHandler = new CustomerPaymentHandler();
            const initStep = BookingUrl.getCurrentStep();
            if (initStep === 'customer') {
                window.customerPaymentHandler.updateCustomerCard();
            } else if (initStep === 'payment') {
                window.customerPaymentHandler.updatePaymentCard();
            }
        }

        // Lock breadcrumb clicks — prevent navigation via breadcrumbs
        document.querySelectorAll('.fresha-breadcrumb-item').forEach(item => {
            item.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
            });
        });

        // Add CSS to disable breadcrumb pointer events
        const breadcrumbStyle = document.createElement('style');
        breadcrumbStyle.textContent = `
            .fresha-breadcrumb-item {
                pointer-events: none;
                cursor: default;
            }
            #step-confirmation .fresha-breadcrumb {
                display: none !important;
            }
        `;
        document.head.appendChild(breadcrumbStyle);

        // Popstate handler — intercept browser back/forward
        window.addEventListener('popstate', (e) => {
            const step = BookingUrl.getCurrentStep();

            // If on confirmation, block ALL navigation
            if (StepGuard.isConfirmation()) {
                history.pushState({ step: 'confirmation' }, '', window.location.href);
                return;
            }

            // If trying to go to a step they haven't earned, push back
            if (step && !StepGuard.canAccessStep(step)) {
                const allowed = StepGuard.getMaxAllowedStep();
                BookingUrl.update(allowed, true);
                StepGuard.stepOrder.forEach(s => {
                    const el = document.querySelector(`#step-${s}`);
                    if (el) el.style.display = (s === allowed) ? 'block' : 'none';
                });
                return;
            }

            // Valid back navigation — show the correct step
            if (step) {
                StepGuard.stepOrder.forEach(s => {
                    const el = document.querySelector(`#step-${s}`);
                    if (el) el.style.display = (s === step) ? 'block' : 'none';
                });
            }
        });

        MobileBookingActions.init();
        console.log('Booking App Initialized');
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() {
        BookingApp.init();
    });
} else {
    BookingApp.init();
}
