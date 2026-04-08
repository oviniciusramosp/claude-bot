import SwiftUI

struct RoutineListView: View {
    @EnvironmentObject var appState: AppState
    @State private var showCreateSheet = false
    @State private var selectedRoutine: Routine? = nil

    var body: some View {
        Group {
            if appState.routines.isEmpty {
                EmptyStateView(
                    symbol: "clock.arrow.2.circlepath",
                    title: "No Routines",
                    subtitle: "Create a routine to schedule automated tasks."
                )
            } else {
                List(appState.routines) { routine in
                    RoutineRow(routine: routine)
                        .onTapGesture { selectedRoutine = routine }
                        .listRowBackground(Color.clear)
                        .listRowSeparator(.hidden)
                        .padding(.vertical, 2)
                }
                .listStyle(.plain)
                .scrollContentBackground(.hidden)
            }
        }
        .navigationTitle("Routines")
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    showCreateSheet = true
                } label: {
                    Label("New Routine", systemImage: "plus")
                }
            }
        }
        .sheet(item: $selectedRoutine) { routine in
            RoutineDetailView(routine: routine)
        }
        .sheet(isPresented: $showCreateSheet) {
            RoutineFormSheet()
        }
    }
}

struct RoutineRow: View {
    var routine: Routine
    @EnvironmentObject var appState: AppState
    @State private var isEnabled: Bool
    @State private var isDryRunning = false

    init(routine: Routine) {
        self.routine = routine
        _isEnabled = State(initialValue: routine.enabled)
    }

    private var effectiveStatus: RoutineExecution.Status? {
        isDryRunning ? .running : routine.lastExecution?.status
    }

    private var statusSymbol: String {
        switch effectiveStatus {
        case .none:      return "clock"
        case .pending:   return "clock"
        case .running:   return "arrow.trianglehead.2.clockwise"
        case .completed: return "checkmark.circle.fill"
        case .failed:    return "exclamationmark.circle.fill"
        case .skipped:   return "forward.fill"
        }
    }

    private var statusColor: Color {
        switch effectiveStatus {
        case .none, .pending, .skipped: return .secondary
        case .running:                  return .statusBlue
        case .completed:                return .statusGreen
        case .failed:                   return .statusRed
        }
    }

    private var statusTooltip: String {
        if isDryRunning { return "Dry run in progress..." }
        guard let exec = routine.lastExecution else { return "No executions today" }
        switch exec.status {
        case .pending:   return "Scheduled: \(exec.timeSlot)"
        case .running:
            if routine.isPipeline {
                let done = exec.pipelineSteps.filter { $0.status == .completed }.count
                return "Running step \(done + 1)/\(exec.pipelineSteps.count)"
            }
            return "Running since \(exec.timeSlot)"
        case .completed:
            let dur = exec.duration.map { " (\($0))" } ?? ""
            return "Completed at \(exec.timeSlot)\(dur)"
        case .failed:
            let err = exec.error.map { " — \($0)" } ?? ""
            return "Failed at \(exec.timeSlot)\(err)"
        case .skipped:  return "Skipped"
        }
    }

    private var agentName: String? {
        routine.agentId.flatMap { id in appState.agents.first { $0.id == id }?.name }
    }

    var body: some View {
        GlassCard(padding: Spacing.lg) {
            HStack(alignment: .top, spacing: Spacing.md) {
                // Pipeline accent bar
                if routine.isPipeline {
                    RoundedRectangle(cornerRadius: 2)
                        .fill(Color.statusBlue)
                        .frame(width: 3)
                }

                // Status indicator
                statusView
                    .frame(width: 20, height: 20)
                    .help(statusTooltip)
                    .padding(.top, 2)

                // Content
                VStack(alignment: .leading, spacing: Spacing.sm) {
                    // Line 1: Title + Model + Toggle
                    HStack(spacing: Spacing.sm) {
                        Text(routine.title)
                            .font(.body.bold())
                            .lineLimit(1)
                        Spacer()
                        ModelBadge(model: routine.model)
                        Toggle("", isOn: $isEnabled)
                            .labelsHidden()
                            .onChange(of: isEnabled) { _, newValue in
                                var updated = routine
                                updated.enabled = newValue
                                Task { try? await appState.saveRoutine(updated) }
                            }
                    }

                    // Line 2: Schedule metadata
                    HStack(spacing: Spacing.sm) {
                        Text(routine.schedule.times.joined(separator: ", "))
                            .font(.caption.monospacedDigit())
                            .foregroundStyle(.secondary)

                        Text("·").foregroundStyle(.quaternary)

                        Text(humanReadableDays(routine.schedule.days))
                            .font(.caption)
                            .foregroundStyle(.secondary)

                        if let agent = agentName {
                            Text("·").foregroundStyle(.quaternary)
                            Label(agent, systemImage: "person.fill")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }

                    // Line 3: Pipeline info + Next execution + Dry-run
                    HStack(spacing: Spacing.sm) {
                        if routine.isPipeline {
                            pipelineBadge
                        }

                        if !isDryRunning && routine.lastExecution?.status == .failed {
                            Button {
                                isDryRunning = true
                                Task {
                                    try? await appState.dryRunRoutine(routine)
                                    isDryRunning = false
                                }
                            } label: {
                                Label("Retry", systemImage: "play.circle")
                                    .font(.caption)
                            }
                            .buttonStyle(.borderless)
                            .foregroundStyle(Color.statusBlue)
                        }

                        Spacer()

                        Text(routine.nextExecutionDescription)
                            .font(.caption)
                            .foregroundStyle(.tertiary)
                    }
                }
            }
        }
        .contentShape(Rectangle())
    }

    @ViewBuilder
    private var statusView: some View {
        if effectiveStatus == .running {
            ProgressView()
                .scaleEffect(0.6)
        } else {
            Image(systemName: statusSymbol)
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(statusColor)
        }
    }

    @ViewBuilder
    private var pipelineBadge: some View {
        let total = routine.pipelineStepsTotal
        let done = routine.pipelineStepsCompleted
        HStack(spacing: 4) {
            Image(systemName: "arrow.triangle.branch")
                .font(.caption)
            if total > 0 {
                Text("\(done)/\(total) steps")
                    .font(.caption.monospacedDigit())
            } else {
                Text("\(routine.stepCount) steps")
                    .font(.caption)
            }
        }
        .foregroundStyle(Color.statusBlue)
        .help("Pipeline: \(done)/\(total) steps completed")
    }

    private func humanReadableDays(_ days: [String]) -> String {
        if days.contains("*") { return "Daily" }
        let weekdays = Set(["mon", "tue", "wed", "thu", "fri"])
        let weekends = Set(["sat", "sun"])
        let daySet = Set(days)
        if daySet == weekdays { return "Weekdays" }
        if daySet == weekends { return "Weekends" }
        if daySet == weekdays.union(weekends) { return "Daily" }
        return days.map { $0.prefix(1).uppercased() + $0.dropFirst().prefix(2) }.joined(separator: ", ")
    }
}
