import SwiftUI

struct SkillDetailView: View {
    @EnvironmentObject var appState: AppState
    @Environment(\.dismiss) var dismiss

    var skill: Skill
    @State private var showDeleteConfirm = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 16) {
                    identityCard
                    if !skill.trigger.isEmpty {
                        triggerCard
                    }
                    bodyCard
                }
                .padding(20)
            }
            .navigationTitle(skill.title)
            .navigationSubtitle(skill.id)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Close") { dismiss() }
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
            .confirmationDialog("Move Skill to Trash?", isPresented: $showDeleteConfirm, titleVisibility: .visible) {
                Button("Move to Trash", role: .destructive) {
                    Task {
                        try? await appState.deleteSkill(id: skill.id)
                        dismiss()
                    }
                }
            } message: {
                Text("The skill file will be moved to Trash. You can restore from Finder.")
            }
        }
        .frame(minWidth: 560, minHeight: 440)
    }

    private var identityCard: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Image(systemName: "wand.and.stars")
                        .font(.title2)
                        .foregroundStyle(.secondary)
                    VStack(alignment: .leading, spacing: 4) {
                        Text(skill.title)
                            .font(.title2.bold())
                        if !skill.description.isEmpty {
                            Text(skill.description)
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                        }
                    }
                    Spacer()
                }

                if !skill.tags.isEmpty {
                    HStack(spacing: 6) {
                        ForEach(skill.tags, id: \.self) { tag in
                            Text(tag)
                                .font(.caption2)
                                .padding(.horizontal, 7)
                                .padding(.vertical, 3)
                                .background(Color.primary.opacity(0.08))
                                .foregroundStyle(.secondary)
                                .clipShape(Capsule())
                        }
                    }
                }
            }
        }
    }

    private var triggerCard: some View {
        GlassCard {
            HStack(spacing: 8) {
                Image(systemName: "bolt.fill")
                    .font(.caption)
                    .foregroundStyle(Color.statusBlue)
                Text(skill.trigger)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
            }
        }
    }

    private var bodyCard: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 8) {
                Text("Instructions")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Text(skill.body)
                    .font(.system(.caption, design: .monospaced))
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(8)
                    .background(Color.primary.opacity(0.03))
                    .clipShape(RoundedRectangle(cornerRadius: 8))
            }
        }
    }
}
