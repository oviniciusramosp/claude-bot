/**
 * routines.js — Routines CRUD + run/stop page for claude-bot web dashboard.
 */
document.addEventListener('alpine:init', () => {
    Alpine.data('routinesPage', () => ({
        routines: [],
        agents: [],
        routinesState: {},
        filterAgent: '__all__',
        selectedRoutine: null,
        editing: false,
        editData: {},
        loading: true,
        saving: false,
        error: '',
        refreshTimer: null,

        models: [
            { id: 'sonnet', label: 'Sonnet 4.6' },
            { id: 'opus', label: 'Opus 4.6' },
            { id: 'haiku', label: 'Haiku 4.5' },
            { id: 'glm-5.1', label: 'GLM 5.1' },
            { id: 'glm-4.7', label: 'GLM 4.7' },
            { id: 'glm-4.5-air', label: 'GLM 4.5 Air' },
        ],

        async load() {
            this.loading = true;
            const [routines, agents, state] = await Promise.all([
                api.get('/api/routines'),
                api.get('/api/agents'),
                api.get('/api/routines-state'),
            ]);
            this.routines = routines || [];
            this.agents = agents || [];
            this.routinesState = state || {};
            this.loading = false;
        },

        init() {
            this.load();
            this.refreshTimer = setInterval(() => {
                // Only refresh state (lightweight), not full routines
                api.get('/api/routines-state').then(s => { if (s) this.routinesState = s; });
            }, 10000);
        },

        destroy() {
            if (this.refreshTimer) clearInterval(this.refreshTimer);
        },

        get filteredRoutines() {
            let list = this.routines;
            if (this.filterAgent !== '__all__') {
                list = list.filter(r => r.ownerAgentId === this.filterAgent);
            }
            return list.sort((a, b) => {
                // Enabled first, then by title
                if (a.enabled !== b.enabled) return a.enabled ? -1 : 1;
                return a.title.localeCompare(b.title);
            });
        },

        getExecution(routine) {
            const exec = this.routinesState[routine.id];
            if (!exec) return null;
            const slots = Object.entries(exec);
            if (slots.length === 0) return null;
            const latest = slots.sort((a, b) => b[0].localeCompare(a[0]))[0];
            return { slot: latest[0], ...latest[1] };
        },

        statusOf(routine) {
            const exec = this.getExecution(routine);
            return exec?.status || null;
        },

        selectRoutine(routine) {
            this.selectedRoutine = { ...routine };
            this.editing = false;
            this.error = '';
        },

        startEdit() {
            this.editData = JSON.parse(JSON.stringify(this.selectedRoutine));
            // Convert tags array to string for editing
            if (Array.isArray(this.editData.tags)) {
                this.editData.tagsStr = this.editData.tags.join(', ');
            }
            // Convert schedule for editing
            if (Array.isArray(this.editData.schedule?.times)) {
                this.editData.timesStr = this.editData.schedule.times.join(', ');
            } else {
                this.editData.timesStr = '';
            }
            if (Array.isArray(this.editData.schedule?.days)) {
                this.editData.daysStr = this.editData.schedule.days.join(', ');
            } else {
                this.editData.daysStr = '*';
            }
            this.editing = true;
            this.error = '';
        },

        cancelEdit() {
            this.editing = false;
            this.error = '';
        },

        async saveRoutine() {
            this.saving = true;
            this.error = '';

            const data = { ...this.editData };
            // Parse tags
            if (typeof data.tagsStr === 'string') {
                data.tags = data.tagsStr.split(',').map(t => t.trim()).filter(Boolean);
            }
            // Parse schedule
            data.schedule = data.schedule || {};
            if (data.timesStr) {
                data.schedule.times = data.timesStr.split(',').map(t => t.trim()).filter(Boolean);
            }
            if (data.daysStr) {
                const d = data.daysStr.trim();
                data.schedule.days = d === '*' ? ['*'] : d.split(',').map(t => t.trim()).filter(Boolean);
            }
            delete data.tagsStr;
            delete data.timesStr;
            delete data.daysStr;

            const result = await api.put(
                `/api/routines/${data.ownerAgentId}/${data.id}`,
                data,
            );

            if (result?.ok) {
                await this.load();
                this.selectedRoutine = this.routines.find(r =>
                    r.id === data.id && r.ownerAgentId === data.ownerAgentId
                ) || null;
                this.editing = false;
            } else {
                this.error = result?.error || 'Failed to save';
            }
            this.saving = false;
        },

        async runRoutine(routine) {
            await api.post(`/api/routines/${routine.ownerAgentId}/${routine.id}/run`);
            setTimeout(() => this.load(), 2000);
        },

        async stopRoutine(routine) {
            await api.post(`/api/routines/${routine.ownerAgentId}/${routine.id}/stop`);
            setTimeout(() => this.load(), 2000);
        },

        async toggleEnabled(routine) {
            const updated = { ...routine, enabled: !routine.enabled };
            await api.put(`/api/routines/${routine.ownerAgentId}/${routine.id}`, updated);
            await this.load();
        },

        async deleteRoutine(routine) {
            if (!confirm(`Delete routine "${routine.title}"?`)) return;
            const result = await api.del(`/api/routines/${routine.ownerAgentId}/${routine.id}`);
            if (result?.ok) {
                this.selectedRoutine = null;
                await this.load();
            }
        },

        backToList() {
            this.selectedRoutine = null;
            this.editing = false;
            this.error = '';
        },

        scheduleText(routine) {
            const s = routine.schedule;
            if (s?.interval) return `Every ${s.interval}`;
            const times = (s?.times || []).join(', ');
            const days = (s?.days || []);
            const daysStr = days.length === 1 && days[0] === '*' ? 'Daily' :
                days.join(', ');
            return times ? `${times} - ${daysStr}` : daysStr;
        },

        agentName(id) {
            return this.agents.find(a => a.id === id)?.name || id;
        },

        agentIcon(id) {
            return this.agents.find(a => a.id === id)?.icon || '';
        },

        modelBadgeClass(model) {
            if (model?.startsWith('glm')) return 'badge-glm';
            return `badge-${model || 'sonnet'}`;
        },

        modelLabel(id) {
            return this.models.find(m => m.id === id)?.label || id;
        },
    }));
});
