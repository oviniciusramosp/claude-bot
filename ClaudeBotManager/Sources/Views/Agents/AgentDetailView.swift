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
                    Text("vault/\(agent.id)/")
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

            // v3.5: Main is the single mandatory default. For Main, show a
            // static "Default" pin; for custom agents, no toggle — the user
            // never picks a different default.
            if agent.id == "main" {
                HStack(spacing: 4) {
                    Image(systemName: "pin.fill")
                        .font(.system(size: 10))
                        .foregroundStyle(Color.statusBlue)
                    Text("Default")
                        .font(.system(size: 10, weight: .medium))
                        .foregroundStyle(Color.statusBlue)
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                .background(Color.statusBlue.opacity(0.10))
                .clipShape(Capsule())
            }
        }
        .padding(.horizontal, 20)
        .padding(.trailing, 12)
        .padding(.vertical, 16)
    }

    // MARK: - Color swatch helper

    private func colorHex(_ name: String) -> Color {
        switch name.lowercased() {
        case "grey":   return Color(red: 0.62, green: 0.62, blue: 0.62)
        case "red":    return Color(red: 0.96, green: 0.26, blue: 0.21)
        case "orange": return Color(red: 1.00, green: 0.60, blue: 0.00)
        case "yellow": return Color(red: 1.00, green: 0.92, blue: 0.23)
        case "green":  return Color(red: 0.30, green: 0.69, blue: 0.31)
        case "teal":   return Color(red: 0.00, green: 0.74, blue: 0.83)
        case "blue":   return Color(red: 0.13, green: 0.59, blue: 0.95)
        case "purple": return Color(red: 0.61, green: 0.15, blue: 0.69)
        default:       return Color(red: 0.62, green: 0.62, blue: 0.62)
        }
    }

    // MARK: - Config Section (Model + Telegram)

    private func modelDisplayName(_ id: String) -> String {
        ModelCatalog.label(for: id)
    }

    private func modelDescription(_ id: String) -> String {
        ModelCatalog.description(for: id)
    }

    private var configSection: some View {
        detailFormSection(icon: "gear", title: "Configuration") {
            VStack(alignment: .leading, spacing: 16) {
                HStack(alignment: .top, spacing: 40) {
                    // Model
                    VStack(alignment: .leading, spacing: 5) {
                        Text("Model").font(.system(size: 10)).foregroundStyle(Color(white: 0.45))
                        menuPicker(label: modelDisplayName(agent.model), selection: $agent.model, options: ModelCatalog.pickerOptions)
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

                // Obsidian graph color — drives the per-agent color group in
                // .obsidian/graph.json, synced automatically by the bot on
                // startup and whenever an agent is saved.
                VStack(alignment: .leading, spacing: 6) {
                    Text("Obsidian Graph Color").font(.system(size: 10)).foregroundStyle(Color(white: 0.45))
                    HStack(spacing: 8) {
                        ForEach(Agent.colorOptions, id: \.self) { colorName in
                            Button {
                                agent.color = colorName
                            } label: {
                                Circle()
                                    .fill(colorHex(colorName))
                                    .frame(width: 22, height: 22)
                                    .overlay(
                                        Circle()
                                            .stroke(Color.primary.opacity(agent.color == colorName ? 0.7 : 0.15),
                                                    lineWidth: agent.color == colorName ? 2 : 1)
                                    )
                                    .overlay(
                                        Image(systemName: "checkmark")
                                            .font(.system(size: 10, weight: .bold))
                                            .foregroundStyle(.white)
                                            .opacity(agent.color == colorName ? 1 : 0)
                                    )
                            }
                            .buttonStyle(.plain)
                            .help(colorName.capitalized)
                        }
                    }
                    Text("Used in the Obsidian graph view to group this agent's files.")
                        .font(.system(size: 10))
                        .foregroundStyle(Color(white: 0.45))
                }
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
            // Main is the mandatory default agent in v3.5 and cannot be deleted.
            if agent.id != "main" {
                Button(role: .destructive) {
                    showDeleteConfirm = true
                } label: {
                    Label("Delete", systemImage: "trash")
                }
                .buttonStyle(.bordered)
                .tint(Color.statusRed)
            }

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

// v3.5 note: the former `MainAgentDetailView` (which edited the project-root
// CLAUDE.md as if it were Main's personality) was removed — Main is now a
// first-class agent loaded via `loadAgents()` and edited via the normal
// `AgentDetailView` like every other agent. Its personality/instructions
// live at `vault/main/CLAUDE.md`, metadata at `vault/main/agent-main.md`.
