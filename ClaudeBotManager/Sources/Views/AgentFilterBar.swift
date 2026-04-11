import SwiftUI

/// Horizontal filter bar used above Routines/Skills/Reactions lists.
/// Lets the user scope the list to a single owning agent (or show all).
/// The "main" agent is always present; custom agents come from `appState.agents`.
struct AgentFilterBar: View {
    @EnvironmentObject var appState: AppState
    /// Stored selection. `"__all__"` means show everything; otherwise a valid agent id.
    @Binding var selection: String

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: Spacing.sm) {
                chip(id: "__all__", icon: "square.grid.2x2", label: "All")
                chip(id: "main", icon: appState.mainAgent.icon, label: appState.mainAgent.name)
                ForEach(appState.agents) { agent in
                    chip(id: agent.id, icon: agent.icon, label: agent.name)
                }
            }
            .padding(.horizontal, Spacing.xs)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder
    private func chip(id: String, icon: String, label: String) -> some View {
        let isSelected = selection == id
        Button {
            selection = id
        } label: {
            HStack(spacing: 4) {
                if icon.count == 1 || icon.unicodeScalars.first?.properties.isEmoji == true {
                    Text(icon)
                        .font(.system(size: 12))
                } else {
                    Image(systemName: icon)
                        .font(.system(size: 11))
                }
                Text(label)
                    .font(.system(size: 12, weight: .medium))
            }
            .padding(.horizontal, 10)
            .frame(height: 24)
            .background(isSelected ? Color.accentColor : Color.black.opacity(0.05))
            .foregroundStyle(isSelected ? Color.white : Color.primary)
            .clipShape(Capsule())
        }
        .buttonStyle(.plain)
    }
}
