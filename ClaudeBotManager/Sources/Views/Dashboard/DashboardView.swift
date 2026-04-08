import SwiftUI

struct DashboardView: View {
    @EnvironmentObject var appState: AppState
    @State private var showRestartConfirm = false

    var body: some View {
        ScrollView {
            LazyVGrid(columns: [GridItem(.flexible(), spacing: Spacing.lg), GridItem(.flexible(), spacing: Spacing.lg)], spacing: Spacing.lg) {
                BotStatusCard()
                ClaudeUsageCard()
                TodayRoutinesCard()
                SessionsSummaryCard()
            }
            .padding(Spacing.xl)
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
            VStack(alignment: .leading, spacing: Spacing.lg) {
                HStack {
                    SectionHeader(title: "Bot Status", symbol: "cpu")
                    Spacer()
                    StatusDot(isRunning: appState.isRunning, size: 10)
                }

                VStack(alignment: .leading, spacing: Spacing.xs) {
                    Text(appState.botStatusLabel)
                        .font(.title2.bold())
                        .foregroundStyle(appState.isRunning ? .primary : .secondary)

                    if case .running(let pid, _) = appState.botStatus {
                        Text("PID \(pid)")
                            .font(.caption.monospacedDigit())
                            .foregroundStyle(.tertiary)
                    }
                }

                HStack(spacing: Spacing.sm) {
                    if appState.isRunning {
                        Button(role: .destructive) {
                            Task { await appState.stopBot() }
                        } label: {
                            Label("Stop", systemImage: "stop.fill")
                                .font(.callout)
                        }
                        .buttonStyle(.bordered)
                    } else {
                        Button {
                            Task { await appState.startBot() }
                        } label: {
                            Label("Start", systemImage: "play.fill")
                                .font(.callout)
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
                                .font(.callout)
                        } else {
                            Label("Restart", systemImage: "arrow.trianglehead.2.clockwise")
                                .font(.callout)
                        }
                    }
                    .buttonStyle(.bordered)
                    .disabled(isRestarting)
                }
            }
        }
        .frame(minHeight: 180)
    }
}

// MARK: - Claude Usage Card

struct ClaudeUsageCard: View {
    @EnvironmentObject var appState: AppState

    var usage: ClaudeUsage { appState.claudeUsage }

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Spacing.lg) {
                SectionHeader(title: "Claude Usage", symbol: "bolt.circle")

                if usage.isAvailable {
                    VStack(spacing: Spacing.md) {
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
                        HStack {
                            Image(systemName: "clock")
                                .font(.caption)
                                .foregroundStyle(.tertiary)
                            Text("Week resets \(reset, style: .relative)")
                                .font(.caption)
                                .foregroundStyle(.tertiary)
                        }
                    }
                } else {
                    VStack(spacing: Spacing.sm) {
                        Image(systemName: "bolt.slash")
                            .font(.title2)
                            .foregroundStyle(.tertiary)
                        Text("Usage data unavailable")
                            .font(.callout)
                            .foregroundStyle(.tertiary)
                        Text("Requires Claude Code credentials")
                            .font(.caption)
                            .foregroundStyle(.quaternary)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, Spacing.sm)
                }
            }
        }
        .frame(minHeight: 180)
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
            VStack(alignment: .leading, spacing: Spacing.lg) {
                SectionHeader(title: "Today's Routines", symbol: "clock.arrow.2.circlepath")

                if todayExecutions.isEmpty {
                    HStack {
                        Image(systemName: "moon.zzz")
                            .foregroundStyle(.tertiary)
                        Text("No executions today")
                            .font(.callout)
                            .foregroundStyle(.tertiary)
                    }
                    .frame(maxWidth: .infinity, alignment: .center)
                    .padding(.vertical, Spacing.sm)
                } else {
                    HStack(spacing: Spacing.xl) {
                        StatPill(value: completed, label: "Done", color: .statusGreen)
                        StatPill(value: failed, label: "Failed", color: .statusRed)
                        if running > 0 {
                            StatPill(value: running, label: "Running", color: .statusBlue)
                        }
                    }

                    VStack(alignment: .leading, spacing: Spacing.sm) {
                        ForEach(appState.routines.prefix(4)) { routine in
                            if let last = routine.lastExecution {
                                RoutineStatusRow(name: routine.title, execution: last)
                            }
                        }
                    }
                }
            }
        }
        .frame(minHeight: 180)
    }
}

struct StatPill: View {
    var value: Int
    var label: String
    var color: Color

    var body: some View {
        VStack(spacing: Spacing.xs) {
            Text("\(value)")
                .font(.title2.bold())
                .foregroundStyle(color)
            Text(label)
                .font(.caption)
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
        HStack(spacing: Spacing.sm) {
            Image(systemName: execution.status.symbol)
                .foregroundStyle(statusColor)
                .font(.callout)
            Text(name)
                .font(.callout)
                .lineLimit(1)
            Spacer()
            Text(execution.timeSlot)
                .font(.callout.monospacedDigit())
                .foregroundStyle(.tertiary)
        }
    }
}

// MARK: - Sessions Summary Card

struct SessionsSummaryCard: View {
    @EnvironmentObject var appState: AppState

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Spacing.lg) {
                SectionHeader(title: "Sessions", symbol: "list.bullet.rectangle")

                HStack(spacing: Spacing.xl) {
                    StatPill(value: appState.sessions.sessions.count, label: "Total", color: .statusBlue)
                    if let active = appState.sessions.active {
                        VStack(alignment: .leading, spacing: Spacing.xs) {
                            Text("Active")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            Text(active.name)
                                .font(.callout.bold())
                                .lineLimit(1)
                        }
                    }
                }

                if let active = appState.sessions.active {
                    VStack(alignment: .leading, spacing: Spacing.sm) {
                        SettingRow("Model") { ModelBadge(model: active.model) }
                        if let agentId = active.agentId {
                            SettingRow("Agent") {
                                Text(appState.agents.first { $0.id == agentId }?.name ?? agentId)
                                    .font(.callout)
                                    .lineLimit(1)
                            }
                        }
                        SettingRow("Messages") {
                            Text("\(active.messageCount)")
                                .font(.callout.monospacedDigit())
                        }
                    }
                }
            }
        }
        .frame(minHeight: 180)
    }
}
