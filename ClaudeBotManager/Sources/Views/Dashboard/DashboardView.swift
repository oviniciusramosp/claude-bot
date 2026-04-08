import SwiftUI

struct DashboardView: View {
    @EnvironmentObject var appState: AppState
    @State private var showRestartConfirm = false

    var body: some View {
        ScrollView {
            LazyVGrid(columns: [GridItem(.flexible(), spacing: 16), GridItem(.flexible(), spacing: 16)], spacing: 16) {
                // Bot Status Card
                BotStatusCard()

                // Claude Usage Card
                ClaudeUsageCard()

                // Today's Routines Card
                TodayRoutinesCard()

                // Active Sessions Card
                SessionsSummaryCard()
            }
            .padding(20)
        }
        .background(Color(.windowBackgroundColor))
        .navigationTitle("Dashboard")
    }
}

// MARK: - Bot Status Card

struct BotStatusCard: View {
    @EnvironmentObject var appState: AppState
    @State private var isRestarting = false

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    SectionHeader(title: "Bot Status", symbol: "cpu")
                    Spacer()
                    StatusDot(isRunning: appState.isRunning, size: 10)
                }

                Text(appState.botStatusLabel)
                    .font(.title3.bold())
                    .foregroundStyle(appState.isRunning ? .primary : .secondary)

                if case .running(let pid, _) = appState.botStatus {
                    Text("PID \(pid)")
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.tertiary)
                }

                Divider()

                HStack(spacing: 8) {
                    if appState.isRunning {
                        Button(role: .destructive) {
                            Task { await appState.stopBot() }
                        } label: {
                            Label("Stop", systemImage: "stop.fill")
                                .font(.caption)
                        }
                        .buttonStyle(.bordered)
                    } else {
                        Button {
                            Task { await appState.startBot() }
                        } label: {
                            Label("Start", systemImage: "play.fill")
                                .font(.caption)
                        }
                        .buttonStyle(.borderedProminent)
                    }

                    Button {
                        isRestarting = true
                        Task {
                            await appState.restartBot()
                            isRestarting = false
                        }
                    } label: {
                        if isRestarting {
                            Label("Restarting…", systemImage: "arrow.trianglehead.2.clockwise")
                                .font(.caption)
                        } else {
                            Label("Restart", systemImage: "arrow.trianglehead.2.clockwise")
                                .font(.caption)
                        }
                    }
                    .buttonStyle(.bordered)
                    .disabled(isRestarting)
                }
            }
        }
    }
}

// MARK: - Claude Usage Card

struct ClaudeUsageCard: View {
    @EnvironmentObject var appState: AppState

    var usage: ClaudeUsage { appState.claudeUsage }

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 12) {
                SectionHeader(title: "Claude Usage", symbol: "bolt.circle")

                if usage.isAvailable {
                    VStack(spacing: 10) {
                        UsageBar(
                            percent: usage.sessionPercent,
                            label: "5-Hour Session",
                            sublabel: usage.sessionLabel
                        )
                        UsageBar(
                            percent: usage.weeklyPercent,
                            label: "7-Day Week",
                            sublabel: usage.weeklyLabel
                        )
                    }

                    if let reset = usage.weeklyResetsAt {
                        Divider()
                        HStack {
                            Image(systemName: "clock")
                                .font(.caption2)
                                .foregroundStyle(.tertiary)
                            Text("Week resets \(reset, style: .relative)")
                                .font(.caption)
                                .foregroundStyle(.tertiary)
                        }
                    }
                } else {
                    VStack(spacing: 8) {
                        Image(systemName: "bolt.slash")
                            .font(.title2)
                            .foregroundStyle(.tertiary)
                        Text("Usage data unavailable")
                            .font(.caption)
                            .foregroundStyle(.tertiary)
                        Text("Requires Claude Code credentials")
                            .font(.caption2)
                            .foregroundStyle(.quaternary)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 8)
                }
            }
        }
    }
}

// MARK: - Today's Routines Card

struct TodayRoutinesCard: View {
    @EnvironmentObject var appState: AppState

    private var todayExecutions: [RoutineExecution] {
        appState.routines.flatMap { $0.todayExecutions }
    }

    private var completed: Int { todayExecutions.filter { $0.status == .completed }.count }
    private var failed: Int { todayExecutions.filter { $0.status == .failed }.count }
    private var running: Int { todayExecutions.filter { $0.status == .running }.count }
    private var pending: Int { todayExecutions.filter { $0.status == .pending }.count }

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 12) {
                SectionHeader(title: "Today's Routines", symbol: "clock.arrow.2.circlepath")

                if todayExecutions.isEmpty {
                    HStack {
                        Image(systemName: "moon.zzz")
                            .foregroundStyle(.tertiary)
                        Text("No executions today")
                            .font(.caption)
                            .foregroundStyle(.tertiary)
                    }
                    .frame(maxWidth: .infinity, alignment: .center)
                    .padding(.vertical, 8)
                } else {
                    HStack(spacing: 16) {
                        StatPill(value: completed, label: "Done", color: .statusGreen)
                        StatPill(value: failed, label: "Failed", color: .statusRed)
                        if running > 0 {
                            StatPill(value: running, label: "Running", color: .statusBlue)
                        }
                    }

                    Divider()

                    VStack(alignment: .leading, spacing: 6) {
                        ForEach(appState.routines.prefix(4)) { routine in
                            if let last = routine.lastExecution {
                                RoutineStatusRow(name: routine.title, execution: last)
                            }
                        }
                    }
                }
            }
        }
    }
}

struct StatPill: View {
    var value: Int
    var label: String
    var color: Color

    var body: some View {
        VStack(spacing: 2) {
            Text("\(value)")
                .font(.title3.bold())
                .foregroundStyle(color)
            Text(label)
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
    }
}

struct RoutineStatusRow: View {
    var name: String
    var execution: RoutineExecution

    private var statusColor: Color {
        switch execution.status {
        case .completed: .statusGreen
        case .failed: .statusRed
        case .running: .statusBlue
        case .pending, .skipped: .secondary
        }
    }

    var body: some View {
        HStack {
            Image(systemName: execution.status.symbol)
                .foregroundStyle(statusColor)
                .font(.caption)
            Text(name)
                .font(.caption)
                .lineLimit(1)
            Spacer()
            Text(execution.timeSlot)
                .font(.caption.monospacedDigit())
                .foregroundStyle(.tertiary)
        }
    }
}

// MARK: - Sessions Summary Card

struct SessionsSummaryCard: View {
    @EnvironmentObject var appState: AppState

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 12) {
                SectionHeader(title: "Sessions", symbol: "list.bullet.rectangle")

                HStack(spacing: 16) {
                    StatPill(value: appState.sessions.sessions.count, label: "Total", color: .statusBlue)
                    if let active = appState.sessions.active {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Active")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                            Text(active.name)
                                .font(.caption.bold())
                                .lineLimit(1)
                        }
                    }
                }

                if let active = appState.sessions.active {
                    Divider()
                    VStack(alignment: .leading, spacing: 4) {
                        HStack {
                            Text("Model")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            Spacer()
                            ModelBadge(model: active.model)
                        }
                        if let agentId = active.agentId {
                            HStack {
                                Text("Agent")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                Spacer()
                                Text(appState.agents.first { $0.id == agentId }?.name ?? agentId)
                                    .font(.caption)
                                    .lineLimit(1)
                            }
                        }
                        HStack {
                            Text("Messages")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            Spacer()
                            Text("\(active.messageCount)")
                                .font(.caption.monospacedDigit())
                        }
                    }
                }
            }
        }
    }
}
