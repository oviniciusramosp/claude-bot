import SwiftUI

struct RoutineDetailView: View {
    @EnvironmentObject var appState: AppState
    @Environment(\.dismiss) var dismiss

    @State private var routine: Routine
    @State private var selectedTab = 0
    @State private var isSaving = false
    @State private var dryRunState: DryRunState = .idle
    @State private var showDeleteConfirm = false

    enum DryRunState { case idle, running, sent, failed }
    @State private var history: [RoutineExecution] = []

    init(routine: Routine) {
        _routine = State(initialValue: routine)
    }

    var body: some View {
        NavigationStack {
            TabView(selection: $selectedTab) {
                RoutineConfigTab(routine: $routine)
                    .tabItem { Label("Config", systemImage: "slider.horizontal.3") }
                    .tag(0)

                if routine.isPipeline {
                    PipelineStepsTab(routine: routine)
                        .tabItem { Label("Steps", systemImage: "arrow.triangle.branch") }
                        .tag(2)
                }

                RoutineHistoryTab(routineId: routine.id, history: $history)
                    .tabItem { Label("History", systemImage: "clock.arrow.circlepath") }
                    .tag(1)
            }
            .navigationTitle(routine.title)
            .navigationSubtitle(routine.id)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        isSaving = true
                        Task {
                            try? await appState.saveRoutine(routine)
                            isSaving = false
                            dismiss()
                        }
                    }
                    .disabled(isSaving)
                }
                ToolbarItem(placement: .automatic) {
                    Button {
                        dryRunState = .running
                        Task {
                            do {
                                let result = try await appState.dryRunRoutine(routine)
                                dryRunState = result?.status == .failed ? .failed : .sent
                                history = await appState.routineHistory(id: routine.id)
                            } catch {
                                dryRunState = .failed
                            }
                            try? await Task.sleep(nanoseconds: 2_500_000_000)
                            dryRunState = .idle
                        }
                    } label: {
                        switch dryRunState {
                        case .idle:
                            Label("Dry Run", systemImage: "play.circle")
                        case .running:
                            Label("Enviando…", systemImage: "arrow.trianglehead.2.clockwise")
                                .foregroundStyle(.secondary)
                        case .sent:
                            Label("Enviado", systemImage: "checkmark.circle.fill")
                                .foregroundStyle(Color.statusGreen)
                        case .failed:
                            Label("Falhou", systemImage: "xmark.circle.fill")
                                .foregroundStyle(Color.statusRed)
                        }
                    }
                    .disabled(dryRunState == .running)
                }
                ToolbarItem(placement: .destructiveAction) {
                    Button(role: .destructive) { showDeleteConfirm = true } label: {
                        Label("Move to Trash", systemImage: "trash")
                    }
                }
            }
            .confirmationDialog("Move to Trash?", isPresented: $showDeleteConfirm, titleVisibility: .visible) {
                Button("Move to Trash", role: .destructive) {
                    Task {
                        try? await appState.deleteRoutine(id: routine.id)
                        dismiss()
                    }
                }
            } message: {
                Text("The routine will be moved to Trash. You can restore from Finder.")
            }
        }
        .frame(minWidth: 620, minHeight: 520)
        .task {
            history = await appState.routineHistory(id: routine.id)
            // Load pipeline step definitions for editing
            if routine.isPipeline && routine.pipelineStepDefs.isEmpty {
                routine.pipelineStepDefs = await appState.loadPipelineStepDefs(
                    routineId: routine.id, promptBody: routine.promptBody)
            }
        }
    }
}

// MARK: - Config Tab

struct RoutineConfigTab: View {
    @EnvironmentObject var appState: AppState
    @Binding var routine: Routine

    private let weekdays = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    private let weekdayLabels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                titleCard
                scheduleCard
                if routine.isPipeline {
                    PipelineStepEditorCard(steps: $routine.pipelineStepDefs, defaultModel: routine.model)
                } else {
                    promptCard
                }
            }
            .padding(20)
        }
    }

    private var titleCard: some View {
        GlassCard {
            VStack(spacing: 12) {
                TextField("Title", text: $routine.title)
                    .font(.title3.bold())
                    .textFieldStyle(.plain)
                TextField("Description", text: $routine.description)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .textFieldStyle(.plain)
            }
        }
    }

    private var scheduleCard: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 12) {
                scheduleHeader
                dayPicker
                timePicker
                Divider()
                modelPicker
                agentPicker
                contextToggle
            }
        }
    }

    private var contextToggle: some View {
        HStack {
            Text("Minimal Context").font(.caption).foregroundStyle(.secondary)
            Spacer()
            Toggle("", isOn: $routine.minimalContext)
                .labelsHidden()
                .toggleStyle(.switch)
        }
        .help("When enabled, the routine runs with only CLAUDE.md — skips vault instructions (Journal, Tooling, etc.)")
    }

    private var scheduleHeader: some View {
        HStack {
            Text("Schedule").font(.headline)
            Spacer()
            Toggle("Pipeline", isOn: Binding(
                get: { routine.isPipeline },
                set: { newVal in routine.routineType = newVal ? "pipeline" : "routine" }
            ))
            .toggleStyle(.switch)
            .font(.caption)
            Toggle("Enabled", isOn: $routine.enabled)
                .labelsHidden()
                .toggleStyle(.switch)
        }
    }

    private var dayPicker: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Days").font(.caption).foregroundStyle(.secondary)
            HStack(spacing: 6) {
                let isAll = routine.schedule.days.contains("*")
                Button("All") { routine.schedule.days = ["*"] }
                    .font(.caption2.bold())
                    .padding(.horizontal, 8).padding(.vertical, 4)
                    .background(isAll ? Color.statusBlue.opacity(0.2) : Color.primary.opacity(0.06))
                    .foregroundStyle(isAll ? Color.statusBlue : Color.secondary)
                    .clipShape(Capsule())

                ForEach(Array(zip(weekdays, weekdayLabels)), id: \.0) { day, label in
                    let isSelected = routine.schedule.days.contains(day)
                    let isAll2 = routine.schedule.days.contains("*")
                    Button(label) { toggleDay(day) }
                        .font(.caption2.bold())
                        .padding(.horizontal, 8).padding(.vertical, 4)
                        .background(isSelected && !isAll2 ? Color.statusBlue.opacity(0.2) : Color.primary.opacity(0.06))
                        .foregroundStyle(isSelected && !isAll2 ? Color.statusBlue : Color.secondary)
                        .clipShape(Capsule())
                        .disabled(isAll2)
                }
            }
        }
    }

    private var timePicker: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Times (24h)").font(.caption).foregroundStyle(.secondary)
            FlowLayout(spacing: 6) {
                ForEach(routine.schedule.times, id: \.self) { time in
                    TimeChip(time: time) {
                        routine.schedule.times.removeAll { $0 == time }
                    }
                }
                AddTimeButton { time in
                    if !routine.schedule.times.contains(time) {
                        routine.schedule.times.append(time)
                        routine.schedule.times.sort()
                    }
                }
            }
        }
    }

    private var modelPicker: some View {
        HStack {
            Text("Model").font(.caption).foregroundStyle(.secondary)
            Spacer()
            Picker("", selection: $routine.model) {
                ForEach(["sonnet", "opus", "haiku"], id: \.self) { m in
                    Text(m.capitalized).tag(m)
                }
            }
            .pickerStyle(.segmented).frame(width: 200)
        }
    }

    private var agentPicker: some View {
        HStack {
            Text("Agent").font(.caption).foregroundStyle(.secondary)
            Spacer()
            Picker("", selection: $routine.agentId) {
                Text("Main (default)").tag(String?.none)
                ForEach(appState.agents) { a in
                    Text("\(a.icon) \(a.name)").tag(Optional(a.id))
                }
            }
            .frame(maxWidth: 200)
        }
    }

    private var promptCard: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 8) {
                Text("Prompt").font(.caption).foregroundStyle(.secondary)
                TextEditor(text: $routine.promptBody)
                    .font(.system(.callout, design: .default))
                    .frame(minHeight: 150)
                    .scrollContentBackground(.hidden)
                    .background(Color.primary.opacity(0.03))
                    .clipShape(RoundedRectangle(cornerRadius: 8))
            }
        }
    }

    private func toggleDay(_ day: String) {
        if routine.schedule.days.contains("*") {
            routine.schedule.days = [day]
        } else if routine.schedule.days.contains(day) {
            routine.schedule.days.removeAll { $0 == day }
            if routine.schedule.days.isEmpty { routine.schedule.days = ["*"] }
        } else {
            routine.schedule.days.append(day)
        }
    }
}

// MARK: - Time Chip

struct TimeChip: View {
    var time: String
    var onRemove: () -> Void

    var body: some View {
        HStack(spacing: 4) {
            Text(time).font(.caption.monospacedDigit())
            Button(action: onRemove) {
                Image(systemName: "xmark.circle.fill").font(.caption2)
            }
            .buttonStyle(.plain).foregroundStyle(.secondary)
        }
        .padding(.horizontal, 8).padding(.vertical, 4)
        .background(Color.primary.opacity(0.06))
        .clipShape(Capsule())
    }
}

// MARK: - History Tab

struct RoutineHistoryTab: View {
    var routineId: String
    @Binding var history: [RoutineExecution]

    var body: some View {
        Group {
            if history.isEmpty {
                EmptyStateView(
                    symbol: "clock.arrow.circlepath",
                    title: "No History",
                    subtitle: "Execution history will appear here after the routine runs."
                )
            } else {
                List(history) { exec in
                    RoutineHistoryRow(execution: exec)
                        .listRowBackground(Color.clear)
                        .listRowSeparator(.hidden)
                }
                .listStyle(.plain)
                .scrollContentBackground(.hidden)
            }
        }
    }
}

struct RoutineHistoryRow: View {
    var execution: RoutineExecution

    private var statusColor: Color {
        switch execution.status {
        case .completed: return .statusGreen
        case .failed: return .statusRed
        case .running: return .statusBlue
        case .pending, .skipped: return Color(.secondaryLabelColor)
        }
    }

    var body: some View {
        GlassCard(padding: 10) {
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Image(systemName: execution.status.symbol)
                        .foregroundStyle(statusColor)
                    Text("\(execution.date) at \(execution.timeSlot)")
                        .font(.caption.monospacedDigit())
                    Spacer()
                    if let duration = execution.duration {
                        Text(duration)
                            .font(.caption2.monospacedDigit())
                            .foregroundStyle(.tertiary)
                    }
                    Text(execution.status.label)
                        .font(.caption2.bold())
                        .foregroundStyle(statusColor)
                }
                if let error = execution.error {
                    Text(error)
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(Color.statusRed)
                        .lineLimit(3)
                        .padding(6)
                        .background(Color.statusRed.opacity(0.08))
                        .clipShape(RoundedRectangle(cornerRadius: 6))
                }
            }
        }
        .padding(.vertical, 2)
    }
}

// MARK: - Add Time Button

struct AddTimeButton: View {
    var onAdd: (String) -> Void
    @State private var showPicker = false
    @State private var input = ""
    @FocusState private var focused: Bool

    private var isValid: Bool {
        let parts = input.split(separator: ":", maxSplits: 1)
        guard parts.count == 2,
              let h = Int(parts[0]), let m = Int(parts[1]),
              (0..<24).contains(h), (0..<60).contains(m)
        else { return false }
        return true
    }

    private func commit() {
        guard isValid else { return }
        let parts = input.split(separator: ":", maxSplits: 1)
        let formatted = String(format: "%02d:%02d", Int(parts[0])!, Int(parts[1])!)
        onAdd(formatted)
        input = ""
        showPicker = false
    }

    var body: some View {
        Button {
            showPicker = true
        } label: {
            Label("Add time", systemImage: "plus.circle")
                .font(.caption2)
        }
        .buttonStyle(.plain)
        .foregroundStyle(Color.statusBlue)
        .popover(isPresented: $showPicker) {
            VStack(alignment: .leading, spacing: 10) {
                Text("Add Time").font(.headline)
                HStack(spacing: 8) {
                    TextField("HH:MM", text: $input)
                        .textFieldStyle(.roundedBorder)
                        .frame(width: 80)
                        .font(.system(.body, design: .monospaced))
                        .focused($focused)
                        .onSubmit { commit() }
                    Button("Add") { commit() }
                        .buttonStyle(.borderedProminent)
                        .disabled(!isValid)
                }
                if !input.isEmpty && !isValid {
                    Text("Use formato HH:MM (ex: 09:30)")
                        .font(.caption2)
                        .foregroundStyle(Color.statusRed)
                }
            }
            .padding()
            .onAppear { input = ""; focused = true }
        }
    }
}

// MARK: - Flow Layout

struct FlowLayout: Layout {
    var spacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? 0
        var height: CGFloat = 0
        var rowWidth: CGFloat = 0
        var rowHeight: CGFloat = 0
        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if rowWidth + size.width > width && rowWidth > 0 {
                height += rowHeight + spacing
                rowWidth = 0; rowHeight = 0
            }
            rowWidth += size.width + spacing
            rowHeight = max(rowHeight, size.height)
        }
        return CGSize(width: width, height: height + rowHeight)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX; var y = bounds.minY; var rowHeight: CGFloat = 0
        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x + size.width > bounds.maxX && x > bounds.minX {
                y += rowHeight + spacing; x = bounds.minX; rowHeight = 0
            }
            subview.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
        }
    }
}

// MARK: - Pipeline Steps Tab

struct PipelineStepsTab: View {
    var routine: Routine

    private var steps: [StepExecution] {
        routine.lastExecution?.pipelineSteps ?? []
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                pipelineSummaryCard
                if !steps.isEmpty {
                    stepsListCard
                } else {
                    noStepsCard
                }
            }
            .padding(20)
        }
    }

    private var pipelineSummaryCard: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Image(systemName: "arrow.triangle.branch")
                        .font(.title3)
                        .foregroundStyle(Color.statusBlue)
                    Text("Pipeline")
                        .font(.headline)
                    Spacer()
                    Text("\(routine.stepCount) steps")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                if !steps.isEmpty {
                    let completed = steps.filter { $0.status == .completed }.count
                    let failed = steps.filter { $0.status == .failed }.count
                    let running = steps.filter { $0.status == .running }.count
                    let skipped = steps.filter { $0.status == .skipped }.count

                    HStack(spacing: 16) {
                        StepCountBadge(count: completed, label: "Completed", color: .statusGreen)
                        if failed > 0 { StepCountBadge(count: failed, label: "Failed", color: .statusRed) }
                        if running > 0 { StepCountBadge(count: running, label: "Running", color: .statusBlue) }
                        if skipped > 0 { StepCountBadge(count: skipped, label: "Skipped", color: .secondary) }
                    }

                    // Progress bar
                    let progress = Double(completed) / Double(max(steps.count, 1))
                    ProgressView(value: progress)
                        .tint(failed > 0 ? Color.statusRed : Color.statusGreen)
                }
            }
        }
    }

    private var stepsListCard: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 0) {
                Text("Step Execution")
                    .font(.caption.bold())
                    .foregroundStyle(.secondary)
                    .padding(.bottom, 8)

                ForEach(Array(steps.enumerated()), id: \.element.id) { idx, step in
                    StepRow(step: step, index: idx + 1, total: steps.count)
                    if idx < steps.count - 1 {
                        Divider().padding(.vertical, 4)
                    }
                }
            }
        }
    }

    private var noStepsCard: some View {
        GlassCard {
            HStack {
                Image(systemName: "info.circle")
                    .foregroundStyle(.secondary)
                Text("No execution data yet. Run the pipeline to see step details.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }
}

struct StepRow: View {
    var step: StepExecution
    var index: Int
    var total: Int

    private var statusColor: Color {
        switch step.status {
        case .completed: return .statusGreen
        case .failed:    return .statusRed
        case .running:   return .statusBlue
        case .skipped:   return .secondary
        case .pending:   return .secondary
        }
    }

    var body: some View {
        HStack(spacing: 10) {
            // Step number
            Text("\(index)")
                .font(.caption2.monospacedDigit().bold())
                .foregroundStyle(.secondary)
                .frame(width: 18)

            // Status icon
            Group {
                if step.status == .running {
                    ProgressView().scaleEffect(0.5)
                } else {
                    Image(systemName: step.status.symbol)
                        .foregroundStyle(statusColor)
                }
            }
            .frame(width: 16, height: 16)

            // Step info
            VStack(alignment: .leading, spacing: 2) {
                Text(step.id)
                    .font(.callout)
                if let err = step.error {
                    Text(err)
                        .font(.caption2)
                        .foregroundStyle(Color.statusRed)
                        .lineLimit(1)
                }
            }

            Spacer()

            // Duration + attempt
            VStack(alignment: .trailing, spacing: 2) {
                if let dur = step.duration {
                    Text(dur)
                        .font(.caption2.monospacedDigit())
                        .foregroundStyle(.secondary)
                }
                if step.attempt > 1 {
                    Text("attempt \(step.attempt)")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
            }
        }
        .padding(.vertical, 2)
    }
}

struct StepCountBadge: View {
    var count: Int
    var label: String
    var color: Color

    var body: some View {
        HStack(spacing: 4) {
            Text("\(count)")
                .font(.caption.bold().monospacedDigit())
                .foregroundStyle(color)
            Text(label)
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
    }
}
