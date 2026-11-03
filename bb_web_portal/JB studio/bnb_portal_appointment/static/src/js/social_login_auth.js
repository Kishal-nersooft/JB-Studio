// ============================================================================
// SOCIAL LOGIN HANDLER - FIXED WITH BETTER ERROR HANDLING
// ============================================================================
class SocialLoginHandler {
    constructor() {
        this.currentProvider = null;
        this.retryCount = 0;
        this.maxRetries = 3;
        this.init();
    }

    init() {
        // Wait for DOM to be fully ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => {
                this.safeBindEvents();
            });
        } else {
            this.safeBindEvents();
        }
    }

    safeBindEvents() {
        try {
            // Use setTimeout to ensure DOM is fully rendered
            setTimeout(() => {
                this.bindEvents();
            }, 100);
        } catch (error) {
            console.error('OAuth: Error binding events:', error);
            if (this.retryCount < this.maxRetries) {
                this.retryCount++;
                setTimeout(() => this.safeBindEvents(), 500);
            }
        }
    }

    bindEvents() {
        try {
            // Apple login button
            const appleBtn = document.getElementById('appleLoginBtn');
            if (appleBtn) {
                appleBtn.removeEventListener('click', this.handleAppleClick); // Remove existing listener
                this.handleAppleClick = (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    this.initiateOAuthFlow('apple');
                };
                appleBtn.addEventListener('click', this.handleAppleClick);
            }

            // Google login button
            const googleBtn = document.getElementById('googleLoginBtn');
            if (googleBtn) {
                googleBtn.removeEventListener('click', this.handleGoogleClick); // Remove existing listener
                this.handleGoogleClick = (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    this.initiateOAuthFlow('google');
                };
                googleBtn.addEventListener('click', this.handleGoogleClick);
            }

            // Check OAuth return
            this.checkOAuthReturn();
        } catch (error) {
            console.error('OAuth: Error in bindEvents:', error);
            this.showError('Sign-in could not be initialized. Please refresh the page or enter your details manually.');
        }
    }

    /**
     * Initiate OAuth flow - Redirect to provider
     */
    initiateOAuthFlow(provider) {
        try {
            // Get CURRENT URL (including all params and hash)
            const currentUrl = window.location.href;

            // Parse URL to extract path and query
            const url = new URL(currentUrl);
            const returnUrl = url.pathname + url.search;

            // Show loading state
            const btn = provider === 'apple'
                ? document.getElementById('appleLoginBtn')
                : document.getElementById('googleLoginBtn');

            if (btn) {
                btn.classList.add('loading');
                btn.disabled = true;
                const originalText = btn.innerHTML;
                btn.innerHTML = `
                    <span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
                    Redirecting...
                `;
            }

            // Redirect to OAuth endpoint
            const authUrl = provider === 'apple'
                ? `/auth/apple/login?return_url=${encodeURIComponent(returnUrl)}`
                : `/auth/google/login?return_url=${encodeURIComponent(returnUrl)}`;

            console.log('OAuth: Redirecting to', authUrl);

            // Use window.location.href instead of replace for better compatibility
            window.location.href = authUrl;

        } catch (error) {
            console.error('OAuth: Error initiating flow:', error);
            this.showError('Failed to start authentication. Please try again.');

            // Reset button state
            const btn = provider === 'apple'
                ? document.getElementById('appleLoginBtn')
                : document.getElementById('googleLoginBtn');
            if (btn) {
                btn.classList.remove('loading');
                btn.disabled = false;
            }
        }
    }

    /**
     * Check if we just returned from OAuth
     */
    async checkOAuthReturn() {
        try {
            const urlParams = new URLSearchParams(window.location.search);
            const socialAuth = urlParams.get('social_auth');

            console.log('OAuth: Checking return. social_auth =', socialAuth);

            if (socialAuth === 'success') {
                console.log('OAuth: Success flag detected, fetching user data...');

                // Clean URL WITHOUT reload
                this.cleanUrl();

                // Fetch user data with retry logic
                let userData = null;
                let attempts = 0;
                const maxAttempts = 3;

                while (attempts < maxAttempts && !userData) {
                    try {
                        userData = await this.fetchSocialUserData();
                        if (userData && userData.success && userData.data) {
                            break;
                        }
                    } catch (err) {
                        console.warn(`OAuth: Fetch attempt ${attempts + 1} failed:`, err);
                    }
                    attempts++;
                    if (attempts < maxAttempts) {
                        await new Promise(resolve => setTimeout(resolve, 1000)); // Wait 1s before retry
                    }
                }

                console.log('OAuth: User data received:', userData);

                if (userData && userData.success && userData.data) {
                    this.cacheSocialUserData(userData.data);
                    this.populateCustomerForm(userData.data);
                    this.showSuccess(`Successfully signed in with ${this.capitalizeProvider(userData.data.provider)}!`);
                } else {
                    this.showError('Could not retrieve user data. Please try again.');
                }
            } else {
                await this.restoreSocialUserData();
            }
        } catch (error) {
            console.error('OAuth: Error in checkOAuthReturn:', error);
            this.showError('An error occurred during sign-in. Please try again.');
        }
    }

    cacheSocialUserData(userData) {
        try {
            sessionStorage.setItem('bnb_social_auth_user_data', JSON.stringify(userData));
        } catch (error) {
            console.warn('OAuth: Could not cache customer details for this tab', error);
            this.showError('Your sign-in details could not be saved in this browser. Please check your customer details before continuing.');
        }
    }

    async restoreSocialUserData() {
        if (!document.getElementById('customerForm')) return;
        try {
            const cached = sessionStorage.getItem('bnb_social_auth_user_data');
            if (cached) {
                this.populateCustomerForm(JSON.parse(cached), { onlyEmpty: true, quiet: true });
            }
        } catch (error) {
            console.warn('OAuth: Ignoring invalid cached customer details', error);
            this.showError('Saved sign-in details could not be restored. Please check your customer details or sign in again.');
        }

        try {
            const result = await this.fetchSocialUserData();
            if (result?.success && result.data) {
                this.cacheSocialUserData(result.data);
                this.populateCustomerForm(result.data, { onlyEmpty: true, quiet: true });
            }
        } catch (error) {
            console.error('OAuth: Could not restore sign-in details', error);
            this.showError('Sign-in details could not be checked. Please try again or enter your details manually.');
        }
    }

    /**
     * Clean URL without page reload
     */
    cleanUrl() {
        try {
            const url = new URL(window.location.href);
            url.searchParams.delete('social_auth');
            window.history.replaceState({}, '', url.toString());
        } catch (error) {
            console.error('OAuth: Error cleaning URL:', error);
        }
    }

    /**
     * Fetch social auth user data from server
     */
    async fetchSocialUserData() {
        try {
            const response = await fetch('/auth/social/userdata', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    jsonrpc: "2.0",
                    method: "call",
                    params: {}
                })
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const result = await response.json();
            if (result.error) {
                const data = result.error.data;
                const expected = ['odoo.exceptions.ValidationError', 'odoo.exceptions.UserError'].includes(data?.name);
                throw new Error(expected && data.message ? data.message : 'Sign-in details could not be loaded. Please try again.');
            }
            return result.result || result;

        } catch (error) {
            console.error('OAuth: Fetch error:', error);
            throw error;
        }
    }

    /**
     * Populate customer form with OAuth user data
     */
    populateCustomerForm(userData, options = {}) {
        try {
            console.log('OAuth: Populating form with data:', userData);

            // Wait for form to be ready with improved logic
            let checkCount = 0;
            const maxChecks = 50; // 5 seconds max

            const waitForForm = setInterval(() => {
                checkCount++;
                const form = document.getElementById('customerForm');

                if (form) {
                    clearInterval(waitForForm);
                    this.fillFormFields(userData, options);
                } else if (checkCount >= maxChecks) {
                    clearInterval(waitForForm);
                    if (!options.quiet) {
                        console.warn('OAuth: Customer form not found after 5 seconds');
                        this.showError('Form not ready. Please refresh and try again.');
                    }
                }
            }, 100);

        } catch (error) {
            console.error('OAuth: Error populating form:', error);
        }
    }

    /**
     * Fill form fields with user data
     */
    fillFormFields(userData, options = {}) {
        try {
            const canFill = (field) => field && (!options.onlyEmpty || !field.value.trim());
            // First name
            if (userData.first_name) {
                const field = document.getElementById('first_name');
                if (canFill(field)) {
                    field.value = userData.first_name;
                    field.dispatchEvent(new Event('input', { bubbles: true }));
                    field.dispatchEvent(new Event('change', { bubbles: true }));
                }
            }

            // Last name
            if (userData.last_name) {
                const field = document.getElementById('last_name');
                if (canFill(field)) {
                    field.value = userData.last_name;
                    field.dispatchEvent(new Event('input', { bubbles: true }));
                    field.dispatchEvent(new Event('change', { bubbles: true }));
                }
            }

            // Email
            if (userData.email) {
                const field = document.getElementById('email');
                if (canFill(field)) {
                    field.value = userData.email;
                    field.dispatchEvent(new Event('input', { bubbles: true }));
                    field.dispatchEvent(new Event('change', { bubbles: true }));
                    field.setAttribute('readonly', 'true');
                    field.style.backgroundColor = '#f8f9fa';
                }
            }

            // Phone
            if (userData.phone) {
                const field = document.getElementById('mobile_phone');
                if (canFill(field)) {
                    field.value = userData.phone;
                    field.dispatchEvent(new Event('input', { bubbles: true }));
                    field.dispatchEvent(new Event('change', { bubbles: true }));
                }
            }

            // Pronouns
            if (userData.pronouns) {
                const field = document.getElementById('pronouns');
                if (field) {
                    field.value = userData.pronouns;
                    field.dispatchEvent(new Event('change', { bubbles: true }));
                }
            }

            // Remember me
            const rememberMe = document.getElementById('remember_me');
            if (rememberMe) {
                rememberMe.checked = true;
            }

            // Verification badge
            if (userData.verified_email) {
                this.showEmailVerificationBadge();
            }

            // Scroll to form
            this.scrollToForm();

        } catch (error) {
            console.error('OAuth: Error filling form fields:', error);
            this.showError('Your sign-in details could not be filled in. Please enter your details manually before continuing.');
        }
    }

    /**
     * Scroll to form smoothly
     */
    scrollToForm() {
        try {
            const form = document.getElementById('customerForm');
            if (form) {
                setTimeout(() => {
                    form.scrollIntoView({
                        behavior: 'smooth',
                        block: 'start'
                    });
                }, 100);
            }
        } catch (error) {
            console.error('OAuth: Error scrolling to form:', error);
        }
    }

    /**
     * Show email verification badge
     */
    showEmailVerificationBadge() {
        try {
            const emailField = document.getElementById('email');
            if (emailField && emailField.parentElement) {
                const existingBadge = emailField.parentElement.querySelector('.verified-badge');
                if (!existingBadge) {
                    const badge = document.createElement('span');
                    badge.className = 'verified-badge badge bg-success ms-2';
                    badge.innerHTML = '<i class="fa fa-check-circle"></i> Verified';
                    badge.style.fontSize = '0.75rem';
                    emailField.parentElement.appendChild(badge);
                }
            }
        } catch (error) {
            console.error('OAuth: Error showing verification badge:', error);
        }
    }

    /**
     * Capitalize provider name
     */
    capitalizeProvider(provider) {
        if (!provider) return '';
        return provider.charAt(0).toUpperCase() + provider.slice(1);
    }

    /**
     * Show success message
     */
    showSuccess(message) {
        try {
            console.log('OAuth: Showing success:', message);
            this.showToast(message, 'success');
        } catch (error) {
            console.error('OAuth: Error showing success:', error);
        }
    }

    /**
     * Show error message
     */
    showError(message) {
        try {
            console.error('OAuth: Showing error:', message);
            if (window.bnbShowBookingError) {
                window.bnbShowBookingError(message);
            } else {
                (window.bnbPendingBookingErrors ||= []).push(message);
            }
        } catch (error) {
            console.error('OAuth: Error showing error toast:', error);
            (window.bnbPendingBookingErrors ||= []).push(message);
        }
    }

    /**
     * Show toast notification
     */
    showToast(message, type) {
        try {
            const toast = document.createElement('div');
            toast.className = `social-auth-toast ${type}`;
            toast.innerHTML = `
                <div class="toast-icon">${type === 'success' ? '✓' : '✕'}</div>
                <div class="toast-message"></div>
            `;
            toast.querySelector('.toast-message').textContent = message;

            document.body.appendChild(toast);

            setTimeout(() => toast.classList.add('show'), 100);

            setTimeout(() => {
                toast.classList.remove('show');
                setTimeout(() => toast.remove(), 300);
            }, type === 'success' ? 4000 : 5000);

        } catch (error) {
            console.error('OAuth: Error showing toast:', error);
            this.showError(message);
        }
    }
}

// ============================================================================
// INITIALIZE - WITH ERROR HANDLING
// ============================================================================
(function() {
    'use strict';

    try {
        // Inject styles
        if (!document.getElementById('social-auth-toast-styles')) {
            const styleElement = document.createElement('style');
            styleElement.id = 'social-auth-toast-styles';
            styleElement.textContent = `
                .social-auth-toast {
                    position: fixed;
                    top: 20px;
                    right: 20px;
                    background: white;
                    padding: 15px 20px;
                    border-radius: 8px;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
                    display: flex;
                    align-items: center;
                    gap: 12px;
                    z-index: 10000;
                    transform: translateX(400px);
                    transition: transform 0.3s ease;
                    max-width: 350px;
                }
                
                .social-auth-toast.show {
                    transform: translateX(0);
                }
                
                .social-auth-toast.success {
                    border-left: 4px solid #28a745;
                }
                
                .social-auth-toast.error {
                    border-left: 4px solid #dc3545;
                }
                
                .social-auth-toast .toast-icon {
                    font-size: 24px;
                    font-weight: bold;
                    width: 30px;
                    height: 30px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    border-radius: 50%;
                }
                
                .social-auth-toast.success .toast-icon {
                    background: #28a745;
                    color: white;
                }
                
                .social-auth-toast.error .toast-icon {
                    background: #dc3545;
                    color: white;
                }
                
                .social-auth-toast .toast-message {
                    flex: 1;
                    font-size: 14px;
                    color: #333;
                }
                
                .verified-badge {
                    display: inline-block;
                    margin-top: 5px;
                }
                
                .social-login-btn.loading {
                    opacity: 0.7;
                    cursor: not-allowed;
                    pointer-events: none;
                }
            `;
            document.head.appendChild(styleElement);
        }

        // Initialize social login handler only once
        if (typeof window !== 'undefined' && !window.socialLoginHandler) {
            window.socialLoginHandler = new SocialLoginHandler();
            console.log('OAuth: SocialLoginHandler initialized successfully');
        }

    } catch (error) {
        console.error('OAuth: Failed to initialize SocialLoginHandler:', error);
        if (document.getElementById('appleLoginBtn') || document.getElementById('googleLoginBtn')) {
            const message = 'Sign-in could not be initialized. Please refresh the page or enter your details manually.';
            if (window.bnbShowBookingError) window.bnbShowBookingError(message);
            else (window.bnbPendingBookingErrors ||= []).push(message);
        }
    }
})();
