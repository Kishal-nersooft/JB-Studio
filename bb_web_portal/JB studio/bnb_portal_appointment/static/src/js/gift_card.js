document.addEventListener('DOMContentLoaded', () => {
    const form = document.querySelector('.bnb-gift-voucher-form');
    if (!form) return;
    const custom = form.querySelector('#bnb_gift_custom_amount');
    const amount = form.querySelector('input[name="amount"]');
    const recipientFields = form.querySelector('.bnb-gift-recipient-email');
    const recipientEmail = form.querySelector('input[name="recipient_email"]');
    const updateAmount = () => {
        const selected = form.querySelector('input[name="amount_fixed"]:checked');
        amount.value = selected ? selected.value : custom.value;
    };
    form.querySelectorAll('input[name="amount_fixed"]').forEach(input => input.addEventListener('change', updateAmount));
    custom.addEventListener('input', () => {
        form.querySelectorAll('input[name="amount_fixed"]').forEach(input => { input.checked = false; });
        updateAmount();
    });
    form.querySelectorAll('input[name="send_to"]').forEach(input => input.addEventListener('change', () => {
        const isRecipient = form.querySelector('input[name="send_to"]:checked').value === 'recipient';
        recipientFields.hidden = !isRecipient;
        recipientEmail.required = isRecipient;
    }));
    form.addEventListener('submit', updateAmount);
});
