import SwiftUI

struct AgentListView: View {
    @EnvironmentObject var appState: AppState
    @State private var showCreateSheet = false
    @State private var selectedAgent: Agent? = nil
    @State private var showMainDetail = false

    var body: some View {
        ScrollView {
            VStack(spacing: Spacing.xl) {
                // Main agent — full width, prominent
                MainAgentCard(agent: appState.mainAgent)
                    .onTapGesture { showMainDetail = true }

                // Other agents — 2-column grid
                if !appState.agents.isEmpty {
                    LazyVGrid(
                        columns: [GridItem(.flexible(), spacing: Spacing.xl),
                                  GridItem(.flexible(), spacing: Spacing.xl)],
                        spacing: Spacing.xl
                    ) {
                        ForEach(appState.agents) { agent in
                            AgentCard(agent: agent)
                                .onTapGesture { selectedAgent = agent }
                        }
                    }
                }
            }
            .padding(Spacing.xl)
        }
        .background(Color(.windowBackgroundColor))
        .navigationTitle("Agents")
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    showCreateSheet = true
                } label: {
                    Label("New Agent", systemImage: "plus")
                }
            }
        }
        .sheet(isPresented: $showMainDetail) {
            MainAgentDetailView(agent: appState.mainAgent)
        }
        .sheet(item: $selectedAgent) { agent in
            AgentDetailView(agent: agent)
        }
        .sheet(isPresented: $showCreateSheet) {
            AgentFormSheet()
        }
    }
}

// MARK: - Main Agent Card (full width, prominent)

struct MainAgentCard: View {
    var agent: Agent

    var body: some View {
        GlassCard(padding: Spacing.xl) {
            HStack(spacing: Spacing.xl) {
                // Large emoji
                Text(agent.icon)
                    .font(.system(size: 48))

                VStack(alignment: .leading, spacing: Spacing.xs) {
                    HStack(spacing: Spacing.sm) {
                        Text(agent.name)
                            .font(.system(size: 17, weight: .bold))
                            .tracking(-0.51)
                        Image(systemName: "pin.fill")
                            .font(.system(size: 10))
                            .foregroundStyle(Color.statusBlue)
                    }
                    Text(agent.description)
                        .font(.system(size: 10))
                        .foregroundStyle(Color(red: 0.447, green: 0.447, blue: 0.447))
                        .lineLimit(2)
                    HStack(spacing: 4) {
                        Image(systemName: "doc.text")
                            .font(.system(size: 10))
                        Text("CLAUDE.md")
                            .font(.system(size: 10))
                    }
                    .foregroundStyle(.tertiary)
                }

                Spacer(minLength: 0)
            }
        }
        .contentShape(Rectangle())
    }
}

// MARK: - Agent Card (grid item)

struct AgentCard: View {
    var agent: Agent
    @EnvironmentObject var appState: AppState

    var body: some View {
        GlassCard(padding: Spacing.xl) {
            VStack(alignment: .leading, spacing: Spacing.md) {
                HStack {
                    Text(agent.icon)
                        .font(.system(size: 36))
                    Spacer()
                    if agent.isDefault {
                        Image(systemName: "star.fill")
                            .font(.system(size: 10))
                            .foregroundStyle(Color.statusYellow)
                    }
                    ModelBadge(model: agent.model)
                }

                VStack(alignment: .leading, spacing: Spacing.xs) {
                    Text(agent.name)
                        .font(.system(size: 15, weight: .bold))
                        .tracking(-0.6)
                        .lineLimit(1)
                    Text(agent.description)
                        .font(.system(size: 10))
                        .foregroundStyle(Color(red: 0.447, green: 0.447, blue: 0.447))
                        .lineLimit(2)
                }

                if !agent.topicMappings.isEmpty {
                    HStack(spacing: 4) {
                        Image(systemName: "paperplane.fill")
                            .font(.system(size: 10))
                            .foregroundStyle(Color.statusBlue)
                        Text("\(agent.topicMappings.count) topic\(agent.topicMappings.count == 1 ? "" : "s")")
                            .font(.system(size: 10))
                            .foregroundStyle(Color(red: 0.447, green: 0.447, blue: 0.447))
                    }
                }
            }
        }
        .contentShape(Rectangle())
    }
}
