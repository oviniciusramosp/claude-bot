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
        GlassCard(padding: 12) {
            HStack(spacing: 12) {
                // Status indicator
                statusView
                    .frame(width: 16, height: 16)
                    .help(statusTooltip)

                VStack(alignment: .leading, spacing: 3) {
                    Text(routine.title)
                        .font(.callout.bold())
                        .lineLimit(1)

                    HStack(spacing: 8) {
                        Label(routine.schedule.times.joined(separator: ", "), systemImage: "clock")
                            .font(.caption2)
                            .foregroundStyle(.secondary)

                        if !routine.schedule.days.contains("*") {
                            Text(routine.schedule.days.joined(separator: " "))
                                .font(.caption2)
                                .foregroundStyle(.tertiary)
                        }

                        if let agent = agentName {
                            Label(agent, systemImage: "person.fill")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }

                        if routine.isPipeline {
                            pipelineBadge
                        }
                    }
                }

                Spacer()

                // Dry-run button — only when last execution failed
                if !isDryRunning && routine.lastExecution?.status == .failed {
                    Button {
                        isDryRunning = true
                        Task {
                            try? await appState.dryRunRoutine(routine)
                            isDryRunning = false
                        }
                    } label: {
                        Label("Run", systemImage: "play.circle")
                            .font(.caption2)
                    }
                    .buttonStyle(.borderless)
                    .foregroundStyle(Color.statusBlue)
                    .help("Run now")
                }

                VStack(alignment: .trailing, spacing: 4) {
                    ModelBadge(model: routine.model)
                    Text(routine.nextExecutionDescription)
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }

                Toggle("", isOn: $isEnabled)
                    .labelsHidden()
                    .onChange(of: isEnabled) { _, newValue in
                        var updated = routine
                        updated.enabled = newValue
                        Task { try? await appState.saveRoutine(updated) }
                    }
            }
        }
        .contentShape(Rectangle())
    }

    @ViewBuilder
    private var statusView: some View {
        if effectiveStatus == .running {
            ProgressView()
                .scaleEffect(0.55)
        } else {
            Image(systemName: statusSymbol)
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(statusColor)
        }
    }

    @ViewBuilder
    private var pipelineBadge: some View {
        let total = routine.pipelineStepsTotal
        let done = routine.pipelineStepsCompleted
        HStack(spacing: 3) {
            Image(systemName: "arrow.triangle.branch")
                .font(.caption2)
            if total > 0 {
                Text("\(done)/\(total)")
                    .font(.caption2.monospacedDigit())
            } else {
                Text("\(routine.stepCount) steps")
                    .font(.caption2)
            }
        }
        .foregroundStyle(Color.statusBlue)
        .help("Pipeline: \(done)/\(total) steps completed")
    }
}
