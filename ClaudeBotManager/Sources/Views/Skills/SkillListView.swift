import SwiftUI

struct SkillListView: View {
    @EnvironmentObject var appState: AppState
    @State private var selectedSkill: Skill? = nil
    @State private var searchText = ""
    @State private var showCreateSheet = false
    @State private var agentFilter: String = "__all__"

    private var search: VaultSearch { VaultSearch(searchText) }

    private func filtered(_ skills: [Skill]) -> [Skill] {
        skills.filter { s in
            (agentFilter == "__all__" || s.ownerAgentId == agentFilter) && search.matches(s)
        }
    }

    private var botSkills: [Skill] { filtered(appState.skills.filter { $0.isBuiltIn }) }
    private var mySkills: [Skill] { filtered(appState.skills.filter { !$0.isBuiltIn }) }

    var body: some View {
        ScrollView {
            VStack(spacing: Spacing.xl) {
                AgentFilterBar(selection: $agentFilter)

                if appState.skills.isEmpty {
                    EmptyStateView(
                        symbol: SidebarItem.skills.symbol,
                        title: "No Skills",
                        subtitle: "Skills are markdown files under vault/<id>/Skills/ (one file per skill, per agent)."
                    )
                } else if botSkills.isEmpty && mySkills.isEmpty {
                    EmptyStateView(
                        symbol: "magnifyingglass",
                        title: "No Results",
                        subtitle: searchText.isEmpty
                            ? "No skills for this agent yet."
                            : "No skills match \"\(searchText)\"."
                    )
                } else {
                    if !botSkills.isEmpty {
                        skillSection(title: "Bot Skills", skills: botSkills)
                    }
                    if !mySkills.isEmpty {
                        skillSection(title: "My Skills", skills: mySkills)
                    }
                }
            }
            .padding(Spacing.xl)
        }
        .background(Color(.windowBackgroundColor))
        .navigationTitle("Skills")
        .searchable(
            text: $searchText,
            placement: .toolbar,
            prompt: "Filter (e.g. tag:publish trigger:notion)"
        )
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    showCreateSheet = true
                } label: {
                    Label("New Skill", systemImage: "plus")
                }
            }
        }
        .sheet(item: $selectedSkill) { skill in
            SkillDetailView(skill: skill)
        }
        .sheet(isPresented: $showCreateSheet) {
            SkillFormSheet(initialOwnerAgentId: agentFilter == "__all__" ? "main" : agentFilter)
        }
    }

    @ViewBuilder
    private func skillSection(title: String, skills: [Skill]) -> some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            Text(title)
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(.secondary)
                .textCase(.uppercase)
                .tracking(0.5)
                .padding(.horizontal, Spacing.xs)
            VStack(spacing: Spacing.lg) {
                ForEach(skills) { skill in
                    SkillRow(skill: skill)
                        .onTapGesture { selectedSkill = skill }
                }
            }
        }
    }
}

// MARK: - Skill Row

struct SkillRow: View {
    var skill: Skill

    var body: some View {
        GlassCard(padding: Spacing.xl) {
            HStack(spacing: Spacing.md) {
                Image(systemName: SidebarItem.skills.symbol)
                    .font(.system(size: 20))
                    .foregroundStyle(Color.statusBlue)
                    .frame(width: 28)

                VStack(alignment: .leading, spacing: Spacing.xs) {
                    Text(skill.title)
                        .font(.system(size: 15, weight: .bold))
                        .tracking(-0.6)
                        .lineLimit(1)

                    if !skill.description.isEmpty {
                        Text(skill.description)
                            .font(.system(size: 10))
                            .foregroundStyle(Color(red: 0.447, green: 0.447, blue: 0.447))
                            .lineLimit(2)
                    }

                    if !skill.trigger.isEmpty {
                        HStack(spacing: 4) {
                            Image(systemName: "bolt.fill")
                                .font(.system(size: 10))
                                .foregroundStyle(Color.statusBlue)
                            Text(skill.trigger)
                                .font(.system(size: 10))
                                .foregroundStyle(Color(red: 0.447, green: 0.447, blue: 0.447))
                                .lineLimit(1)
                        }
                    }
                }

                Spacer()

                if skill.isBuiltIn {
                    Image(systemName: "lock.fill")
                        .font(.system(size: 10))
                        .foregroundStyle(.tertiary)
                } else if !skill.tags.isEmpty {
                    HStack(spacing: 4) {
                        ForEach(skill.tags.prefix(2), id: \.self) { tag in
                            Text(tag)
                                .font(.system(size: 10))
                                .padding(.horizontal, 6)
                                .padding(.vertical, 2)
                                .background(Color.black.opacity(0.05))
                                .clipShape(Capsule())
                                .foregroundStyle(Color(red: 0.447, green: 0.447, blue: 0.447))
                        }
                    }
                }
            }
        }
        .contentShape(Rectangle())
    }
}

// MARK: - Skill Create Form

struct SkillFormSheet: View {
    @EnvironmentObject var appState: AppState
    @Environment(\.dismiss) var dismiss

    let initialOwnerAgentId: String

    init(initialOwnerAgentId: String = "main") {
        self.initialOwnerAgentId = initialOwnerAgentId
        _ownerAgentId = State(initialValue: initialOwnerAgentId)
    }

    @State private var title = ""
    @State private var skillId = ""
    @State private var description = ""
    @State private var trigger = ""
    @State private var instructions = ""
    @State private var ownerAgentId: String = "main"
    @State private var isSaving = false

    private var canCreate: Bool {
        !title.isEmpty && !instructions.isEmpty && !isSaving
    }

    /// Owner agent options for the picker.
    private var ownerAgentOptions: [(String, String)] {
        var opts: [(String, String)] = [("main", "\(appState.mainAgent.icon) \(appState.mainAgent.name)")]
        for a in appState.agents {
            opts.append((a.id, "\(a.icon) \(a.name)"))
        }
        return opts
    }

    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(spacing: 0) {
                    // Identity
                    VStack(alignment: .leading, spacing: Spacing.md) {
                        TextField("Skill Title", text: $title)
                            .font(.system(size: 17, weight: .bold))
                            .textFieldStyle(.plain)
                            .onChange(of: title) { _, v in
                                skillId = v.lowercased()
                                    .replacingOccurrences(of: " ", with: "-")
                                    .filter { $0.isLetter || $0.isNumber || $0 == "-" }
                            }
                        if !skillId.isEmpty {
                            Text("\(skillId).md")
                                .font(.system(size: 10, design: .monospaced))
                                .foregroundStyle(.tertiary)
                        }
                        TextField("Description", text: $description,
                                  prompt: Text("What does this skill do?"))
                            .font(.system(size: 13))
                            .foregroundStyle(.secondary)
                            .textFieldStyle(.plain)
                    }
                    .padding(.horizontal, Spacing.xl)
                    .padding(.vertical, Spacing.lg)

                    Divider().padding(.horizontal, Spacing.xl)

                    // Owner agent
                    VStack(alignment: .leading, spacing: Spacing.xs) {
                        Text("Owner Agent")
                            .font(.system(size: 10)).foregroundStyle(.secondary)
                        Picker("", selection: $ownerAgentId) {
                            ForEach(ownerAgentOptions, id: \.0) { id, label in
                                Text(label).tag(id)
                            }
                        }
                        .labelsHidden()
                        Text("Lives under vault/\(ownerAgentId)/Skills/")
                            .font(.system(size: 10))
                            .foregroundStyle(.tertiary)
                    }
                    .padding(.horizontal, Spacing.xl)
                    .padding(.vertical, Spacing.lg)

                    Divider().padding(.horizontal, Spacing.xl)

                    // Trigger
                    VStack(alignment: .leading, spacing: Spacing.xs) {
                        Text("Trigger")
                            .font(.system(size: 10)).foregroundStyle(.secondary)
                        TextField("When should this skill activate?", text: $trigger)
                            .font(.system(size: 13))
                            .textFieldStyle(.roundedBorder)
                    }
                    .padding(.horizontal, Spacing.xl)
                    .padding(.vertical, Spacing.lg)

                    Divider().padding(.horizontal, Spacing.xl)

                    // Instructions body
                    VStack(alignment: .leading, spacing: Spacing.xs) {
                        Text("Instructions")
                            .font(.system(size: 10)).foregroundStyle(.secondary)
                        TextEditor(text: $instructions)
                            .font(.system(.callout, design: .default))
                            .frame(minHeight: 200)
                            .scrollContentBackground(.hidden)
                            .padding(Spacing.sm)
                            .background(Color.primary.opacity(0.03))
                            .clipShape(RoundedRectangle(cornerRadius: 8))
                            .overlay(
                                RoundedRectangle(cornerRadius: 8)
                                    .strokeBorder(Color.accentColor.opacity(0.35), lineWidth: 1)
                            )
                    }
                    .padding(.horizontal, Spacing.xl)
                    .padding(.vertical, Spacing.lg)
                }
            }

            Divider()

            // Footer
            HStack {
                Spacer()
                Button("Cancel") { dismiss() }
                    .buttonStyle(.bordered)
                Button("Create") {
                    isSaving = true
                    let todayStr = {
                        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"
                        return f.string(from: Date())
                    }()
                    var skill = Skill(
                        id: skillId, title: title, description: description,
                        trigger: trigger, tags: ["skill"],
                        created: todayStr, updated: todayStr, body: instructions
                    )
                    skill.ownerAgentId = ownerAgentId.isEmpty ? "main" : ownerAgentId
                    Task {
                        try? await appState.saveSkill(skill)
                        isSaving = false
                        dismiss()
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(!canCreate)
            }
            .padding(.horizontal, Spacing.xl)
            .padding(.vertical, Spacing.md)
        }
        .frame(minWidth: 500, minHeight: 480)
        .background(Color(.windowBackgroundColor))
    }
}
