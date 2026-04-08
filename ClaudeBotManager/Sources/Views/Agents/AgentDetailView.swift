import SwiftUI

struct AgentDetailView: View {
    @EnvironmentObject var appState: AppState
    @Environment(\.dismiss) var dismiss

    @State private var agent: Agent
    @State private var isSaving = false
    @State private var showDeleteConfirm = false
    @State private var selectedTab = 0
    @State private var newChatId = ""
    @State private var newThreadId = ""

    init(agent: Agent) {
        _agent = State(initialValue: agent)
    }

    var body: some View {
        NavigationStack {
            TabView(selection: $selectedTab) {
                AgentInfoTab(agent: $agent)
                    .tabItem { Label("Info", systemImage: "person.circle") }
                    .tag(0)

                AgentTelegramTab(agent: $agent, newChatId: $newChatId, newThreadId: $newThreadId)
                    .tabItem { Label("Telegram", systemImage: "paperplane.fill") }
                    .tag(1)
            }
            .navigationTitle(agent.name)
            .navigationSubtitle(agent.id)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        isSaving = true
                        Task {
                            try? await appState.saveAgent(agent)
                            isSaving = false
                            dismiss()
                        }
                    }
                    .disabled(isSaving)
                }
                ToolbarItem(placement: .destructiveAction) {
                    Button(role: .destructive) {
                        showDeleteConfirm = true
                    } label: {
                        Label("Move to Trash", systemImage: "trash")
                    }
                    .foregroundStyle(Color.statusRed)
                }
            }
            .confirmationDialog("Move Agent to Trash?", isPresented: $showDeleteConfirm, titleVisibility: .visible) {
                Button("Move to Trash", role: .destructive) {
                    Task {
                        try? await appState.deleteAgent(id: agent.id)
                        dismiss()
                    }
                }
            } message: {
                Text("The agent and all its files will be moved to Trash. You can restore from Finder.")
            }
        }
        .frame(minWidth: 600, minHeight: 500)
    }
}

// MARK: - Info Tab

struct AgentInfoTab: View {
    @Binding var agent: Agent

    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                identityCard
                instructionsCard
            }
            .padding(20)
        }
    }

    private var identityCard: some View {
        GlassCard {
            VStack(spacing: 14) {
                HStack {
                    Text(agent.icon)
                        .font(.system(size: 50))
                    VStack(alignment: .leading, spacing: 4) {
                        TextField("Name", text: $agent.name)
                            .font(.title2.bold())
                            .textFieldStyle(.plain)
                        TextField("Description", text: $agent.description)
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                            .textFieldStyle(.plain)
                    }
                    Spacer()
                }

                HStack {
                    Text("Icon (emoji)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Spacer()
                    TextField("Emoji", text: $agent.icon)
                        .frame(width: 60)
                        .textFieldStyle(.roundedBorder)
                        .multilineTextAlignment(.center)
                }

                HStack {
                    Text("Model")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Spacer()
                    Picker("", selection: $agent.model) {
                        ForEach(Agent.modelOptions, id: \.self) { m in
                            Text(m.capitalized).tag(m)
                        }
                    }
                    .pickerStyle(.segmented)
                    .frame(width: 200)
                }

                TextField("Personality", text: $agent.personality, prompt: Text("Brief personality description"))
                    .textFieldStyle(.roundedBorder)
                    .font(.caption)

                Toggle("Default Agent", isOn: $agent.isDefault)
                    .font(.caption)
            }
        }
    }

    private var instructionsCard: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 8) {
                Text("Instructions (CLAUDE.md)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                TextEditor(text: $agent.instructions)
                    .font(.system(.caption, design: .monospaced))
                    .frame(minHeight: 200)
                    .scrollContentBackground(.hidden)
                    .background(Color.primary.opacity(0.03))
                    .clipShape(RoundedRectangle(cornerRadius: 8))
            }
        }
    }
}

// MARK: - Telegram Tab

struct AgentTelegramTab: View {
    @Binding var agent: Agent
    @Binding var newChatId: String
    @Binding var newThreadId: String

    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                existingMappingsCard
                addMappingCard
            }
            .padding(20)
        }
    }

    private var existingMappingsCard: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 12) {
                Text("Telegram Topic Mappings")
                    .font(.headline)
                Text("This agent responds to messages in the following chats/topics. Mappings created via Telegram are shown automatically.")
                    .font(.caption)
                    .foregroundStyle(.secondary)

                Divider()

                if agent.topicMappings.isEmpty {
                    HStack {
                        Image(systemName: "info.circle")
                            .foregroundStyle(.secondary)
                        Text("No Telegram topics linked yet")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.vertical, 4)
                } else {
                    ForEach(agent.topicMappings) { mapping in
                        MappingRow(mapping: mapping)
                    }
                }
            }
        }
    }

    private var addMappingCard: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 10) {
                Text("Add Manual Mapping")
                    .font(.caption.bold())
                    .foregroundStyle(.secondary)

                HStack {
                    TextField("Chat ID", text: $newChatId)
                        .textFieldStyle(.roundedBorder)
                        .font(.caption)
                    TextField("Thread ID (optional)", text: $newThreadId)
                        .textFieldStyle(.roundedBorder)
                        .font(.caption)
                    Button("Add") {
                        let mapping = Agent.TopicMapping(
                            chatId: newChatId,
                            threadId: newThreadId.isEmpty ? nil : newThreadId,
                            sessionName: "agent-\(agent.id)"
                        )
                        agent.topicMappings.append(mapping)
                        newChatId = ""
                        newThreadId = ""
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(newChatId.isEmpty)
                    .font(.caption)
                }
            }
        }
    }
}

struct MappingRow: View {
    var mapping: Agent.TopicMapping

    var body: some View {
        HStack {
            Image(systemName: "paperplane.fill")
                .foregroundStyle(Color.statusBlue)
                .font(.caption)
            VStack(alignment: .leading, spacing: 2) {
                Text("Chat \(mapping.chatId)")
                    .font(.caption.monospacedDigit())
                if let tid = mapping.threadId {
                    Text("Topic \(tid)")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
            Spacer()
            Text(mapping.sessionName)
                .font(.caption2)
                .foregroundStyle(.tertiary)
        }
    }
}

// MARK: - Main Agent Detail

struct MainAgentDetailView: View {
    @EnvironmentObject var appState: AppState
    @Environment(\.dismiss) var dismiss

    @State private var agent: Agent
    @State private var isSaving = false

    init(agent: Agent) {
        _agent = State(initialValue: agent)
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 16) {
                    identityCard
                    instructionsCard
                }
                .padding(20)
            }
            .navigationTitle("Main (Default)")
            .navigationSubtitle("Instruções do bot quando nenhum agente está ativo")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        isSaving = true
                        Task {
                            try? await appState.saveMainAgent(agent)
                            isSaving = false
                            dismiss()
                        }
                    }
                    .disabled(isSaving)
                }
            }
        }
        .frame(minWidth: 640, minHeight: 540)
    }

    private var identityCard: some View {
        GlassCard {
            HStack(spacing: 14) {
                Text(agent.icon)
                    .font(.system(size: 44))
                VStack(alignment: .leading, spacing: 4) {
                    Text(agent.name)
                        .font(.title2.bold())
                    Text(agent.description)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Image(systemName: "pin.fill")
                    .foregroundStyle(Color.statusBlue)
                    .font(.callout)
            }
        }
    }

    private var instructionsCard: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 8) {
                Label("~/claude-bot/CLAUDE.md", systemImage: "doc.text")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                TextEditor(text: $agent.instructions)
                    .font(.system(.caption, design: .monospaced))
                    .frame(minHeight: 360)
                    .scrollContentBackground(.hidden)
                    .background(Color.primary.opacity(0.03))
                    .clipShape(RoundedRectangle(cornerRadius: 8))
            }
        }
    }
}
