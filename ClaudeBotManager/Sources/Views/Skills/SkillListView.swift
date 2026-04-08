import SwiftUI

struct SkillListView: View {
    @EnvironmentObject var appState: AppState
    @State private var selectedSkill: Skill? = nil

    var body: some View {
        Group {
            if appState.skills.isEmpty {
                EmptyStateView(
                    symbol: "wand.and.stars",
                    title: "No Skills",
                    subtitle: "Skills are markdown files in vault/Skills/."
                )
            } else {
                List(appState.skills) { skill in
                    SkillRow(skill: skill)
                        .onTapGesture { selectedSkill = skill }
                        .listRowBackground(Color.clear)
                        .listRowSeparator(.hidden)
                        .padding(.vertical, 2)
                }
                .listStyle(.plain)
                .scrollContentBackground(.hidden)
            }
        }
        .navigationTitle("Skills")
        .sheet(item: $selectedSkill) { skill in
            SkillDetailView(skill: skill)
        }
    }
}

struct SkillRow: View {
    var skill: Skill

    var body: some View {
        GlassCard(padding: 12) {
            HStack(spacing: 12) {
                Image(systemName: "wand.and.stars")
                    .font(.system(size: 18))
                    .foregroundStyle(.secondary)
                    .frame(width: 24)

                VStack(alignment: .leading, spacing: 3) {
                    Text(skill.title)
                        .font(.callout.bold())
                        .lineLimit(1)

                    if !skill.description.isEmpty {
                        Text(skill.description)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                    }

                    if !skill.trigger.isEmpty {
                        Label(skill.trigger, systemImage: "bolt.fill")
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                            .lineLimit(1)
                    }
                }

                Spacer()

                if !skill.tags.isEmpty {
                    HStack(spacing: 4) {
                        ForEach(skill.tags.prefix(3), id: \.self) { tag in
                            Text(tag)
                                .font(.caption2)
                                .padding(.horizontal, 6)
                                .padding(.vertical, 2)
                                .background(Color.primary.opacity(0.06))
                                .clipShape(Capsule())
                                .foregroundStyle(.secondary)
                        }
                    }
                }
            }
        }
        .contentShape(Rectangle())
    }
}
