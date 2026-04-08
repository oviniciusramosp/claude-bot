import SwiftUI

struct RoutineListView: View {
    @EnvironmentObject var appState: AppState
    @State private var showCreateSheet = false
    @State private var selectedRoutine: Routine? = nil

    var body: some View {
        ScrollView {
            VStack(spacing: Spacing.lg) {
                if appState.routines.isEmpty {
                    EmptyStateView(
                        symbol: "clock.arrow.2.circlepath",
                        title: "No Routines",
                        subtitle: "Create a routine to schedule automated tasks."
                    )
                } else {
                    ForEach(appState.routines) { routine in
                        RoutineRow(routine: routine)
                            .onTapGesture { selectedRoutine = routine }
                    }
                }
            }
            .padding(Spacing.xl)
        }
        .background(Color(.windowBackgroundColor))
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

// MARK: - Routine Row

struct RoutineRow: View {
    var routine: Routine
    @EnvironmentObject var appState: AppState
    @State private var isEnabled: Bool
    @State private var isDryRunning = false
    @State private var isStopping = false

    init(routine: Routine) {
        self.routine = routine
        _isEnabled = State(initialValue: routine.enabled)
    }

    private var isRunning: Bool {
        isDryRunning || routine.lastExecution?.status == .running
    }

    private var effectiveStatus: RoutineExecution.Status? {
        if isDryRunning { return .running }
        return routine.lastExecution?.status
    }

    private var statusColor: Color {
        switch effectiveStatus {
        case .none, .pending, .skipped: Color(red: 0.447, green: 0.447, blue: 0.447)
        case .running:                  Color(red: 0.25, green: 0.56, blue: 0.98)
        case .completed:                Color(red: 0.204, green: 0.780, blue: 0.349)
        case .failed:                   Color(red: 1.0, green: 0.220, blue: 0.235)
        }
    }

    private var statusSymbol: String {
        switch effectiveStatus {
        case .none, .pending:  "clock"
        case .running:         "arrow.trianglehead.2.clockwise"
        case .completed:       "checkmark.circle.fill"
        case .failed:          "xmark.circle.fill"
        case .skipped:         "forward.fill"
        }
    }

    private var agentName: String? {
        routine.agentId.flatMap { id in appState.agents.first { $0.id == id }?.name }
    }

    var body: some View {
        GlassCard(padding: Spacing.xl) {
            VStack(alignment: .leading, spacing: Spacing.md) {
                // Row 1: Status + Title + Model + Toggle
                HStack(spacing: Spacing.md) {
                    // Status indicator
                    if isRunning {
                        ProgressView()
                            .scaleEffect(0.6)
                            .frame(width: 20, height: 20)
                    } else {
                        Image(systemName: statusSymbol)
                            .font(.system(size: 14, weight: .semibold))
                            .foregroundStyle(statusColor)
                            .frame(width: 20, height: 20)
                    }

                    Text(routine.title)
                        .font(.system(size: 15, weight: .bold))
                        .tracking(-0.6)
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

                // Row 2: Schedule metadata
                HStack(spacing: Spacing.sm) {
                    Text(routine.schedule.times.joined(separator: ", "))
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(Color(red: 0.447, green: 0.447, blue: 0.447))

                    Text("·").foregroundStyle(.quaternary)

                    Text(humanReadableDays(routine.schedule.days))
                        .font(.system(size: 10))
                        .foregroundStyle(Color(red: 0.447, green: 0.447, blue: 0.447))

                    if let agent = agentName {
                        Text("·").foregroundStyle(.quaternary)
                        Label(agent, systemImage: "person.fill")
                            .font(.system(size: 10))
                            .foregroundStyle(Color(red: 0.447, green: 0.447, blue: 0.447))
                    }

                    Spacer()

                    Text(routine.nextExecutionDescription)
                        .font(.system(size: 10))
                        .foregroundStyle(.tertiary)
                }

                // Row 3: Pipeline horizontal timeline (if pipeline and has execution data)
                if routine.isPipeline {
                    pipelineTimeline
                }

                // Running pulse bar
                if isRunning {
                    runningBar
                }
            }
        }
        .contentShape(Rectangle())
        .contextMenu { contextMenuItems }
        // Overlay: subtle left accent for pipelines
        .overlay(alignment: .leading) {
            if routine.isPipeline {
                RoundedRectangle(cornerRadius: 2)
                    .fill(Color.statusBlue)
                    .frame(width: 3)
                    .padding(.vertical, 4)
            }
        }
    }

    // MARK: - Context Menu

    @ViewBuilder
    private var contextMenuItems: some View {
        if isRunning {
            Button {
                isStopping = true
                Task {
                    try? await appState.stopRoutine(routine)
                    isDryRunning = false
                    isStopping = false
                }
            } label: {
                Label("Stop", systemImage: "stop.fill")
            }
            .disabled(isStopping)
        } else {
            Button {
                isDryRunning = true
                Task {
                    try? await appState.dryRunRoutine(routine)
                    isDryRunning = false
                }
            } label: {
                Label("Run Now", systemImage: "play.fill")
            }
        }

        Divider()

        Button {
            var updated = routine
            updated.enabled.toggle()
            Task { try? await appState.saveRoutine(updated) }
            isEnabled.toggle()
        } label: {
            Label(isEnabled ? "Disable" : "Enable",
                  systemImage: isEnabled ? "pause.circle" : "play.circle")
        }

        if !routine.isBuiltIn {
            Divider()
            Button(role: .destructive) {
                Task { try? await appState.deleteRoutine(id: routine.id) }
            } label: {
                Label("Move to Trash", systemImage: "trash")
            }
        }
    }

    // MARK: - Pipeline Horizontal Timeline

    @ViewBuilder
    private var pipelineTimeline: some View {
        let steps = routine.lastExecution?.pipelineSteps ?? []
        let defSteps = routine.pipelineStepDefs
        let stepCount = steps.isEmpty ? max(routine.stepCount, defSteps.count) : steps.count

        if stepCount > 0 {
            HStack(spacing: 2) {
                ForEach(0..<stepCount, id: \.self) { i in
                    let step = i < steps.count ? steps[i] : nil
                    let name = step?.id ?? (i < defSteps.count ? defSteps[i].name : "Step \(i+1)")
                    let color = stepColor(step?.status)

                    RoundedRectangle(cornerRadius: 3)
                        .fill(color)
                        .frame(height: 6)
                        .overlay {
                            if step?.status == .running {
                                RoundedRectangle(cornerRadius: 3)
                                    .fill(color.opacity(0.5))
                                    .phaseAnimator([false, true]) { content, phase in
                                        content.opacity(phase ? 0.4 : 1.0)
                                    }
                            }
                        }
                        .help(name)
                }
            }
        }
    }

    private func stepColor(_ status: RoutineExecution.Status?) -> Color {
        switch status {
        case .completed: Color(red: 0.204, green: 0.780, blue: 0.349)
        case .failed:    Color(red: 1.0, green: 0.220, blue: 0.235)
        case .running:   Color(red: 0.25, green: 0.56, blue: 0.98)
        case .pending:   Color.primary.opacity(0.08)
        case .skipped:   Color.primary.opacity(0.05)
        case .none:      Color.primary.opacity(0.08)
        }
    }

    // MARK: - Running pulse bar

    private var runningBar: some View {
        GeometryReader { geo in
            RoundedRectangle(cornerRadius: 1)
                .fill(Color.statusBlue.opacity(0.4))
                .frame(width: geo.size.width, height: 2)
                .overlay(alignment: .leading) {
                    RoundedRectangle(cornerRadius: 1)
                        .fill(Color.statusBlue)
                        .frame(width: geo.size.width * 0.3, height: 2)
                        .phaseAnimator([false, true]) { content, phase in
                            content.offset(x: phase ? geo.size.width * 0.7 : 0)
                        } animation: { _ in .easeInOut(duration: 1.2).repeatForever(autoreverses: true) }
                }
        }
        .frame(height: 2)
    }

    // MARK: - Helpers

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
