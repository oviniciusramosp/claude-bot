import SwiftUI

struct RoutineListView: View {
    @EnvironmentObject var appState: AppState
    @State private var showCreateSheet = false
    @State private var selectedRoutine: Routine? = nil

    private func sorted(_ routines: [Routine]) -> [Routine] {
        routines.sorted { ($0.schedule.times.first ?? "99:99") < ($1.schedule.times.first ?? "99:99") }
    }

    private var botRoutines: [Routine] { sorted(appState.routines.filter { $0.isBuiltIn }) }
    private var myRoutines: [Routine] { sorted(appState.routines.filter { !$0.isBuiltIn }) }

    var body: some View {
        ScrollView {
            VStack(spacing: Spacing.xl) {
                if appState.routines.isEmpty {
                    EmptyStateView(
                        symbol: "clock.arrow.2.circlepath",
                        title: "No Routines",
                        subtitle: "Create a routine to schedule automated tasks."
                    )
                } else {
                    if !botRoutines.isEmpty {
                        routineSection(title: "Bot Routines", routines: botRoutines)
                    }
                    if !myRoutines.isEmpty {
                        routineSection(title: "My Routines", routines: myRoutines)
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

    @ViewBuilder
    private func routineSection(title: String, routines: [Routine]) -> some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            Text(title)
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(.secondary)
                .textCase(.uppercase)
                .tracking(0.5)
                .padding(.horizontal, Spacing.xs)
            VStack(spacing: Spacing.lg) {
                ForEach(routines) { routine in
                    RoutineRow(routine: routine, onTap: { selectedRoutine = routine })
                }
            }
        }
    }
}

// MARK: - Routine Row

struct RoutineRow: View {
    var routine: Routine
    var onTap: () -> Void = {}
    @EnvironmentObject var appState: AppState
    @State private var isEnabled: Bool
    @State private var isDryRunning = false
    @State private var isStopping = false
    @State private var isExpanded = false

    init(routine: Routine, onTap: @escaping () -> Void = {}) {
        self.routine = routine
        self.onTap = onTap
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

    /// Agent emoji + name — always shows something (Main if no specific agent)
    private var agentDisplay: (icon: String, name: String) {
        if let id = routine.agentId,
           let agent = appState.agents.first(where: { $0.id == id }) {
            return (agent.icon, agent.name)
        }
        return (appState.mainAgent.icon, appState.mainAgent.name)
    }

    var body: some View {
        GlassCard(padding: Spacing.xl) {
            VStack(alignment: .leading, spacing: Spacing.md) {
                // Row 1: Status + Title + Model/Pipeline badge + Switch
                HStack(spacing: Spacing.md) {
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

                    if routine.isPipeline {
                        HStack(spacing: 4) {
                            Image(systemName: "checklist")
                                .font(.system(size: 10))
                            Text("\(routine.stepCount) steps")
                                .font(.system(size: 10))
                        }
                        .foregroundStyle(Color.statusBlue)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 3)
                        .background(Color.statusBlue.opacity(0.15))
                        .clipShape(Capsule())
                    } else {
                        ModelBadge(model: routine.model)
                    }

                    Button { onTap() } label: {
                        Image(systemName: "slider.horizontal.3")
                            .font(.system(size: 12))
                            .foregroundStyle(.secondary)
                    }
                    .buttonStyle(.plain)
                    .help("Edit")

                    Toggle("", isOn: $isEnabled)
                        .labelsHidden()
                        .toggleStyle(.switch)
                        .onChange(of: isEnabled) { _, newValue in
                            var updated = routine
                            updated.enabled = newValue
                            Task { try? await appState.saveRoutine(updated) }
                        }
                }

                // Row 2: Schedule + Agent + Last execution info
                HStack(spacing: Spacing.sm) {
                    Text(routine.schedule.times.joined(separator: ", "))
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(Color(red: 0.447, green: 0.447, blue: 0.447))

                    Text("·").foregroundStyle(.quaternary)

                    Text(humanReadableDays(routine.schedule.days))
                        .font(.system(size: 10))
                        .foregroundStyle(Color(red: 0.447, green: 0.447, blue: 0.447))

                    Text("·").foregroundStyle(.quaternary)

                    Text("\(agentDisplay.icon) \(agentDisplay.name)")
                        .font(.system(size: 10))
                        .foregroundStyle(Color(red: 0.447, green: 0.447, blue: 0.447))

                    Spacer()

                    if let exec = routine.lastExecution {
                        if exec.status == .running, let dur = exec.liveDuration {
                            Text("Running \(dur)")
                                .font(.system(size: 10, weight: .medium))
                                .foregroundStyle(Color(red: 0.25, green: 0.56, blue: 0.98))
                        } else if let dur = exec.liveDuration {
                            Text("\(exec.timeLabel) · \(dur)")
                                .font(.system(size: 10, design: .monospaced))
                                .foregroundStyle(.tertiary)
                        } else {
                            Text(exec.timeLabel)
                                .font(.system(size: 10, design: .monospaced))
                                .foregroundStyle(.tertiary)
                        }
                    } else {
                        Text(routine.nextExecutionDescription)
                            .font(.system(size: 10))
                            .foregroundStyle(.tertiary)
                    }
                }

                // Error detail (if last execution failed)
                if let exec = routine.lastExecution, exec.status == .failed {
                    let errorDetail = buildErrorDetail(exec)
                    if !errorDetail.isEmpty {
                        Text(errorDetail)
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundStyle(Color(red: 1.0, green: 0.220, blue: 0.235))
                            .lineLimit(6)
                            .textSelection(.enabled)
                            .padding(.horizontal, Spacing.sm)
                            .padding(.vertical, 4)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(Color(red: 1.0, green: 0.220, blue: 0.235).opacity(0.08))
                            .clipShape(RoundedRectangle(cornerRadius: 6))
                            .contextMenu {
                                Button("Copy Error") {
                                    NSPasteboard.general.clearContents()
                                    NSPasteboard.general.setString(errorDetail, forType: .string)
                                }
                            }
                    }
                }

                // Pipeline: expanded steps or compact bar
                if routine.isPipeline {
                    if isExpanded {
                        pipelineExpandedSteps
                    } else if routine.lastExecution?.status != .failed {
                        pipelineTimeline
                    }

                    // Chevron toggle
                    Button {
                        withAnimation(.easeInOut(duration: 0.2)) { isExpanded.toggle() }
                    } label: {
                        Image(systemName: isExpanded ? "chevron.up" : "chevron.down")
                            .font(.system(size: 9, weight: .semibold))
                            .foregroundStyle(.tertiary)
                            .frame(maxWidth: .infinity)
                            .frame(height: 4)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
            }
        } // GlassCard
        .contextMenu { contextMenuItems }
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

    // MARK: - Pipeline Expanded Steps

    @ViewBuilder
    private var pipelineExpandedSteps: some View {
        let steps = routine.lastExecution?.pipelineSteps ?? []
        let defSteps = routine.pipelineStepDefs

        VStack(spacing: 0) {
            ForEach(0..<max(steps.count, defSteps.count, routine.stepCount), id: \.self) { i in
                let step = i < steps.count ? steps[i] : nil
                let defName = i < defSteps.count ? defSteps[i].name : nil
                let name = defName ?? step?.id ?? "Step \(i + 1)"
                let status = step?.status
                let color = stepColor(status)
                let icon: String = {
                    switch status {
                    case .completed: return "checkmark.circle.fill"
                    case .failed: return "xmark.circle.fill"
                    case .running: return "arrow.trianglehead.2.clockwise"
                    case .skipped: return "forward.fill"
                    default: return "circle"
                    }
                }()

                HStack(spacing: Spacing.sm) {
                    // Step number
                    Text("\(i + 1)")
                        .font(.system(size: 9, weight: .bold, design: .monospaced))
                        .foregroundStyle(.tertiary)
                        .frame(width: 14)

                    // Status icon (spinner for running)
                    if status == .running {
                        ProgressView()
                            .scaleEffect(0.45)
                            .frame(width: 14, height: 14)
                    } else {
                        Image(systemName: icon)
                            .font(.system(size: 10))
                            .foregroundStyle(color)
                            .frame(width: 14)
                    }

                    // Step name
                    Text(name)
                        .font(.system(size: 11))
                        .foregroundStyle(status == nil || status == .pending ? .tertiary : .primary)
                        .lineLimit(1)

                    Spacer()

                    // Duration
                    if let step, let dur = step.liveDuration {
                        Text(dur)
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundStyle(status == .running
                                ? Color(red: 0.25, green: 0.56, blue: 0.98)
                                : Color(red: 0.447, green: 0.447, blue: 0.447))
                    }

                    // Model + timeout badges (from defs)
                    if i < defSteps.count {
                        let def = defSteps[i]
                        HStack(spacing: 3) {
                            Text(def.model)
                                .font(.system(size: 8, weight: .medium))
                            Text("·")
                                .font(.system(size: 8))
                            Text("\(def.timeout / 60)m")
                                .font(.system(size: 8, design: .monospaced))
                        }
                        .foregroundStyle(.tertiary)
                        .padding(.horizontal, 5)
                        .padding(.vertical, 1)
                        .background(Color.primary.opacity(0.04))
                        .clipShape(Capsule())
                    }
                }
                .padding(.vertical, 4)

                // Error detail for failed steps
                if let step, step.status == .failed, let err = step.error {
                    Text(err)
                        .font(.system(size: 9, design: .monospaced))
                        .foregroundStyle(Color(red: 1.0, green: 0.220, blue: 0.235))
                        .lineLimit(2)
                        .textSelection(.enabled)
                        .padding(.horizontal, Spacing.sm)
                        .padding(.vertical, 3)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color(red: 1.0, green: 0.220, blue: 0.235).opacity(0.06))
                        .clipShape(RoundedRectangle(cornerRadius: 4))
                        .contextMenu {
                            Button("Copy Error") {
                                NSPasteboard.general.clearContents()
                                NSPasteboard.general.setString(err, forType: .string)
                            }
                        }
                }

                if i < max(steps.count, defSteps.count, routine.stepCount) - 1 {
                    Divider().padding(.leading, 30)
                }
            }
        }
        .padding(.vertical, 2)
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

    private func buildErrorDetail(_ exec: RoutineExecution) -> String {
        // For pipelines: show per-step errors, not just "Steps failed: x"
        if exec.isPipeline && !exec.pipelineSteps.isEmpty {
            let failedSteps = exec.pipelineSteps.filter { $0.status == .failed && $0.error != nil }
            if !failedSteps.isEmpty {
                return failedSteps.map { step in
                    "\(step.id): \(step.error ?? "unknown error")"
                }.joined(separator: "\n")
            }
        }
        return exec.error ?? ""
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
