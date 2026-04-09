import SwiftUI

struct AgentDetailView: View {
    @EnvironmentObject var appState: AppState
    @Environment(\.dismiss) var dismiss

    @State private var agent: Agent
    @State private var isSaving = false
    @State private var showDeleteConfirm = false

    init(agent: Agent) {
        _agent = State(initialValue: agent)
    }

    /// Fallback chat ID from vault/.env TELEGRAM_GROUP_ID
    private var defaultChatId: String {
        appState.vaultEnvEntries.first(where: { $0.id == "TELEGRAM_GROUP_ID" })?.value ?? ""
    }

    var body: some View {
        VStack(spacing: 0) {
            configScrollView
            Divider()
            footerBar
        }
        .frame(minWidth: 720, minHeight: 560)
        .background(Color(.windowBackgroundColor))
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
        .onAppear {
            // Pre-fill chat ID from vault/.env when empty
            if agent.chatId.isEmpty && !defaultChatId.isEmpty {
                agent.chatId = defaultChatId
            }
        }
    }

    // MARK: - Config Scroll View

    private var configScrollView: some View {
        ScrollView {
            VStack(spacing: 0) {
                identitySection
                Divider().padding(.horizontal, Spacing.xl)
                configSection
                Divider().padding(.horizontal, Spacing.xl)
                personalitySection
                Divider().padding(.horizontal, Spacing.xl)
                instructionsSection
                Divider().padding(.horizontal, Spacing.xl)
                specializationsSection
                if !agent.otherInstructions.isEmpty {
                    Divider().padding(.horizontal, Spacing.xl)
                    otherSection
                }
            }
        }
    }

    // MARK: - Identity Section

    private var identitySection: some View {
        HStack(alignment: .top, spacing: 10) {
            // Emoji button — click to open system emoji picker
            Button {
                NSApp.orderFrontCharacterPalette(nil)
            } label: {
                Text(agent.icon)
                    .font(.system(size: 40))
            }
            .buttonStyle(.plain)
            .frame(width: 44)

            VStack(alignment: .leading, spacing: 10) {
                VStack(alignment: .leading, spacing: 0) {
                    TextField("Name", text: $agent.name)
                        .font(.system(size: 17, weight: .bold))
                        .textFieldStyle(.plain)
                    Text("Agents/\(agent.id)/")
                        .font(.system(size: 10))
                        .foregroundStyle(Color(white: 0.45))
                }
                TextField("Description", text: $agent.description,
                          prompt: Text("What this agent does").foregroundStyle(.quaternary))
                    .font(.system(size: 13))
                    .foregroundStyle(Color(white: 0.45))
                    .textFieldStyle(.plain)
            }

            Spacer()

            Toggle("", isOn: $agent.isDefault)
                .labelsHidden()
                .toggleStyle(.switch)
        }
        .padding(.horizontal, 20)
        .padding(.trailing, 12)
        .padding(.vertical, 16)
    }

    // MARK: - Config Section (Model + Telegram)

    private func modelDisplayName(_ id: String) -> String {
        switch id {
        case "opus":  return "Opus 4.6"
        case "haiku": return "Claude Haiku"
        default:      return "Claude Sonnet"
        }
    }

    private func modelDescription(_ id: String) -> String {
        switch id {
        case "opus":  return "Most capable for ambitious work"
        case "haiku": return "Fastest and most compact"
        default:      return "Balanced performance and speed"
        }
    }

    private var configSection: some View {
        detailFormSection(icon: "gear", title: "Configuration") {
            HStack(alignment: .top, spacing: 40) {
                // Model
                VStack(alignment: .leading, spacing: 5) {
                    Text("Model").font(.system(size: 10)).foregroundStyle(Color(white: 0.45))
                    menuPicker(label: modelDisplayName(agent.model), selection: $agent.model, options: [
                        ("sonnet", modelDisplayName("sonnet")),
                        ("opus", modelDisplayName("opus")),
                        ("haiku", modelDisplayName("haiku")),
                    ])
                    Text(modelDescription(agent.model))
                        .font(.system(size: 10))
                        .foregroundStyle(Color(white: 0.45))
                }
                .frame(maxWidth: .infinity)

                // Telegram
                VStack(alignment: .leading, spacing: 5) {
                    Text("Telegram Topic").font(.system(size: 10)).foregroundStyle(Color(white: 0.45))
                    HStack(spacing: 8) {
                        TextField("Chat ID", text: $agent.chatId)
                            .font(.system(size: 13, design: .monospaced))
                            .textFieldStyle(.plain)
                            .padding(.horizontal, 8)
                            .frame(height: 24)
                            .background(Color.black.opacity(0.05))
                            .clipShape(RoundedRectangle(cornerRadius: 6))
                        TextField("Thread", text: $agent.threadId)
                            .font(.system(size: 13, design: .monospaced))
                            .textFieldStyle(.plain)
                            .padding(.horizontal, 8)
                            .frame(width: 80, height: 24)
                            .background(Color.black.opacity(0.05))
                            .clipShape(RoundedRectangle(cornerRadius: 6))
                    }
                    Text("Chat and thread where this agent responds")
                        .font(.system(size: 10))
                        .foregroundStyle(Color(white: 0.45))
                }
                .frame(maxWidth: .infinity)
            }
        }
    }

    // MARK: - Personality Section

    private var personalitySection: some View {
        detailFormSection(icon: "person.text.rectangle", title: "Personality and Tone") {
            TextEditor(text: $agent.personalityAndTone)
                .font(.system(size: 13))
                .frame(minHeight: 80)
                .padding(8)
                .scrollContentBackground(.hidden)
                .background(Color.white)
                .clipShape(RoundedRectangle(cornerRadius: 6))
                .overlay(
                    RoundedRectangle(cornerRadius: 6)
                        .stroke(Color.black.opacity(0.08), lineWidth: 1)
                )
        }
    }

    // MARK: - Instructions Section

    private var instructionsSection: some View {
        detailFormSection(icon: "text.alignleft", title: "Instructions") {
            TextEditor(text: $agent.instructions)
                .font(.system(size: 13))
                .frame(minHeight: 120)
                .padding(8)
                .scrollContentBackground(.hidden)
                .background(Color.white)
                .clipShape(RoundedRectangle(cornerRadius: 6))
                .overlay(
                    RoundedRectangle(cornerRadius: 6)
                        .stroke(Color.black.opacity(0.08), lineWidth: 1)
                )
        }
    }

    // MARK: - Specializations Section

    private var specializationsSection: some View {
        detailFormSection(icon: "star", title: "Specializations") {
            TextEditor(text: $agent.specializations)
                .font(.system(size: 13))
                .frame(minHeight: 80)
                .padding(8)
                .scrollContentBackground(.hidden)
                .background(Color.white)
                .clipShape(RoundedRectangle(cornerRadius: 6))
                .overlay(
                    RoundedRectangle(cornerRadius: 6)
                        .stroke(Color.black.opacity(0.08), lineWidth: 1)
                )
        }
    }

    // MARK: - Other Section

    private var otherSection: some View {
        detailFormSection(icon: "ellipsis.rectangle", title: "Other") {
            TextEditor(text: $agent.otherInstructions)
                .font(.system(size: 13))
                .frame(minHeight: 80)
                .padding(8)
                .scrollContentBackground(.hidden)
                .background(Color.white)
                .clipShape(RoundedRectangle(cornerRadius: 6))
                .overlay(
                    RoundedRectangle(cornerRadius: 6)
                        .stroke(Color.black.opacity(0.08), lineWidth: 1)
                )
        }
    }

    // MARK: - Footer Bar

    private var footerBar: some View {
        HStack(spacing: Spacing.sm) {
            Button(role: .destructive) {
                showDeleteConfirm = true
            } label: {
                Label("Delete", systemImage: "trash")
            }
            .buttonStyle(.bordered)
            .tint(Color.statusRed)

            Spacer()

            Button("Cancel") { dismiss() }
                .buttonStyle(.bordered)

            Button(isSaving ? "Saving…" : "Save") {
                isSaving = true
                // Sync personality frontmatter from the structured section (first line)
                let firstLine = agent.personalityAndTone.components(separatedBy: "\n").first ?? ""
                agent.personality = String(firstLine.prefix(200))
                Task {
                    try? await appState.saveAgent(agent)
                    isSaving = false
                    dismiss()
                }
            }
            .buttonStyle(.borderedProminent)
            .disabled(isSaving)
        }
        .padding(.horizontal, Spacing.xl)
        .padding(.vertical, Spacing.md)
    }

    // MARK: - Helpers

    @ViewBuilder
    private func detailFormSection<Content: View>(icon: String, title: String, @ViewBuilder content: () -> Content) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: icon)
                .font(.system(size: 17))
                .foregroundStyle(Color(white: 0.75))
                .frame(width: 22)

            VStack(alignment: .leading, spacing: 10) {
                Text(title)
                    .font(.system(size: 15, weight: .bold))
                    .tracking(-0.6)
                    .foregroundStyle(Color.primary.opacity(0.5))

                content()
            }
        }
        .padding(.leading, 20)
        .padding(.trailing, 32)
        .padding(.vertical, 16)
    }

    private func menuPicker<V: Hashable>(label: String, selection: Binding<V>, options: [(V, String)]) -> some View {
        Menu {
            ForEach(options, id: \.0) { value, text in
                Button {
                    selection.wrappedValue = value
                } label: {
                    HStack {
                        Text(text)
                        if selection.wrappedValue == value {
                            Image(systemName: "checkmark")
                        }
                    }
                }
            }
        } label: {
            HStack {
                Text(label)
                    .font(.system(size: 13))
                    .foregroundStyle(.primary)
                Spacer()
                Image(systemName: "chevron.up.chevron.down")
                    .font(.system(size: 10))
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 8)
            .frame(maxWidth: .infinity)
            .frame(height: 24)
            .background(Color.black.opacity(0.05))
            .clipShape(RoundedRectangle(cornerRadius: 6))
        }
        .buttonStyle(.plain)
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
        VStack(spacing: 0) {
            ScrollView {
                VStack(spacing: 0) {
                    // Identity
                    HStack(alignment: .top, spacing: 10) {
                        Text(agent.icon)
                            .font(.system(size: 40))
                            .frame(width: 44)

                        VStack(alignment: .leading, spacing: 4) {
                            HStack(spacing: Spacing.sm) {
                                Text(agent.name)
                                    .font(.system(size: 17, weight: .bold))
                                Image(systemName: "pin.fill")
                                    .font(.system(size: 10))
                                    .foregroundStyle(Color.statusBlue)
                            }
                            Text(agent.description)
                                .font(.system(size: 13))
                                .foregroundStyle(Color(white: 0.45))
                        }

                        Spacer()
                    }
                    .padding(.horizontal, 20)
                    .padding(.trailing, 12)
                    .padding(.vertical, 16)

                    Divider().padding(.horizontal, Spacing.xl)

                    // Instructions
                    HStack(alignment: .top, spacing: 10) {
                        Image(systemName: "text.alignleft")
                            .font(.system(size: 17))
                            .foregroundStyle(Color(white: 0.75))
                            .frame(width: 22)

                        VStack(alignment: .leading, spacing: 10) {
                            Text("Instructions")
                                .font(.system(size: 15, weight: .bold))
                                .tracking(-0.6)
                                .foregroundStyle(Color.primary.opacity(0.5))

                            Text("~/claude-bot/CLAUDE.md")
                                .font(.system(size: 10))
                                .foregroundStyle(Color(white: 0.45))

                            TextEditor(text: $agent.otherInstructions)
                                .font(.system(size: 13))
                                .frame(minHeight: 360)
                                .padding(8)
                                .scrollContentBackground(.hidden)
                                .background(Color.white)
                                .clipShape(RoundedRectangle(cornerRadius: 6))
                                .overlay(
                                    RoundedRectangle(cornerRadius: 6)
                                        .stroke(Color.black.opacity(0.08), lineWidth: 1)
                                )
                        }
                    }
                    .padding(.leading, 20)
                    .padding(.trailing, 32)
                    .padding(.vertical, 16)
                }
            }

            Divider()

            HStack(spacing: Spacing.sm) {
                Spacer()
                Button("Cancel") { dismiss() }
                    .buttonStyle(.bordered)
                Button(isSaving ? "Saving…" : "Save") {
                    isSaving = true
                    Task {
                        try? await appState.saveMainAgent(agent)
                        isSaving = false
                        dismiss()
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(isSaving)
            }
            .padding(.horizontal, Spacing.xl)
            .padding(.vertical, Spacing.md)
        }
        .frame(minWidth: 720, minHeight: 560)
        .background(Color(.windowBackgroundColor))
    }
}
