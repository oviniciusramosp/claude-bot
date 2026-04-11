import SwiftUI
import Charts

/// Rich visualization of the bot's cost tracker (~/.claude-bot/costs.json).
///
/// Shows daily spend over a selectable window (7/30 days), weekly totals for
/// every week still in the file, and the biggest-spending days. Uses Swift
/// Charts + the project's shared `GlassCard` / `SectionCard` design system.
struct UsageView: View {
    @EnvironmentObject var appState: AppState

    @State private var selectedRange: Range = .sevenDays
    @State private var series: [CostEntry] = []
    @State private var weeks: [WeekBucket] = []
    @State private var totalInRange: Double = 0
    @State private var totalToday: Double = 0
    @State private var totalThisWeek: Double = 0
    @State private var isLoading = true
    @State private var loadError: String?

    enum Range: String, CaseIterable, Identifiable {
        case sevenDays = "7d"
        case thirtyDays = "30d"
        var id: String { rawValue }

        var days: Int {
            switch self {
            case .sevenDays: return 7
            case .thirtyDays: return 30
            }
        }

        var label: String {
            switch self {
            case .sevenDays: return "7 days"
            case .thirtyDays: return "30 days"
            }
        }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.xl) {
                headerCard
                if isLoading {
                    ProgressView().frame(maxWidth: .infinity, minHeight: 140)
                } else if let err = loadError {
                    errorCard(err)
                } else if series.isEmpty || totalInRange == 0 && weeks.allSatisfy({ $0.total == 0 }) {
                    emptyStateCard
                } else {
                    dailyChartCard
                    weeklyChartCard
                    topDaysCard
                }
            }
            .padding(Spacing.xl)
        }
        .background(Color(.windowBackgroundColor))
        .navigationTitle("Usage")
        .toolbar {
            ToolbarItem {
                Button {
                    Task { await reload() }
                } label: {
                    Label("Refresh", systemImage: "arrow.clockwise")
                }
            }
        }
        .task(id: appState.dataDir) {
            await reload()
        }
        .task(id: selectedRange) {
            await reload()
        }
    }

    // MARK: - Header

    private var headerCard: some View {
        SectionCard(title: "Usage", symbol: "chart.line.uptrend.xyaxis") {
            VStack(alignment: .leading, spacing: Spacing.md) {
                HStack(alignment: .firstTextBaseline, spacing: Spacing.md) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(formatCurrency(totalThisWeek))
                            .font(.system(size: 34, weight: .bold, design: .rounded))
                            .monospacedDigit()
                        Text("this week")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    VStack(alignment: .trailing, spacing: 2) {
                        Text(formatCurrency(totalToday))
                            .font(.title3.monospacedDigit())
                            .foregroundStyle(.primary)
                        Text("today")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }

                Picker("Range", selection: $selectedRange) {
                    ForEach(Range.allCases) { r in
                        Text(r.label).tag(r)
                    }
                }
                .pickerStyle(.segmented)
                .labelsHidden()
            }
        }
    }

    // MARK: - Daily chart

    private var dailyChartCard: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Spacing.md) {
                HStack {
                    Label("Daily Cost", systemImage: "calendar")
                        .font(.headline)
                    Spacer()
                    Text(formatCurrency(totalInRange) + " · last \(selectedRange.days) days")
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                }

                Chart(series) { entry in
                    BarMark(
                        x: .value("Day", entry.date, unit: .day),
                        y: .value("Cost", entry.cost)
                    )
                    .foregroundStyle(Color.statusBlue.gradient)
                    .cornerRadius(3)
                }
                .frame(height: 180)
                .chartYAxis {
                    AxisMarks(position: .leading) { value in
                        AxisGridLine()
                        AxisValueLabel {
                            if let d = value.as(Double.self) {
                                Text(formatCurrencyCompact(d))
                                    .font(.caption2.monospacedDigit())
                            }
                        }
                    }
                }
                .chartXAxis {
                    AxisMarks(values: .stride(by: xAxisStride)) { value in
                        AxisGridLine()
                        AxisValueLabel(format: .dateTime.month(.abbreviated).day(), centered: true)
                    }
                }
            }
        }
    }

    private var xAxisStride: Calendar.Component {
        selectedRange == .sevenDays ? .day : .weekOfYear
    }

    // MARK: - Weekly totals

    private var weeklyChartCard: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Spacing.md) {
                HStack {
                    Label("Weekly Totals", systemImage: "calendar.badge.clock")
                        .font(.headline)
                    Spacer()
                    Text("\(weeks.count) week\(weeks.count == 1 ? "" : "s") on file")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                if weeks.isEmpty {
                    Text("No weekly data yet.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .padding(.vertical, Spacing.lg)
                } else {
                    Chart(weeks) { week in
                        BarMark(
                            x: .value("Week", week.weekKey),
                            y: .value("Total", week.total)
                        )
                        .foregroundStyle(weekBarColor(for: week).gradient)
                        .cornerRadius(3)
                        .annotation(position: .top, alignment: .center, spacing: 2) {
                            Text(formatCurrencyCompact(week.total))
                                .font(.caption2.monospacedDigit())
                                .foregroundStyle(.secondary)
                        }
                    }
                    .frame(height: 160)
                    .chartYAxis {
                        AxisMarks(position: .leading) { value in
                            AxisGridLine()
                            AxisValueLabel {
                                if let d = value.as(Double.self) {
                                    Text(formatCurrencyCompact(d))
                                        .font(.caption2.monospacedDigit())
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    private func weekBarColor(for week: WeekBucket) -> Color {
        guard let current = currentWeekKey(), week.weekKey == current else {
            return .statusBlue.opacity(0.55)
        }
        return .statusBlue
    }

    private func currentWeekKey() -> String? {
        weeks.last?.weekKey
    }

    // MARK: - Top days

    private var topDaysCard: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Spacing.md) {
                HStack {
                    Label("Top Days", systemImage: "star.fill")
                        .font(.headline)
                    Spacer()
                    Text("by cost")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                let top = topDays()
                if top.isEmpty {
                    Text("No spending recorded in this window.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .padding(.vertical, Spacing.md)
                } else {
                    VStack(spacing: Spacing.sm) {
                        ForEach(top) { entry in
                            HStack {
                                Text(entry.date, format: .dateTime.weekday(.wide).month(.abbreviated).day())
                                    .font(.callout)
                                    .foregroundStyle(.primary)
                                Spacer()
                                Text(formatCurrency(entry.cost))
                                    .font(.callout.monospacedDigit())
                                    .foregroundStyle(.primary)
                            }
                            if entry.id != top.last?.id {
                                Divider()
                            }
                        }
                    }
                }
            }
        }
    }

    private func topDays() -> [CostEntry] {
        series
            .filter { $0.cost > 0 }
            .sorted { $0.cost > $1.cost }
            .prefix(5)
            .map { $0 }
    }

    // MARK: - Empty / error

    private var emptyStateCard: some View {
        GlassCard {
            EmptyStateView(
                symbol: "chart.bar.xaxis",
                title: "No usage data yet",
                subtitle: "Costs appear here after the bot records its first Claude invocation."
            )
            .frame(minHeight: 220)
        }
    }

    private func errorCard(_ message: String) -> some View {
        GlassCard {
            VStack(spacing: Spacing.md) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.system(size: 32))
                    .foregroundStyle(Color.statusYellow)
                Text("Couldn't read costs.json")
                    .font(.headline)
                Text(message)
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                Button("Retry") {
                    Task { await reload() }
                }
            }
            .frame(maxWidth: .infinity)
            .padding(Spacing.lg)
        }
    }

    // MARK: - Data

    private func reload() async {
        isLoading = true
        loadError = nil
        let service = CostHistoryService(dataDir: appState.dataDir)
        do {
            let dense = try await service.dailySeries(forLastDays: selectedRange.days)
            let total = try await service.totalForLastDays(selectedRange.days)
            let history = try await service.loadHistory()
            let today = try await service.totalToday()
            let week = try await service.totalThisWeek()
            self.series = dense
            self.weeks = history.weeks
            self.totalInRange = total
            self.totalToday = today
            self.totalThisWeek = week
            self.isLoading = false
        } catch {
            self.loadError = error.localizedDescription
            self.series = []
            self.weeks = []
            self.totalInRange = 0
            self.totalToday = 0
            self.totalThisWeek = 0
            self.isLoading = false
        }
    }

    // MARK: - Formatting

    private func formatCurrency(_ value: Double) -> String {
        String(format: "$%.2f", value)
    }

    /// Compact currency format for axis labels and annotations:
    /// "$0.00", "$0.12", "$1.2", "$12", "$1.2k".
    private func formatCurrencyCompact(_ value: Double) -> String {
        if value == 0 { return "$0" }
        if value < 0.01 { return String(format: "$%.3f", value) }
        if value < 1 { return String(format: "$%.2f", value) }
        if value < 10 { return String(format: "$%.2f", value) }
        if value < 100 { return String(format: "$%.1f", value) }
        if value < 1000 { return String(format: "$%.0f", value) }
        return String(format: "$%.1fk", value / 1000)
    }
}
