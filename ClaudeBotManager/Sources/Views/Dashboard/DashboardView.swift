import SwiftUI

struct DashboardView: View {
    @EnvironmentObject var appState: AppState

    var body: some View {
        ScrollView {
            VStack(spacing: Spacing.xl) {
                BotStatusCard()
                ClaudeUsageCard()
                TodayRoutinesCard()
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
            HStack(spacing: Spacing.xl) {
                // Robot illustration
                if let img = Bundle.module.image(forResource: "bot-avatar") {
                    Image(nsImage: img)
                        .resizable()
                        .interpolation(.high)
                        .aspectRatio(contentMode: .fit)
                        .frame(maxWidth: 160, maxHeight: 164)
                }

                // Status info
                VStack(alignment: .leading, spacing: Spacing.md) {
                    cardHeader("Bot Status", symbol: "desktopcomputer")

                    HStack(spacing: Spacing.sm) {
                        Text(statusText)
                            .font(.title2.bold())
                            .foregroundStyle(appState.isRunning ? .primary : .secondary)
                        StatusDot(isRunning: appState.isRunning, size: 10)
                    }

                    if case .running(let pid, let uptime) = appState.botStatus {
                        Text("\(formatUptime(uptime)) - PID \(pid)")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }

                    HStack(spacing: Spacing.md) {
                        if appState.isRunning {
                            Button(role: .destructive) {
                                Task { await appState.stopBot() }
                            } label: {
                                Label("Stop", systemImage: "stop.fill").font(.callout)
                            }
                            .buttonStyle(.bordered)
                        } else {
                            Button {
                                Task { await appState.startBot() }
                            } label: {
                                Label("Start", systemImage: "play.fill").font(.callout)
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
                            Label(
                                isRestarting ? "Restarting…" : "Restart",
                                systemImage: "arrow.trianglehead.2.clockwise"
                            )
                            .font(.callout)
                        }
                        .buttonStyle(.bordered)
                        .disabled(isRestarting)
                    }
                }

                Spacer(minLength: 0)
            }
        }
    }

    private var statusText: String {
        switch appState.botStatus {
        case .running: return "Running"
        case .stopped: return "Stopped"
        case .unknown: return "Unknown"
        }
    }

    private func formatUptime(_ t: TimeInterval) -> String {
        let s = Int(t)
        if s < 60 { return "\(s)s" }
        if s < 3600 { return "\(s/60)m" }
        if s < 86400 { return "\(s/3600)h \((s%3600)/60)min" }
        return "\(s/86400)d \((s%86400)/3600)h"
    }
}

// MARK: - Claude Usage Card

struct ClaudeUsageCard: View {
    @EnvironmentObject var appState: AppState

    private var usage: ClaudeUsage { appState.claudeUsage }

    // Elapsed fraction of the 7-day window
    private var weekReferencePercent: Double {
        let now = Date()
        if let resetsAt = usage.weeklyResetsAt {
            let windowStart = resetsAt.addingTimeInterval(-7 * 24 * 3600)
            return max(0, min(1, now.timeIntervalSince(windowStart) / (7 * 24 * 3600)))
        }
        let cal = Calendar.current
        let weekday = cal.component(.weekday, from: now)
        let dayIndex = (weekday - 2 + 7) % 7
        let hour   = cal.component(.hour,   from: now)
        let minute = cal.component(.minute, from: now)
        return (Double(dayIndex) + (Double(hour) * 60 + Double(minute)) / 1440.0) / 7.0
    }

    private var effectiveWeeklyPercent: Double {
        if usage.isAvailable  { return usage.weeklyPercent }
        if usage.hasTokenData { return usage.weeklyTokenPercent }
        return 0
    }

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Spacing.md) {
                cardHeader("Claude Usage", symbol: "bolt.circle")

                if usage.isAvailable || usage.hasTokenData {
                    // Large percentage
                    Text("\(Int(effectiveWeeklyPercent * 100))%")
                        .font(.title2.bold())

                    // Segmented bar
                    WeeklySegmentBar(
                        percent: effectiveWeeklyPercent,
                        referencePercent: weekReferencePercent
                    )

                    // Pace info
                    paceRow

                    // Renew info
                    renewRow

                    // Stat chips
                    statChips
                } else if usage.hasPlanInfo {
                    planInfoView
                } else {
                    noCredentialsView
                }
            }
        }
    }

    // "On pace: -2% (expected 58%)" or "Above pace: +30% (expected 58%)"
    private var paceRow: some View {
        let expected = Int(weekReferencePercent * 100)
        let actual   = Int(effectiveWeeklyPercent * 100)
        let offset   = actual - expected
        let label: String
        if offset <= 0 {
            label = "On pace: \(offset)% (expected \(expected)%)"
        } else {
            label = "Above pace: +\(offset)% (expected \(expected)%)"
        }

        return HStack(spacing: 4) {
            Image(systemName: "timer")
            Text(label)
        }
        .font(.caption)
        .foregroundStyle(.secondary)
    }

    // "Renew Friday 20:00 (3 day 22h)"
    @ViewBuilder
    private var renewRow: some View {
        if let reset = usage.weeklyResetsAt {
            let dayName = { () -> String in
                let f = DateFormatter()
                f.dateFormat = "EEEE"
                return f.string(from: reset)
            }()
            let timeStr = { () -> String in
                let f = DateFormatter()
                f.dateFormat = "HH:mm"
                return f.string(from: reset)
            }()
            let remaining = { () -> String in
                let secs = Int(max(0, reset.timeIntervalSinceNow))
                let d = secs / 86400
                let h = (secs % 86400) / 3600
                if d > 0 { return "\(d) day \(h)h" }
                return "\(h)h"
            }()

            HStack(spacing: 4) {
                Image(systemName: "clock")
                Text("Renew \(dayName) \(timeStr) (\(remaining))")
            }
            .font(.caption)
            .foregroundStyle(.secondary)
        }
    }

    // 3 stat chips: agents, routines, skills
    private var statChips: some View {
        HStack(spacing: Spacing.sm) {
            DashboardChip(symbol: "person.2", value: appState.agents.count)
            DashboardChip(symbol: "clock.arrow.circlepath", value: appState.routines.count)
            DashboardChip(symbol: "bolt", value: appState.skills.count)
        }
    }

    private var planInfoView: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            HStack(spacing: Spacing.sm) {
                Image(systemName: "checkmark.seal.fill")
                    .foregroundStyle(Color.statusGreen)
                    .font(.title3)
                VStack(alignment: .leading, spacing: 2) {
                    Text(usage.planName ?? "Claude")
                        .font(.callout.bold())
                    if let tier = usage.rateTier {
                        Text("\(tier) rate limit")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
            }

            WeeklySegmentBar(
                percent: effectiveWeeklyPercent,
                referencePercent: weekReferencePercent
            )

            if let exp = usage.credentialsExpireAt {
                HStack(spacing: Spacing.xs) {
                    Image(systemName: usage.credentialsAreValid ? "key.fill" : "key.slash")
                        .font(.caption)
                        .foregroundStyle(usage.credentialsAreValid ? Color.statusGreen : Color.statusRed)
                    Text(usage.credentialsAreValid
                         ? "Credentials valid · expires \(exp, style: .relative)"
                         : "Credentials expired")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var noCredentialsView: some View {
        VStack(spacing: Spacing.sm) {
            Image(systemName: "key.slash")
                .font(.title2).foregroundStyle(.tertiary)
            Text("No credentials found")
                .font(.callout).foregroundStyle(.tertiary)
            Text("Sign in to Claude Code CLI first")
                .font(.caption).foregroundStyle(.quaternary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, Spacing.sm)
    }
}

// MARK: - Today's Routines Card

struct TodayRoutinesCard: View {
    @EnvironmentObject var appState: AppState

    private var allExecutions: [RoutineExecution] {
        appState.routines.flatMap { $0.todayExecutions }
    }

    /// All scheduled time slots today (from routine definitions), paired with their execution if any
    private var timeline: [(routine: Routine, time: String, execution: RoutineExecution?)] {
        var entries: [(routine: Routine, time: String, execution: RoutineExecution?)] = []

        for routine in appState.routines where routine.enabled {
            for time in routine.schedule.times {
                let exec = routine.todayExecutions.first { $0.timeSlot == time }
                entries.append((routine: routine, time: time, execution: exec))
            }
        }
        return entries.sorted { $0.time < $1.time }
    }

    private var completedCount: Int { allExecutions.filter { $0.status == .completed }.count }
    private var scheduledCount: Int {
        timeline.filter { entry in
            entry.execution == nil || entry.execution?.status == .pending
        }.count
    }
    private var failedCount: Int { allExecutions.filter { $0.status == .failed }.count }

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Spacing.md) {
                cardHeader("Today's Routines", symbol: "clock.arrow.2.circlepath")

                if timeline.isEmpty {
                    HStack {
                        Image(systemName: "moon.zzz").foregroundStyle(.tertiary)
                        Text("No routines scheduled today")
                            .font(.callout).foregroundStyle(.tertiary)
                    }
                    .frame(maxWidth: .infinity, alignment: .center)
                    .padding(.vertical, Spacing.sm)
                } else {
                    HStack(alignment: .top, spacing: Spacing.xl) {
                        // Left: Summary stats
                        VStack(spacing: Spacing.sm) {
                            RoutineStatCard(label: "Done", count: completedCount, color: .statusGreen, symbol: "checkmark")
                            RoutineStatCard(label: "Scheduled", count: scheduledCount, color: .secondary, symbol: "clock")
                            if failedCount > 0 {
                                RoutineStatCard(label: "Failed", count: failedCount, color: .statusRed, symbol: "exclamationmark.triangle")
                            }
                        }
                        .frame(width: 160)

                        // Right: Timeline
                        VStack(alignment: .leading, spacing: 0) {
                            let nowTime = { let f = DateFormatter(); f.dateFormat = "HH:mm"; return f.string(from: Date()) }()

                            ForEach(Array(timeline.enumerated()), id: \.offset) { idx, entry in
                                let isPast = entry.time <= nowTime
                                let nextIsFuture = idx + 1 < timeline.count && timeline[idx + 1].time > nowTime

                                TimelineRow(
                                    time: entry.time,
                                    name: entry.routine.title,
                                    status: entry.execution?.status ?? .pending
                                )
                                .padding(.vertical, 5)

                                // Progress line between past and future entries
                                if isPast && nextIsFuture {
                                    HStack(spacing: 0) {
                                        Rectangle()
                                            .fill(Color.statusRed.opacity(0.5))
                                            .frame(height: 2)
                                        Circle()
                                            .fill(Color.statusRed)
                                            .frame(width: 8, height: 8)
                                    }
                                    .padding(.vertical, 4)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

// MARK: - Helper Components

/// Section header matching Figma style — icon + title, 50% opacity
private func cardHeader(_ title: String, symbol: String) -> some View {
    HStack(spacing: 5) {
        Image(systemName: symbol)
            .font(.body)
            .opacity(0.5)
        Text(title)
            .font(.subheadline.bold())
            .tracking(-0.6)
            .opacity(0.5)
    }
    .foregroundStyle(.primary)
}

/// Stat chip at bottom of usage card
struct DashboardChip: View {
    var symbol: String
    var value: Int

    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: symbol).font(.caption)
            Text("\(value)").font(.caption)
        }
        .foregroundStyle(.secondary)
        .padding(.horizontal, 8)
        .padding(.vertical, 5)
        .frame(maxWidth: .infinity)
        .background(Color.primary.opacity(0.05))
        .clipShape(RoundedRectangle(cornerRadius: 4))
    }
}

/// Summary stat card for Today's Routines left column
struct RoutineStatCard: View {
    var label: String
    var count: Int
    var color: Color
    var symbol: String

    var body: some View {
        HStack {
            HStack(spacing: 6) {
                Image(systemName: symbol)
                    .font(.caption)
                    .foregroundStyle(color)
                Text(label)
                    .font(.caption)
            }
            Spacer()
            Text("\(count)")
                .font(.title2.bold())
        }
        .padding(.horizontal, Spacing.xl)
        .padding(.vertical, Spacing.lg)
        .background(Color.primary.opacity(0.05))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}

/// Single row in the routines timeline
struct TimelineRow: View {
    var time: String
    var name: String
    var status: RoutineExecution.Status

    private var statusColor: Color {
        switch status {
        case .completed: .statusGreen
        case .failed:    .statusRed
        case .running:   .statusBlue
        case .pending, .skipped: .secondary
        }
    }

    var body: some View {
        HStack(spacing: Spacing.sm) {
            Text(time)
                .font(.caption.monospacedDigit())
                .foregroundStyle(.secondary)
                .frame(width: 40, alignment: .trailing)
            Image(systemName: status.symbol)
                .font(.caption)
                .foregroundStyle(statusColor)
            Text(name)
                .font(.caption.bold())
                .lineLimit(1)
        }
    }
}
