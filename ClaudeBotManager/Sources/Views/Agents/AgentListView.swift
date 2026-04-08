import SwiftUI

struct AgentListView: View {
    @EnvironmentObject var appState: AppState
    @State private var showCreateSheet = false
    @State private var selectedAgent: Agent? = nil
    @State private var showMainDetail = false

    private let columns = [
        GridItem(.adaptive(minimum: 200, maximum: 280), spacing: 16)
    ]

    var body: some View {
        ScrollView {
            LazyVGrid(columns: columns, spacing: 16) {
                MainAgentCard(agent: appState.mainAgent)
                    .onTapGesture { showMainDetail = true }
                ForEach(appState.agents) { agent in
                    AgentCard(agent: agent)
                        .onTapGesture { selectedAgent = agent }
                }
            }
            .padding(20)
        }
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

struct MainAgentCard: View {
    var agent: Agent

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Text(agent.icon)
                        .font(.system(size: 36))
                    Spacer()
                    Image(systemName: "pin.fill")
                        .font(.caption)
                        .foregroundStyle(Color.statusBlue)
                }
                VStack(alignment: .leading, spacing: 3) {
                    Text(agent.name)
                        .font(.headline)
                        .lineLimit(1)
                    Text(agent.description)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
                HStack {
                    Image(systemName: "doc.text")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    Text("CLAUDE.md")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
            }
        }
        .contentShape(Rectangle())
    }
}

struct AgentCard: View {
    var agent: Agent
    @EnvironmentObject var appState: AppState

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Text(agent.icon)
                        .font(.system(size: 36))
                    Spacer()
                    if agent.isDefault {
                        Image(systemName: "star.fill")
                            .font(.caption)
                            .foregroundStyle(Color.statusYellow)
                    }
                    ModelBadge(model: agent.model)
                }

                VStack(alignment: .leading, spacing: 3) {
                    Text(agent.name)
                        .font(.headline)
                        .lineLimit(1)
                    Text(agent.description)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }

                if !agent.topicMappings.isEmpty {
                    HStack {
                        Image(systemName: "paperplane.fill")
                            .font(.caption2)
                            .foregroundStyle(Color.statusBlue)
                        Text("\(agent.topicMappings.count) topic\(agent.topicMappings.count == 1 ? "" : "s")")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
        .contentShape(Rectangle())
    }
}
