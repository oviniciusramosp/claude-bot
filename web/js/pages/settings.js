/**
 * settings.js — Settings page for claude-bot web dashboard.
 */
document.addEventListener('alpine:init', () => {
    Alpine.data('settingsPage', () => ({
        settings: { bot: {}, vault: {} },
        editingBot: false,
        editingVault: false,
        botForm: {},
        vaultForm: {},
        loading: true,
        saving: false,
        error: '',
        success: '',
        showSecrets: {},

        // Known bot .env keys with labels
        botKeys: [
            { key: 'TELEGRAM_BOT_TOKEN', label: 'Telegram Bot Token', sensitive: true },
            { key: 'TELEGRAM_CHAT_ID', label: 'Chat ID' },
            { key: 'CLAUDE_PATH', label: 'Claude CLI Path' },
            { key: 'CLAUDE_WORKSPACE', label: 'Workspace' },
            { key: 'ZAI_API_KEY', label: 'z.AI API Key', sensitive: true },
            { key: 'ZAI_BASE_URL', label: 'z.AI Base URL' },
            { key: 'MODEL_FALLBACK_CHAIN', label: 'Model Fallback Chain' },
            { key: 'WEB_PIN', label: 'Web Dashboard PIN', sensitive: true },
            { key: 'ADVISOR_MODEL', label: 'Advisor Model' },
        ],

        async load() {
            this.loading = true;
            this.settings = await api.get('/api/settings') || { bot: {}, vault: {} };
            this.loading = false;
        },

        startEditBot() {
            this.botForm = { ...this.settings.bot };
            this.editingBot = true;
            this.error = '';
            this.success = '';
        },

        startEditVault() {
            this.vaultForm = { ...this.settings.vault };
            this.editingVault = true;
            this.error = '';
            this.success = '';
        },

        cancelEdit() {
            this.editingBot = false;
            this.editingVault = false;
            this.error = '';
        },

        async saveBotSettings() {
            this.saving = true;
            this.error = '';
            this.success = '';
            const result = await api.put('/api/settings', {
                section: 'bot',
                data: this.botForm,
            });
            if (result?.ok) {
                this.editingBot = false;
                this.success = 'Bot settings saved';
                await this.load();
            } else {
                this.error = result?.error || 'Failed to save';
            }
            this.saving = false;
        },

        async saveVaultSettings() {
            this.saving = true;
            this.error = '';
            this.success = '';
            const result = await api.put('/api/settings', {
                section: 'vault',
                data: this.vaultForm,
            });
            if (result?.ok) {
                this.editingVault = false;
                this.success = 'Vault settings saved';
                await this.load();
            } else {
                this.error = result?.error || 'Failed to save';
            }
            this.saving = false;
        },

        async restartBot() {
            this.success = '';
            this.error = '';
            const result = await api.post('/api/bot/restart');
            if (result?.ok) {
                this.success = 'Bot restart initiated';
            } else {
                this.error = result?.message || 'Failed to restart';
            }
        },

        async stopBot() {
            this.success = '';
            this.error = '';
            const result = await api.post('/api/bot/stop');
            if (result?.ok) {
                this.success = 'Bot stopped';
            } else {
                this.error = result?.message || 'Failed to stop';
            }
        },

        async startBot() {
            this.success = '';
            this.error = '';
            const result = await api.post('/api/bot/start');
            if (result?.ok) {
                this.success = 'Bot started';
            } else {
                this.error = result?.message || 'Failed to start';
            }
        },

        toggleSecret(key) {
            this.showSecrets[key] = !this.showSecrets[key];
        },

        isSensitive(key) {
            const s = key.toUpperCase();
            return ['TOKEN', 'KEY', 'SECRET', 'PASSWORD', 'PIN'].some(w => s.includes(w));
        },

        displayValue(key, value) {
            if (this.isSensitive(key) && !this.showSecrets[key]) {
                return value; // Already masked by server
            }
            return value;
        },

        get vaultEnvEntries() {
            return Object.entries(this.settings.vault || {}).map(([k, v]) => ({
                key: k, value: v,
            }));
        },

        get botEnvEntries() {
            // Return known keys first, then any extras
            const known = this.botKeys.map(bk => ({
                ...bk,
                value: this.settings.bot?.[bk.key] || '',
                exists: bk.key in (this.settings.bot || {}),
            })).filter(e => e.exists);

            const knownKeys = new Set(this.botKeys.map(b => b.key));
            const extras = Object.entries(this.settings.bot || {})
                .filter(([k]) => !knownKeys.has(k))
                .map(([k, v]) => ({ key: k, label: k, value: v, sensitive: this.isSensitive(k) }));

            return [...known, ...extras];
        },
    }));
});
