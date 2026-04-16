/**
 * app.js — Root Alpine.js application for claude-bot web dashboard.
 * Must be loaded AFTER all page components and AFTER api.js.
 */
document.addEventListener('alpine:init', () => {
    Alpine.data('app', () => ({
        authenticated: false,
        page: 'dashboard',
        checking: true,

        init() {
            // Check if already authenticated
            api.get('/api/status').then(data => {
                this.authenticated = data && !data._error;
                this.checking = false;
            });
            // Handle auth expiry
            window.addEventListener('auth-expired', () => {
                this.authenticated = false;
            });
            // Handle successful login
            window.addEventListener('login-success', () => {
                this.authenticated = true;
                this.page = 'dashboard';
            });
            // Logout from Settings page
            window.addEventListener('logout-request', () => this.logout());
        },

        navigate(p) {
            this.page = p;
        },

        async logout() {
            await api.post('/api/logout');
            this.authenticated = false;
        },
    }));
});
