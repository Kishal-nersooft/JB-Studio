// ============================================================================
// BREADCRUMB NAVIGATION HANDLER
// ============================================================================
class BreadcrumbNavigation {
    constructor() {
        this.steps = [
            { id: 'step-service', name: 'Services', index: 0, slug: 'service' },
            { id: 'step-date', name: 'Time', index: 1, slug: 'date' },
            { id: 'step-beautician', name: 'Professional', index: 2, slug: 'beautician' },
            { id: 'step-customer', name: 'Customer', index: 3, slug: 'customer' },
            { id: 'step-payment', name: 'Payment', index: 4, slug: 'payment' }
        ];
        this.currentStepIndex = 0;
        this.init();
    }

    init() {
    const appliedFromUrl = this.applyStepFromUrl();

    // Find current visible step
    if (!appliedFromUrl) {
        this.steps.forEach((step, index) => {
            const el = document.getElementById(step.id);
            if (el && el.style.display !== 'none') {
                this.currentStepIndex = index;
            }
        });
    }

    // Bind breadcrumb clicks
    document.addEventListener('click', (e) => {
        const breadcrumbItem = e.target.closest('.fresha-breadcrumb-item');
        if (breadcrumbItem) {
            const stepIndex = parseInt(breadcrumbItem.dataset.step);
            if (!isNaN(stepIndex)) {
                this.goToStep(stepIndex);
            }
        }
    });

    this.addNavigationButtons();
    this.animateBreadcrumbChange(); // Changed from updateBreadcrumb()
}

    getFirstInvalidStepIndex() {
        const bookingData = window.bookingData || {};

        if (!bookingData.selectedServices?.length) return 0;
        if (!bookingData.selectedDateTime?.date || !bookingData.selectedDateTime?.time) return 1;
        if (!bookingData.selectedBeautician) return 2;
        return null;
    }

    getStepIndexFromUrl() {
        const slug = window.BookingUrl?.getCurrentStep
            ? window.BookingUrl.getCurrentStep()
            : window.location.pathname.split('/').filter(Boolean).slice(-1)[0];

        const targetIndex = this.steps.findIndex(step => step.slug === slug);
        return targetIndex >= 0 ? targetIndex : null;
    }

    applyStepFromUrl() {
        let targetIndex = this.getStepIndexFromUrl();
        if (targetIndex === null) return false;

        const firstInvalid = this.getFirstInvalidStepIndex();
        if (firstInvalid !== null && targetIndex > 4) {
            targetIndex = firstInvalid;
        }

        const targetId = this.steps[targetIndex]?.id;
        const targetStep = targetId ? document.getElementById(targetId) : null;
        if (!targetStep) return false;

        this.steps.forEach(step => {
            const el = document.getElementById(step.id);
            if (el) el.style.display = 'none';
        });

        targetStep.style.display = 'block';
        this.currentStepIndex = targetIndex;
        this.animateBreadcrumbChange();
        this.onStepChange(targetIndex);
        return true;
    }

    // A single back button at the top of each step, above the breadcrumb.
    // Moving forward is done with the Continue button only.
    addNavigationButtons() {
        this.steps.forEach((step, index) => {
            const stepEl = document.getElementById(step.id);
            if (!stepEl) return;

            // Skip if buttons already exist
            if (stepEl.querySelector('.step-navigation-buttons')) return;

            const breadcrumb = stepEl.querySelector('.fresha-breadcrumb');
            if (!breadcrumb) return;

            breadcrumb.insertAdjacentHTML('beforebegin', `
                <div class="step-navigation-buttons">
                    <button type="button" class="step-nav-btn step-nav-prev" data-step="${index}"
                            aria-label="${index > 0 ? `Back to ${this.steps[index - 1].name}` : 'Back to locations'}">
                        <i class="fa fa-chevron-left" aria-hidden="true"></i>
                    </button>
                </div>
            `);
        });

        // Bind button clicks
        document.addEventListener('click', (e) => {
            const prevBtn = e.target.closest('.step-nav-prev');
            if (!prevBtn) return;
            e.preventDefault();
            const stepIndex = parseInt(prevBtn.dataset.step);
            this.animateButton(prevBtn);
            if (stepIndex === 0) {
                // Services is the first step: go back to choosing a salon
                window.location.href = '/book-online';
                return;
            }
            this.goToStep(stepIndex - 1);
        });
    }

    animateButton(btn) {
        btn.style.transform = 'scale(0.9)';
        setTimeout(() => {
            btn.style.transform = 'scale(1)';
        }, 150);
    }

    validateStep(stepIndex) {
        const bookingData = window.bookingData || {};

        switch (stepIndex) {
            case 0:
                if (!bookingData.selectedServices?.length) {
                    window.bnbShowBookingError('Please select at least one service');
                    return false;
                }
                return true;
            case 1:
                if (!bookingData.selectedDateTime?.date || !bookingData.selectedDateTime?.time) {
                    window.bnbShowBookingError('Please select date and time');
                    return false;
                }
                return true;
            case 2:
                if (!bookingData.selectedBeautician) {
                    window.bnbShowBookingError('Please select a professional');
                    return false;
                }
                return true;
            case 3:
                const form = document.getElementById('customerForm');
                if (!form) return true;
                const formData = new FormData(form);
                if (!formData.get('first_name') || !formData.get('email')) {
                    window.bnbShowBookingError('Please fill in required customer details');
                    return false;
                }
                return true;
            default:
                return true;
        }
    }

    goToStep(targetIndex) {
    if (targetIndex < 0 || targetIndex >= this.steps.length) return;

    // Validate all steps between current and target if moving forward
    if (targetIndex > this.currentStepIndex) {
        for (let i = this.currentStepIndex; i < targetIndex; i++) {
            if (!this.validateStep(i)) return;
        }
    }

    // Hide all steps
    this.steps.forEach(step => {
        const el = document.getElementById(step.id);
        if (el) el.style.display = 'none';
    });

    // Show target step
    const targetStep = document.getElementById(this.steps[targetIndex].id);
    if (targetStep) {
        targetStep.style.display = 'block';
        this.currentStepIndex = targetIndex;
        this.animateBreadcrumbChange(); // This updates colors
        this.onStepChange(targetIndex);
        if (window.BookingUrl?.update) {
            window.BookingUrl.update(this.steps[targetIndex].slug);
        }
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }
}

    // Every step has its own copy of the breadcrumb, so each copy marks the
    // step it sits in as active. That keeps it right even when base.js moves
    // between steps without going through goToStep. Colours and the "pop"
    // animation are in main-booking.scss.
    animateBreadcrumbChange() {
    document.querySelectorAll('.fresha-breadcrumb').forEach(breadcrumb => {
        const owner = this.steps.findIndex(step => breadcrumb.closest(`#${step.id}`));
        const current = owner >= 0 ? owner : this.currentStepIndex;

        breadcrumb.querySelectorAll('.fresha-breadcrumb-item').forEach((item, index) => {
            item.classList.toggle('completed', index < current);
            item.classList.toggle('active', index === current);
            if (index === current) {
                item.setAttribute('aria-current', 'step');
            } else {
                item.removeAttribute('aria-current');
            }
        });

        breadcrumb.querySelectorAll('.fa-chevron-right').forEach((chevron, index) => {
            chevron.classList.toggle('completed', index < current);
        });
    });
}

    onStepChange(stepIndex) {
    const bookingData = window.bookingData || {};

    switch (stepIndex) {
        case 0:
            // When returning to service step, refresh the service card
            if (window.serviceHandler) {
                window.serviceHandler.updateCard();
            }
            break;
        case 1:
            // When entering date step, update dates and refresh card
            if (window.dateTimeHandler) {
                window.dateTimeHandler.updateDates();
            }
            if (window.serviceHandler) {
                window.serviceHandler.updateDateStepCard();
            }
            break;
        case 2:
            // When entering beautician step, reload beauticians and refresh card
            if (window.beauticianHandler) {
                // Always reload when entering this step to reflect any service/time changes
                window.beauticianHandler.hasLoaded = false;
                window.beauticianHandler.triggerLoad();
            }
            break;
        case 3:
            // When entering customer step, refresh the booking summary
            if (window.customerPaymentHandler) {
                window.customerPaymentHandler.updateCustomerCard();
            }
            break;
        case 4:
            // When entering payment step, refresh the payment summary
            if (window.customerPaymentHandler) {
                window.customerPaymentHandler.updatePaymentCard();
            }
            break;
    }
}
}

// Initialize breadcrumb navigation
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        window.breadcrumbNav = new BreadcrumbNavigation();
    });
} else {
    window.breadcrumbNav = new BreadcrumbNavigation();
}