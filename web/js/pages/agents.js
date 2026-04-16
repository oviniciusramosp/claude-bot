/**
 * agents.js — Agents CRUD page for claude-bot web dashboard.
 */
document.addEventListener('alpine:init', () => {
    Alpine.data('agentsPage', () => ({
        agents: [],
        selectedAgent: null,
        editing: false,
        creating: false,
        editData: {},
        loading: true,
        saving: false,
        error: '',

        models: [
            { id: 'sonnet', label: 'Sonnet 4.6', provider: 'anthropic' },
            { id: 'opus', label: 'Opus 4.6', provider: 'anthropic' },
            { id: 'haiku', label: 'Haiku 4.5', provider: 'anthropic' },
            { id: 'glm-5.1', label: 'GLM 5.1', provider: 'zai' },
            { id: 'glm-4.7', label: 'GLM 4.7', provider: 'zai' },
            { id: 'glm-4.5-air', label: 'GLM 4.5 Air', provider: 'zai' },
        ],

        colors: ['grey', 'red', 'orange', 'yellow', 'green', 'teal', 'blue', 'purple'],

        async load() {
            this.loading = true;
            this.agents = await api.get('/api/agents') || [];
            this.loading = false;
        },

        get mainAgent() {
            return this.agents.find(a => a.id === 'main' || a.isDefault);
        },

        get customAgents() {
            return this.agents.filter(a => a.id !== 'main' && !a.isDefault);
        },

        selectAgent(agent) {
            this.selectedAgent = { ...agent };
            this.editing = false;
            this.creating = false;
            this.error = '';
        },

        startEdit() {
            this.editData = { ...this.selectedAgent };
            this.editing = true;
            this.error = '';
        },

        startCreate() {
            this.editData = {
                id: '',
                name: '',
                icon: '',
                description: '',
                model: 'sonnet',
                color: 'grey',
                tags: [],
                personality: '',
                chatId: '',
                threadId: '',
            };
            this.creating = true;
            this.editing = true;
            this.selectedAgent = null;
            this.error = '';
        },

        cancelEdit() {
            this.editing = false;
            this.creating = false;
            this.error = '';
        },

        async saveAgent() {
            this.saving = true;
            this.error = '';
            // Generate ID from name for new agents
            if (this.creating) {
                this.editData.id = this.editData.name
                    .toLowerCase()
                    .replace(/[^a-z0-9]+/g, '-')
                    .replace(/^-|-$/g, '');
                if (!this.editData.id) {
                    this.error = 'Name is required';
                    this.saving = false;
                    return;
                }
            }
            // Parse tags from comma-separated string if needed
            if (typeof this.editData.tags === 'string') {
                this.editData.tags = this.editData.tags.split(',').map(t => t.trim()).filter(Boolean);
            }

            let result;
            if (this.creating) {
                result = await api.post('/api/agents', this.editData);
            } else {
                result = await api.put(`/api/agents/${this.editData.id}`, this.editData);
            }

            if (result?.ok) {
                await this.load();
                this.selectedAgent = this.agents.find(a => a.id === this.editData.id) || null;
                this.editing = false;
                this.creating = false;
            } else {
                this.error = result?.error || 'Failed to save';
            }
            this.saving = false;
        },

        async deleteAgent(agent) {
            if (!confirm(`Delete agent "${agent.name}"? This moves the entire agent folder to Trash.`)) return;
            const result = await api.del(`/api/agents/${agent.id}`);
            if (result?.ok) {
                this.selectedAgent = null;
                await this.load();
            } else {
                this.error = result?.error || 'Failed to delete';
            }
        },

        backToList() {
            this.selectedAgent = null;
            this.editing = false;
            this.creating = false;
            this.error = '';
        },

        modelLabel(id) {
            return this.models.find(m => m.id === id)?.label || id;
        },

        modelBadgeClass(model) {
            if (model?.startsWith('glm')) return 'badge-glm';
            return `badge-${model || 'sonnet'}`;
        },
    }));
});
