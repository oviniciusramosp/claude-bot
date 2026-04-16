/**
 * api.js — Fetch wrapper for claude-bot web dashboard.
 * Handles auth (session cookie), 401 redirects, and JSON parsing.
 */
const api = {
    async get(path) {
        try {
            const resp = await fetch(path, { credentials: 'same-origin' });
            if (resp.status === 401) {
                window.dispatchEvent(new Event('auth-expired'));
                return null;
            }
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({ error: resp.statusText }));
                return { _error: true, status: resp.status, ...err };
            }
            return resp.json();
        } catch (e) {
            return { _error: true, error: e.message };
        }
    },

    async post(path, body = {}) {
        try {
            const resp = await fetch(path, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify(body),
            });
            if (resp.status === 401) {
                window.dispatchEvent(new Event('auth-expired'));
                return null;
            }
            return resp.json();
        } catch (e) {
            return { _error: true, error: e.message };
        }
    },

    async put(path, body = {}) {
        try {
            const resp = await fetch(path, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify(body),
            });
            if (resp.status === 401) {
                window.dispatchEvent(new Event('auth-expired'));
                return null;
            }
            return resp.json();
        } catch (e) {
            return { _error: true, error: e.message };
        }
    },

    async del(path) {
        try {
            const resp = await fetch(path, {
                method: 'DELETE',
                credentials: 'same-origin',
            });
            if (resp.status === 401) {
                window.dispatchEvent(new Event('auth-expired'));
                return null;
            }
            return resp.json();
        } catch (e) {
            return { _error: true, error: e.message };
        }
    },
};
