/**
 * login.js — PIN entry page for claude-bot web dashboard.
 */
document.addEventListener('alpine:init', () => {
    Alpine.data('loginPage', () => ({
        pin: '',
        error: '',
        loading: false,

        async submit() {
            if (!this.pin) return;
            this.loading = true;
            this.error = '';
            try {
                const resp = await fetch('/api/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({ pin: this.pin }),
                });
                const data = await resp.json();
                if (data.ok) {
                    // Bubble up to root app state
                    window.dispatchEvent(new Event('login-success'));
                } else {
                    this.error = data.error || 'Invalid PIN';
                    this.pin = '';
                }
            } catch (e) {
                this.error = 'Connection failed';
            }
            this.loading = false;
        },

        handleKey(e) {
            if (e.key === 'Enter') this.submit();
        },
    }));
});
