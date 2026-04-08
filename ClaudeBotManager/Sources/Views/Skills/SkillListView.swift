import SwiftUI

struct SkillListView: View {
    @EnvironmentObject var appState: AppState
    @State private var selectedSkill: Skill? = nil

    var body: some View {
        ScrollView {
            if appState.skills.isEmpty {
                EmptyStateView(
                    symbol: SidebarItem.skills.symbol,
                    title: "No Skills",
                    subtitle: "Skills are markdown files in vault/Skills/."
                )
            } else {
                LazyVGrid(
                    columns: [GridItem(.flexible(), spacing: Spacing.xl),
                              GridItem(.flexible(), spacing: Spacing.xl)],
                    spacing: Spacing.xl
                ) {
                    ForEach(appState.skills) { skill in
                        SkillCard(skill: skill)
                            .onTapGesture { selectedSkill = skill }
                    }
                }
                .padding(Spacing.xl)
            }
        }
        .background(Color(.windowBackgroundColor))
        .navigationTitle("Skills")
        .sheet(item: $selectedSkill) { skill in
            SkillDetailView(skill: skill)
        }
    }
}

struct SkillCard: View {
    var skill: Skill

    var body: some View {
        GlassCard(padding: Spacing.xl) {
            VStack(alignment: .leading, spacing: Spacing.md) {
                // Header: icon + title
                HStack {
                    Image(systemName: SidebarItem.skills.symbol)
                        .font(.system(size: 24))
                        .foregroundStyle(Color.statusBlue)
                    Spacer()
                    if !skill.tags.isEmpty {
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

                // Title + description
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
                }

                // Trigger
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
        }
        .contentShape(Rectangle())
    }
}
