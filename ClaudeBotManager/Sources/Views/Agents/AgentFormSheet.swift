import SwiftUI
import Foundation

struct AgentFormSheet: View {
    @EnvironmentObject var appState: AppState
    @Environment(\.dismiss) var dismiss

    @State private var name = ""
    @State private var icon = "🤖"
    @State private var description = ""
    @State private var personality = ""
    @State private var model = "sonnet"
    @State private var instructions = ""
    @State private var isSaving = false
    @State private var idPreview = ""
    @State private var idError = ""

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 16) {
                    GlassCard {
                        VStack(spacing: 14) {
                            HStack {
                                Text(icon.isEmpty ? "🤖" : icon)
                                    .font(.system(size: 50))
                                VStack(alignment: .leading, spacing: 8) {
                                    TextField("Agent Name", text: $name)
                                        .font(.title2.bold())
                                        .textFieldStyle(.roundedBorder)
                                        .onChange(of: name) { _, v in
                                            idPreview = toKebabCase(v)
                                            idError = validateAgentId(idPreview)
                                        }
                                    if !idPreview.isEmpty {
                                        Text("ID: \(idPreview)")
                                            .font(.caption.monospacedDigit())
                                            .foregroundStyle(idError.isEmpty ? AnyShapeStyle(.tertiary) : AnyShapeStyle(.red))
                                    }
                                    if !idError.isEmpty {
                                        Text(idError)
                                            .font(.caption2)
                                            .foregroundStyle(.red)
                                    }
                                }
                                .padding(.leading, 8)
                            }

                            HStack {
                                Text("Icon")
                                    .font(.caption).foregroundStyle(.secondary)
                                Spacer()
                                TextField("Emoji", text: $icon)
                                    .frame(width: 80)
                                    .textFieldStyle(.roundedBorder)
                                    .multilineTextAlignment(.center)
                            }

                            TextField("Description", text: $description, prompt: Text("What does this agent do?"))
                                .textFieldStyle(.roundedBorder)
                            TextField("Personality", text: $personality, prompt: Text("Brief personality description"))
                                .textFieldStyle(.roundedBorder)

                            HStack {
                                Text("Model")
                                    .font(.caption).foregroundStyle(.secondary)
                                Spacer()
                                Picker("", selection: $model) {
                                    ForEach(Agent.modelOptions, id: \.self) { m in
                                        Text(m.capitalized).tag(m)
                                    }
                                }
                                .pickerStyle(.segmented)
                                .frame(width: 200)
                            }
                        }
                    }

                    GlassCard {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Instructions (CLAUDE.md)")
                                .font(.caption).foregroundStyle(.secondary)
                            Text("These instructions define the agent's behavior. No frontmatter needed.")
                                .font(.caption2).foregroundStyle(.tertiary)

                            TextEditor(text: $instructions)
                                .font(.system(.caption, design: .monospaced))
                                .frame(minHeight: 180)
                                .scrollContentBackground(.hidden)
                                .background(Color.primary.opacity(0.03))
                                .clipShape(RoundedRectangle(cornerRadius: 8))
                                .overlay(
                                    Group {
                                        if instructions.isEmpty {
                                            Text("# Agent Name 🤖\n\n## Personalidade\nDescrição do tom e estilo\n\n## Instruções\n- Registrar conversas no Journal próprio...")
                                                .font(.system(.caption, design: .monospaced))
                                                .foregroundStyle(.quaternary)
                                                .padding(8)
                                                .allowsHitTesting(false)
                                                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                                        }
                                    }
                                )
                        }
                    }
                }
                .padding(20)
            }
            .navigationTitle("New Agent")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Create") {
                        isSaving = true
                        let today = {
                            let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"
                            return f.string(from: Date())
                        }()
                        // Parse raw CLAUDE.md into structured sections
                        let sections = Agent.parseCLAUDEmd(instructions)
                        let agent = Agent(
                            id: idPreview.isEmpty ? toKebabCase(name) : idPreview,
                            name: name,
                            icon: icon.isEmpty ? "🤖" : icon,
                            description: description,
                            personality: personality,
                            model: model,
                            tags: ["agent"],
                            isDefault: false,
                            source: nil,
                            sourceId: nil,
                            created: today,
                            updated: today,
                            personalityAndTone: sections.personality.isEmpty ? personality : sections.personality,
                            instructions: sections.instructions,
                            specializations: sections.specializations,
                            otherInstructions: sections.other
                        )
                        Task {
                            try? await appState.saveAgent(agent)
                            isSaving = false
                            dismiss()
                        }
                    }
                    .disabled(name.isEmpty || isSaving || !idError.isEmpty)
                }
            }
        }
        .frame(minWidth: 560, minHeight: 480)
    }

    private func toKebabCase(_ s: String) -> String {
        s.lowercased()
            .replacingOccurrences(of: " ", with: "-")
            .filter { $0.isLetter || $0.isNumber || $0 == "-" }
    }

    private func validateAgentId(_ id: String) -> String {
        guard !id.isEmpty else { return "" }
        let pattern = "^[a-z0-9]([a-z0-9-]*[a-z0-9])?$"
        if id.range(of: pattern, options: .regularExpression) == nil {
            return "ID must be kebab-case (lowercase letters, numbers, hyphens; cannot start or end with hyphen)"
        }
        return ""
    }
}
