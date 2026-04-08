import SwiftUI

struct SessionBrowserView: View {
    @EnvironmentObject var appState: AppState
    @State private var sortOrder = [KeyPathComparator(\SessionData.createdAt, order: .reverse)]

    private var sessions: [SessionData] {
        Array(appState.sessions.sessions.values)
    }

    var body: some View {
        Group {
            if sessions.isEmpty {
                EmptyStateView(
                    symbol: "list.bullet.rectangle",
                    title: "No Sessions",
                    subtitle: "Sessions are created when you start a conversation in Telegram."
                )
            } else {
                Table(sessions, sortOrder: $sortOrder) {
                    TableColumn("Name") { s in
                        HStack {
                            if s.isActive {
                                Circle().fill(Color.statusGreen).frame(width: 6, height: 6)
                            }
                            Text(s.name)
                                .font(s.isActive ? .body.bold() : .body)
                        }
                    }
                    .width(min: 120)

                    TableColumn("Model") { s in
                        ModelBadge(model: s.model)
                    }
                    .width(80)

                    TableColumn("Agent") { s in
                        if let agentId = s.agentId,
                           let agent = appState.agents.first(where: { $0.id == agentId }) {
                            Label("\(agent.icon) \(agent.name)", systemImage: "")
                                .font(.caption)
                        } else {
                            Text("—").foregroundStyle(.tertiary)
                        }
                    }
                    .width(min: 100)

                    TableColumn("Messages", value: \.messageCount) { s in
                        Text("\(s.messageCount)")
                            .font(.caption.monospacedDigit())
                            .foregroundStyle(.secondary)
                    }
                    .width(80)

                    TableColumn("Turns", value: \.totalTurns) { s in
                        Text("\(s.totalTurns)")
                            .font(.caption.monospacedDigit())
                            .foregroundStyle(.secondary)
                    }
                    .width(60)

                    TableColumn("Created", value: \.createdAt) { s in
                        Text(s.createdAt, format: .dateTime.month(.abbreviated).day().hour().minute())
                            .font(.caption.monospacedDigit())
                            .foregroundStyle(.secondary)
                    }
                    .width(min: 140)
                }
                .tableStyle(.inset)
            }
        }
        .navigationTitle("Sessions")
        .toolbar {
            ToolbarItem {
                Text("Total turns: \(appState.sessions.cumulativeTurns)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            ToolbarItem {
                Button {
                    Task { await appState.loadSessions() }
                } label: {
                    Label("Refresh", systemImage: "arrow.clockwise")
                }
            }
        }
    }
}
