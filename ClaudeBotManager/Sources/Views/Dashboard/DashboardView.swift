import SwiftUI

struct DashboardView: View {
    @EnvironmentObject var appState: AppState
    @State private var showRestartConfirm = false

    var body: some View {
        ScrollView {
            // Equal-height grid: HStack rows so both cards in each row share height
            VStack(spacing: Spacing.lg) {
                HStack(alignment: .top, spacing: Spacing.lg) {
                    BotStatusCard()     .frame(maxWidth: .infinity, maxHeight: .infinity)
                    ClaudeUsageCard()   .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
                HStack(alignment: .top, spacing: Spacing.lg) {
                    TodayRoutinesCard() .frame(maxWidth: .infinity, maxHeight: .infinity)
                    SessionsSummaryCard().frame(maxWidth: .infinity, maxHeight: .infinity)
                }
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

    private var weekReferencePercent: Double {
        let cal = Calendar.current
        let now = Date()
        let weekday = cal.component(.weekday, from: now)       // 1=Sun … 7=Sat
        let dayIndex = (weekday - 2 + 7) % 7                  // Mon=0 … Sun=6
        let hour   = cal.component(.hour,   from: now)
        let minute = cal.component(.minute, from: now)
        return (Double(dayIndex) + (Double(hour) * 60 + Double(minute)) / 1440.0) / 7.0
    }

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Spacing.lg) {
                SectionHeader(title: "Claude Plan", symbol: "bolt.circle")

                if usage.isAvailable {
                    VStack(spacing: Spacing.md) {
                        UsageBar(
                            percent: usage.sessionPercent,
                            label: "5-Hour Session",
                            sublabel: usage.sessionLabel
                        )
                        weeklyBarSection
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
                } else if usage.hasPlanInfo {
                    planInfoView
                } else {
                    noCredentialsView
                }
            }
        }
        .frame(minHeight: 180)
    }

    // Effective fill for the weekly bar (prefers live API data, falls back to token scan)
    private var effectiveWeeklyPercent: Double {
        if usage.isAvailable       { return usage.weeklyPercent }
        if usage.hasTokenData      { return usage.weeklyTokenPercent }
        return 0
    }

    // 7-segment weekly bar, shared between isAvailable and plan-info views
    private var weeklyBarSection: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            HStack {
                Text("7-Day Window")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
                if usage.isAvailable {
                    Text(usage.weeklyLabel)
                        .font(.caption.monospacedDigit())
                } else if usage.hasTokenData {
                    HStack(spacing: 3) {
                        Text(usage.formatTokens(usage.weeklyTokensUsed))
                            .font(.caption.monospacedDigit().bold())
                        Text("/ \(usage.formatTokens(usage.weeklyTokensRef))")
                            .font(.caption2.monospacedDigit())
                            .foregroundStyle(.secondary)
                    }
                } else {
                    Text("scanning…")
                        .font(.caption2)
                        .foregroundStyle(.quaternary)
                }
            }
            WeeklySegmentBar(
                percent: effectiveWeeklyPercent,
                referencePercent: weekReferencePercent
            )
        }
    }

    private var planInfoView: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            // Plan name + tier pill
            HStack(spacing: Spacing.sm) {
                Image(systemName: "checkmark.seal.fill")
                    .foregroundStyle(Color.statusGreen)
                    .font(.title3)
                VStack(alignment: .leading, spacing: 2) {
                    Text(usage.planName ?? "Claude")
                        .font(.callout.bold())
                    if let tier = usage.rateTier {
                        Text("\(tier) rate limit")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }

            // Weekly bar (reference line only — no fill without data)
            weeklyBarSection

            // Credentials status
            if let exp = usage.credentialsExpireAt {
                HStack(spacing: Spacing.xs) {
                    Image(systemName: usage.credentialsAreValid ? "key.fill" : "key.slash")
                        .font(.caption)
                        .foregroundStyle(usage.credentialsAreValid ? Color.statusGreen : Color.statusRed)
                    Text(usage.credentialsAreValid
                         ? "Credentials valid · expires \(exp, style: .relative)"
                         : "Credentials expired")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var noCredentialsView: some View {
        VStack(spacing: Spacing.sm) {
            Image(systemName: "key.slash")
                .font(.title2)
                .foregroundStyle(.tertiary)
            Text("No credentials found")
                .font(.callout)
                .foregroundStyle(.tertiary)
            Text("Sign in to Claude Code CLI first")
                .font(.caption)
                .foregroundStyle(.quaternary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, Spacing.sm)
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
