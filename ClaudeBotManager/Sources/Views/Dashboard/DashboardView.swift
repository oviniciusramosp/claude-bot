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
        GlassCard(padding: Spacing.xl) {
            HStack(spacing: Spacing.xl) {
                // Image container — 50% width, image stays at fixed natural size
                if let img = Bundle.module.image(forResource: "bot-avatar") {
                    HStack {
                        Spacer()
                        Image(nsImage: img)
                            .resizable()
                            .interpolation(.high)
                            .aspectRatio(contentMode: .fit)
                            .frame(width: 176, height: 180)
                        Spacer()
                    }
                    .frame(maxWidth: .infinity)
                }

                // Status info — 50% width
                VStack(alignment: .leading, spacing: Spacing.md) {
                    cardHeader("Bot Status", symbol: "apple.terminal")

                    // "Running 🟢" — status text + play.circle.fill indicator
                    HStack(spacing: Spacing.sm) {
                        Text(statusText)
                            .font(.system(size: 17, weight: .bold))
                            .tracking(-0.51)
                        if appState.isRunning {
                            Image(systemName: "play.circle.fill")
                                .font(.system(size: 17))
                                .foregroundStyle(Color(red: 0.204, green: 0.780, blue: 0.349)) // #34C759
                        }
                    }

                    if case .running(let pid, let uptime) = appState.botStatus {
                        Text("\(formatUptime(uptime)) - PID \(pid)")
                            .font(.system(size: 10))
                            .foregroundStyle(Color(red: 0.447, green: 0.447, blue: 0.447)) // #727272
                    }

                    HStack(spacing: Spacing.md) {
                        if appState.isRunning {
                            Button(role: .destructive) {
                                Task { await appState.stopBot() }
                            } label: {
                                Label("Stop", systemImage: "stop.fill")
                            }
                            .buttonStyle(.bordered)
                        } else {
                            Button {
                                Task { await appState.startBot() }
                            } label: {
                                Label("Start", systemImage: "play.fill")
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
                                systemImage: "arrow.clockwise"
                            )
                        }
                        .buttonStyle(.bordered)
                        .disabled(isRestarting)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }

    private var statusText: String {
        switch appState.botStatus {
        case .running: "Running"
        case .stopped: "Stopped"
        case .unknown: "Unknown"
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
        GlassCard(padding: Spacing.xl) {
            VStack(alignment: .leading, spacing: Spacing.md) {
                cardHeader("Claude Usage", symbol: "archivebox")

                if usage.isAvailable || usage.hasTokenData {
                    // Large percentage — 17px bold
                    Text("\(Int(effectiveWeeklyPercent * 100))%")
                        .font(.system(size: 17, weight: .bold))
                        .tracking(-0.51)

                    // Segmented bar
                    WeeklySegmentBar(
                        percent: effectiveWeeklyPercent,
                        referencePercent: weekReferencePercent
                    )

                    paceRow
                    renewRow
                    statChips
                } else if usage.hasPlanInfo {
                    planInfoView
                } else {
                    noCredentialsView
                }
            }
        }
    }

    // "⏱ On pace: -2% (expected 58%)"
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
        .font(.system(size: 10))
        .foregroundStyle(Color(red: 0.447, green: 0.447, blue: 0.447))
    }

    // "🕐 Renew Friday 20:00 (3 day 22h)"
    @ViewBuilder
    private var renewRow: some View {
        if let reset = usage.weeklyResetsAt {
            let dayName = { () -> String in
                let f = DateFormatter(); f.dateFormat = "EEEE"; return f.string(from: reset)
            }()
            let timeStr = { () -> String in
                let f = DateFormatter(); f.dateFormat = "HH:mm"; return f.string(from: reset)
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
            .font(.system(size: 10))
            .foregroundStyle(Color(red: 0.447, green: 0.447, blue: 0.447))
        }
    }

    // 3 stat chips — 5px gap, 24px height
    private var statChips: some View {
        HStack(spacing: 5) {
            DashboardChip(symbol: "person.2", value: appState.agents.count)
            DashboardChip(symbol: "clock.arrow.circlepath", value: appState.routines.count)
            DashboardChip(symbol: "bolt", value: appState.skills.count)
        }
    }

    private var planInfoView: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            HStack(spacing: Spacing.sm) {
                Image(systemName: "checkmark.seal.fill")
                    .foregroundStyle(Color(red: 0.204, green: 0.780, blue: 0.349))
                    .font(.title3)
                VStack(alignment: .leading, spacing: 2) {
                    Text(usage.planName ?? "Claude")
                        .font(.callout.bold())
                    if let tier = usage.rateTier {
                        Text("\(tier) rate limit")
                            .font(.system(size: 10))
                            .foregroundStyle(Color(red: 0.447, green: 0.447, blue: 0.447))
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
                        .font(.system(size: 10))
                        .foregroundStyle(usage.credentialsAreValid
                            ? Color(red: 0.204, green: 0.780, blue: 0.349)
                            : Color(red: 1.0, green: 0.220, blue: 0.235))
                    Text(usage.credentialsAreValid
                         ? "Credentials valid · expires \(exp, style: .relative)"
                         : "Credentials expired")
                        .font(.system(size: 10))
                        .foregroundStyle(Color(red: 0.447, green: 0.447, blue: 0.447))
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
                .font(.system(size: 10)).foregroundStyle(.quaternary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, Spacing.sm)
    }
}

// MARK: - Today's Routines Card

struct TodayRoutinesCard: View {
    @EnvironmentObject var appState: AppState

    /// Only automatic executions — excludes manual dry-runs
    private var autoExecutions: [RoutineExecution] {
        appState.routines
            .flatMap { $0.todayExecutions }
            .filter { $0.timeSlot != "dry-run" }
    }

    /// Scheduled timeline slots paired with their execution (if any)
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

    private var completedCount: Int { autoExecutions.filter { $0.status == .completed }.count }
    private var scheduledCount: Int {
        timeline.filter { $0.execution == nil || $0.execution?.status == .pending }.count
    }
    private var failedCount: Int { autoExecutions.filter { $0.status == .failed }.count }

    var body: some View {
        GlassCard(padding: Spacing.xl) {
            VStack(alignment: .leading, spacing: Spacing.md) {
                cardHeader("Today's Routines", symbol: "clock.arrow.circlepath")

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
                        // Left: Summary stats — always show all 3
                        VStack(spacing: 5) {
                            RoutineStatCard(
                                label: "Done", count: completedCount,
                                iconColor: Color(red: 0.204, green: 0.780, blue: 0.349),
                                symbol: "checkmark.circle.fill"
                            )
                            RoutineStatCard(
                                label: "Scheduled", count: scheduledCount,
                                iconColor: Color(red: 0.447, green: 0.447, blue: 0.447),
                                symbol: "clock"
                            )
                            RoutineStatCard(
                                label: "Failed", count: failedCount,
                                iconColor: Color(red: 1.0, green: 0.220, blue: 0.235),
                                symbol: "xmark.circle.fill"
                            )
                        }
                        .frame(maxWidth: .infinity)

                        // Right: Timeline
                        VStack(alignment: .leading, spacing: Spacing.md) {
                            let nowTime = { let f = DateFormatter(); f.dateFormat = "HH:mm"; return f.string(from: Date()) }()

                            ForEach(Array(timeline.enumerated()), id: \.offset) { idx, entry in
                                let isPast = entry.time <= nowTime
                                let nextIsFuture = idx + 1 < timeline.count && timeline[idx + 1].time > nowTime

                                TimelineRow(
                                    time: entry.time,
                                    name: entry.routine.title,
                                    status: entry.execution?.status ?? .pending
                                )

                                // Progress line between past and future
                                if isPast && nextIsFuture {
                                    HStack(spacing: 0) {
                                        Rectangle()
                                            .fill(Color(red: 1.0, green: 0.220, blue: 0.235))
                                            .frame(height: 2)
                                        Circle()
                                            .fill(Color(red: 1.0, green: 0.220, blue: 0.235))
                                            .frame(width: 8, height: 8)
                                    }
                                }
                            }
                        }
                        .frame(maxWidth: .infinity)
                    }
                }
            }
        }
    }
}

// MARK: - Card Header (Figma spec: icon 17px regular + title 15px bold, opacity 50%)

private func cardHeader(_ title: String, symbol: String) -> some View {
    HStack(spacing: 5) {
        Image(systemName: symbol)
            .font(.system(size: 17, weight: .regular))
            .opacity(0.5)
        Text(title)
            .font(.system(size: 15, weight: .bold))
            .tracking(-0.6)
            .opacity(0.5)
    }
    .foregroundStyle(.primary)
}

// MARK: - Dashboard Chip (Figma: 24h, 10px, #727272, bg rgba(0,0,0,0.05), gap 5px)

struct DashboardChip: View {
    var symbol: String
    var value: Int

    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: symbol).font(.system(size: 10))
            Text("\(value)").font(.system(size: 10))
        }
        .foregroundStyle(Color(red: 0.447, green: 0.447, blue: 0.447))
        .frame(maxWidth: .infinity)
        .frame(height: 24)
        .background(Color.black.opacity(0.05))
        .clipShape(RoundedRectangle(cornerRadius: 4))
    }
}

// MARK: - Routine Stat Card (Figma: bg rgba(0,0,0,0.05), 8px radius, 20px h-pad, 15px v-pad)

struct RoutineStatCard: View {
    var label: String
    var count: Int
    var iconColor: Color
    var symbol: String

    var body: some View {
        HStack {
            HStack(spacing: 4) {
                Image(systemName: symbol)
                    .font(.system(size: 10))
                    .foregroundStyle(iconColor)
                Text(label)
                    .font(.system(size: 10))
                    .foregroundStyle(Color(red: 0.447, green: 0.447, blue: 0.447))
            }
            Spacer()
            Text("\(count)")
                .font(.system(size: 17, weight: .bold))
                .tracking(-0.51)
        }
        .padding(.horizontal, Spacing.xl)
        .padding(.vertical, 15)
        .background(Color.black.opacity(0.05))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}

// MARK: - Timeline Row (Figma: 10px, icon colored, name bold, #727272)

struct TimelineRow: View {
    var time: String
    var name: String
    var status: RoutineExecution.Status

    private var statusColor: Color {
        switch status {
        case .completed: Color(red: 0.204, green: 0.780, blue: 0.349) // #34C759
        case .failed:    Color(red: 1.0, green: 0.220, blue: 0.235)   // #FF383C
        case .running:   Color(red: 0.25, green: 0.56, blue: 0.98)
        case .pending, .skipped: Color(red: 0.447, green: 0.447, blue: 0.447) // #727272
        }
    }

    private var statusSymbol: String {
        switch status {
        case .completed: "checkmark.circle.fill"
        case .failed:    "xmark.circle.fill"
        case .running:   "arrow.trianglehead.2.clockwise"
        case .pending, .skipped: "clock"
        }
    }

    var body: some View {
        HStack(spacing: 0) {
            Image(systemName: statusSymbol)
                .font(.system(size: 10))
                .foregroundStyle(statusColor)
            Text(" \(time) - ")
                .font(.system(size: 10))
                .foregroundStyle(Color(red: 0.447, green: 0.447, blue: 0.447))
            Text(name)
                .font(.system(size: 10, weight: .bold))
                .foregroundStyle(Color(red: 0.447, green: 0.447, blue: 0.447))
                .lineLimit(1)
        }
    }
}
