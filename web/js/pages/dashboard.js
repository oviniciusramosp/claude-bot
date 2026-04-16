/**
 * dashboard.js — Dashboard: bot status, Claude + ZAI usage, today's timeline.
 */
document.addEventListener('alpine:init', () => {
    Alpine.data('dashboardPage', () => ({
        botStatus: null,
        routinesState: {},
        routines: [],
        agents: [],
        usage: null,
        loading: true,
        refreshTimer: null,

        async load() {
            this.loading = true;
            const [status, state, routines, agents, usage] = await Promise.all([
                api.get('/api/status'),
                api.get('/api/routines-state'),
                api.get('/api/routines'),
                api.get('/api/agents'),
                api.get('/api/usage'),
            ]);
            this.botStatus = status;
            this.routinesState = state || {};
            this.routines = routines || [];
            this.agents = agents || [];
            this.usage = usage;
            this.loading = false;
        },

        init() {
            this.load();
            this.refreshTimer = setInterval(() => this.load(), 15000);
        },

        destroy() {
            if (this.refreshTimer) clearInterval(this.refreshTimer);
        },

        // ── Helpers ───────────────────────────────────────────────────────
        /** Compute how far (0-100%) we are through the current 7-day window.
         *  If resetsAt is known, uses the actual renewal boundary.
         *  Otherwise falls back to Mon-Sun calendar week. */
        _weekProgress(resetsAtISO) {
            const now = Date.now();
            if (resetsAtISO) {
                const resetsAt = new Date(resetsAtISO).getTime();
                const windowStart = resetsAt - 7 * 24 * 3600 * 1000;
                const windowLen   = 7 * 24 * 3600 * 1000;
                return Math.max(0, Math.min(100, (now - windowStart) / windowLen * 100));
            }
            // Fallback: Mon=0 … Sun=6
            const d = new Date();
            const dayIndex = (d.getDay() + 6) % 7;
            const minutesIntoDay = d.getHours() * 60 + d.getMinutes();
            return ((dayIndex + minutesIntoDay / 1440) / 7) * 100;
        },

        _renewLabel(resetsAtISO) {
            if (!resetsAtISO) return null;
            const d = new Date(resetsAtISO);
            const days = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
            const day = days[d.getDay()];
            const time = d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
            const secsLeft = Math.max(0, Math.floor((d - Date.now()) / 1000));
            const dd = Math.floor(secsLeft / 86400);
            const h  = Math.floor((secsLeft % 86400) / 3600);
            const left = dd > 0 ? `${dd}d ${h}h` : `${h}h`;
            return `Renew ${day} ${time} (${left})`;
        },

        _paceLabel(actualPct, weekProgress) {
            const expected = Math.round(weekProgress);
            const diff = Math.round(actualPct) - expected;
            if (diff <= 0) return `On pace: ${diff}% (expected ${expected}%)`;
            return `Above pace: +${diff}% (expected ${expected}%)`;
        },

        // ── Bot status ────────────────────────────────────────────────────
        get isRunning() { return this.botStatus?.status === 'ok'; },

        get uptimeFormatted() {
            const s = this.botStatus?.uptime_seconds;
            if (!s) return '--';
            const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
            return h > 0 ? `${h}h ${m}m` : `${m}m`;
        },

        get activeRunners() { return this.botStatus?.active_runners || 0; },

        // ── Claude usage ──────────────────────────────────────────────────
        get claudeAvailable() { return this.usage?.claude?.available || false; },
        get claudeHasTokenData() { return this.usage?.claude?.hasTokenData || false; },
        get claudeHasData() { return this.claudeAvailable || this.claudeHasTokenData; },

        get claudePercent() {
            if (this.claudeAvailable) return this.usage?.claude?.weeklyPercent || 0;
            return this.usage?.claude?.weeklyTokenPercent || 0;
        },

        get claudeWeekProgress() {
            return this._weekProgress(this.usage?.claude?.weeklyResetsAt);
        },

        get claudePaceLabel() {
            return this._paceLabel(this.claudePercent, this.claudeWeekProgress);
        },

        get claudeRenewLabel() {
            return this._renewLabel(this.usage?.claude?.weeklyResetsAt);
        },

        get claudePlanName() { return this.usage?.claude?.planName || null; },
        get claudeRateTier()  { return this.usage?.claude?.rateTier || null; },

        // ── ZAI usage ─────────────────────────────────────────────────────
        get zaiConfigured()  { return this.usage?.zai?.configured  || false; },
        get zaiAvailable()   { return this.usage?.zai?.available   || false; },
        get zaiHasCostData() { return this.usage?.zai?.hasCostData || false; },
        get zaiHasPlanInfo() { return !!(this.usage?.zai?.planLevel); },

        get zaiPercent()        { return this.usage?.zai?.weeklyPercent  || 0; },
        get zaiSessionPercent() { return this.usage?.zai?.sessionPercent || 0; },
        get zaiWeeklyLabel()    { return this.usage?.zai?.weeklyLabel    || '—'; },
        get zaiPlanName()       { return this.usage?.zai?.planName       || null; },

        get zaiWeeklyCost() {
            const c = this.usage?.zai?.weeklyCostUSD || 0;
            return c > 0 ? `$${c.toFixed(2)}` : null;
        },
        get zaiTodayCost() {
            const c = this.usage?.zai?.todayCostUSD || 0;
            return c > 0 ? `$${c.toFixed(2)}` : null;
        },

        get zaiWeekProgress() {
            return this._weekProgress(this.usage?.zai?.weeklyResetsAt);
        },
        get zaiPaceLabel() {
            return this._paceLabel(this.zaiPercent, this.zaiWeekProgress);
        },
        get zaiRenewLabel() {
            return this._renewLabel(this.usage?.zai?.weeklyResetsAt);
        },

        // GLM-specific counts (from macOS app)
        get glmAgentCount()   { return this.usage?.zai?.glmAgentCount   || 0; },
        get glmRoutineCount() { return this.usage?.zai?.glmRoutineCount || 0; },
        get glmStepCount()    { return this.usage?.zai?.glmStepCount    || 0; },

        // ── Counts ────────────────────────────────────────────────────────
        get counts() { return this.usage?.counts || { agents: 0, routines: 0, skills: 0 }; },

        // ── Timeline ──────────────────────────────────────────────────────
        get timeline() {
            const now = new Date();
            const nowStr = `${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}`;
            const entries = [];
            for (const r of this.routines) {
                if (!r.enabled) continue;
                for (const t of (r.schedule?.times || [])) {
                    const exec = this.routinesState[r.id]?.[t] || null;
                    const agent = this.agents.find(a => a.id === r.ownerAgentId);
                    entries.push({
                        id: `${r.id}-${t}`,
                        time: t,
                        title: r.title,
                        agentIcon: agent?.icon || '🤖',
                        status: exec?.status || 'pending',
                        isPast: t <= nowStr,
                    });
                }
            }
            entries.sort((a, b) => a.time.localeCompare(b.time));
            // Inject "now" marker between past and future
            let nowInserted = false;
            const result = [];
            for (let i = 0; i < entries.length; i++) {
                const e = entries[i];
                if (!nowInserted && !e.isPast) {
                    result.push({ _isNow: true, id: '__now__' });
                    nowInserted = true;
                }
                result.push(e);
            }
            return result;
        },

        get completedCount() {
            return this.routines.flatMap(r =>
                Object.values(this.routinesState[r.id] || {})
            ).filter(e => e.status === 'completed').length;
        },
        get runningCount() {
            return this.routines.flatMap(r =>
                Object.values(this.routinesState[r.id] || {})
            ).filter(e => e.status === 'running').length;
        },
        get failedCount() {
            return this.routines.flatMap(r =>
                Object.values(this.routinesState[r.id] || {})
            ).filter(e => e.status === 'failed').length;
        },
        get scheduledCount() {
            return this.timeline.filter(e => !e._isNow && e.status === 'pending').length;
        },

        // ── Actions ───────────────────────────────────────────────────────
        async restartBot() { await api.post('/api/bot/restart'); setTimeout(() => this.load(), 3000); },
        async stopBot()    { await api.post('/api/bot/stop');    setTimeout(() => this.load(), 2000); },
        async startBot()   { await api.post('/api/bot/start');   setTimeout(() => this.load(), 3000); },
        async runRoutine(routine) {
            await api.post(`/api/routines/${routine.ownerAgentId}/${routine.id}/run`);
            setTimeout(() => this.load(), 2000);
        },
    }));
});
