import SwiftUI

struct RoutineDetailView: View {
    @EnvironmentObject var appState: AppState
    @Environment(\.dismiss) var dismiss

    @State private var routine: Routine
    @State private var selectedTab: Int = 0   // 0 = Configuration, 1 = History
    @State private var isSaving = false
    @State private var dryRunState: DryRunState = .idle
    @State private var showDeleteConfirm = false
    @State private var history: [RoutineExecution] = []

    enum DryRunState { case idle, running, sent, failed }

    init(routine: Routine) {
        _routine = State(initialValue: routine)
    }

    var body: some View {
        VStack(spacing: 0) {
            // ── Tab picker ──────────────────────────────────────────────
            Picker("", selection: $selectedTab) {
                Text("Configuration").tag(0)
                Text("History").tag(1)
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .frame(width: 300)
            .padding(.horizontal, Spacing.xl)
            .padding(.top, Spacing.lg)
            .padding(.bottom, Spacing.md)

            Divider()

            // ── Content ─────────────────────────────────────────────────
            if selectedTab == 0 {
                configScrollView
            } else {
                RoutineHistoryTab(routineId: routine.id, history: $history)
            }

            Divider()

            // ── Footer ───────────────────────────────────────────────────
            footerBar
        }
        .frame(minWidth: 600, minHeight: 560)
        .background(Color(.windowBackgroundColor))
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
        .task {
            history = await appState.routineHistory(id: routine.id)
            if routine.isPipeline && routine.pipelineStepDefs.isEmpty {
                routine.pipelineStepDefs = await appState.loadPipelineStepDefs(
                    routineId: routine.id, promptBody: routine.promptBody)
            }
        }
    }

    // MARK: - Config Scroll View

    private var configScrollView: some View {
        ScrollView {
            VStack(spacing: 0) {
                identitySection
                Divider().padding(.horizontal, Spacing.xl)
                scheduleSection
                Divider().padding(.horizontal, Spacing.xl)
                executionSection
                Divider().padding(.horizontal, Spacing.xl)
                if routine.isPipeline {
                    pipelineSection
                } else {
                    promptSection
                }
            }
        }
    }

    // MARK: - Identity Section

    private var identitySection: some View {
        HStack(alignment: .top, spacing: Spacing.md) {
            Image(systemName: "info.circle")
                .foregroundStyle(.secondary)
                .font(.body)
                .padding(.top, 3)

            VStack(alignment: .leading, spacing: Spacing.xs) {
                TextField("Title", text: $routine.title)
                    .font(.title2.bold())
                    .textFieldStyle(.plain)
                Text("\(routine.id).md")
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(.tertiary)
                TextField("Description", text: $routine.description,
                          prompt: Text("Routine description goes here").foregroundStyle(.quaternary))
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .textFieldStyle(.plain)
            }

            Spacer()

            Toggle("", isOn: $routine.enabled)
                .labelsHidden()
                .toggleStyle(.switch)
                .padding(.top, 2)
        }
        .padding(.horizontal, Spacing.xl)
        .padding(.vertical, Spacing.lg)
    }

    // MARK: - Schedule Section

    private let weekdays      = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    private let weekdayLabels = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

    private var scheduleSection: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            Label("Schedule", systemImage: "calendar.badge.clock")
                .font(.subheadline)
                .foregroundStyle(.secondary)

            Text("Select the days of the week the routine will repeat")
                .font(.caption)
                .foregroundStyle(.secondary)

            // Day buttons — equal width, rounded rectangle
            HStack(spacing: 6) {
                ForEach(Array(zip(weekdays, weekdayLabels)), id: \.0) { day, label in
                    let isAll      = routine.schedule.days.contains("*")
                    let isSelected = isAll || routine.schedule.days.contains(day)
                    Button(label) { toggleDay(day) }
                        .font(.caption.bold())
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 8)
                        .background(isSelected ? Color.accentColor : Color.primary.opacity(0.06))
                        .foregroundStyle(isSelected ? Color.white : Color.primary)
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                        .buttonStyle(.plain)
                }
            }

            Text("Time of the day")
                .font(.caption)
                .foregroundStyle(.secondary)

            FlowLayout(spacing: Spacing.sm) {
                AddTimeButton { time in
                    if !routine.schedule.times.contains(time) {
                        routine.schedule.times.append(time)
                        routine.schedule.times.sort()
                    }
                }
                ForEach(routine.schedule.times, id: \.self) { time in
                    TimeChip(time: time) {
                        routine.schedule.times.removeAll { $0 == time }
                    }
                }
            }
        }
        .padding(.horizontal, Spacing.xl)
        .padding(.vertical, Spacing.lg)
    }

    // MARK: - Execution Section

    /// Derived exec type from routine fields
    private var execType: String {
        if routine.isPipeline    { return "pipeline" }
        if routine.minimalContext { return "minimal"  }
        return "default"
    }

    private func setExecType(_ type: String) {
        switch type {
        case "minimal":
            routine.routineType   = "routine"
            routine.minimalContext = true
        case "pipeline":
            routine.routineType   = "pipeline"
            routine.minimalContext = false
        default:
            routine.routineType   = "routine"
            routine.minimalContext = false
        }
    }

    private var execTypeDescription: String {
        switch execType {
        case "minimal":  return "Minimal context to execute the routine. Agent won't read the vault."
        case "pipeline": return "Run a sequence of Claude steps in order."
        default:         return "Full context to execute the routine. Agent will read the vault."
        }
    }

    private func modelDisplayName(_ id: String) -> String {
        switch id {
        case "opus":  return "Opus 4.6"
        case "haiku": return "Claude Haiku"
        default:      return "Claude Sonnet"
        }
    }

    private func modelDescription(_ id: String) -> String {
        switch id {
        case "opus":  return "Most capable for ambitious work"
        case "haiku": return "Fastest and most compact"
        default:      return "Balanced performance and speed"
        }
    }

    private var agentDescription: String {
        guard let id = routine.agentId,
              let agent = appState.agents.first(where: { $0.id == id })
        else { return "Send to the Bot's conversation." }
        return agent.description.isEmpty ? "Custom agent" : agent.description
    }

    private var executionSection: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            Label("Execution", systemImage: "gearshape")
                .font(.subheadline)
                .foregroundStyle(.secondary)

            // Type segmented
            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text("Type").font(.caption).foregroundStyle(.secondary)
                Picker("", selection: Binding(
                    get: { execType },
                    set: { setExecType($0) }
                )) {
                    Text("Default").tag("default")
                    Text("Minimal").tag("minimal")
                    Text("Pipeline").tag("pipeline")
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                Text(execTypeDescription)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            // Model + Agent side by side
            HStack(alignment: .top, spacing: Spacing.lg) {
                // Model column
                VStack(alignment: .leading, spacing: Spacing.xs) {
                    Text("Model").font(.caption).foregroundStyle(.secondary)
                    Picker("", selection: $routine.model) {
                        ForEach(["sonnet", "opus", "haiku"], id: \.self) { m in
                            Text(modelDisplayName(m)).tag(m)
                        }
                    }
                    .frame(maxWidth: .infinity)
                    Text(modelDescription(routine.model))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                // Agent column
                VStack(alignment: .leading, spacing: Spacing.xs) {
                    Text("Agent").font(.caption).foregroundStyle(.secondary)
                    Picker("", selection: $routine.agentId) {
                        Text("🤖 Main (Default)").tag(String?.none)
                        ForEach(appState.agents) { a in
                            Text("\(a.icon) \(a.name)").tag(Optional(a.id))
                        }
                    }
                    .frame(maxWidth: .infinity)
                    Text(agentDescription)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .padding(.horizontal, Spacing.xl)
        .padding(.vertical, Spacing.lg)
    }

    // MARK: - Prompt Section

    private var promptSection: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            Label("Prompt", systemImage: "text.bubble")
                .font(.subheadline)
                .foregroundStyle(.secondary)

            TextEditor(text: $routine.promptBody)
                .font(.system(.callout, design: .default))
                .frame(minHeight: 180)
                .scrollContentBackground(.hidden)
                .padding(Spacing.sm)
                .background(Color.primary.opacity(0.03))
                .clipShape(RoundedRectangle(cornerRadius: 8))
                .overlay(
                    RoundedRectangle(cornerRadius: 8)
                        .strokeBorder(Color.accentColor.opacity(0.35), lineWidth: 1)
                )
        }
        .padding(.horizontal, Spacing.xl)
        .padding(.vertical, Spacing.lg)
    }

    // MARK: - Pipeline Section

    private var pipelineSection: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            Label("Pipeline Steps", systemImage: "arrow.triangle.branch")
                .font(.subheadline)
                .foregroundStyle(.secondary)

            Text("Steps share a workspace. Each reads previous outputs from data/{id}.md.")
                .font(.caption)
                .foregroundStyle(.tertiary)

            ForEach(Array(routine.pipelineStepDefs.enumerated()), id: \.element.id) { idx, _ in
                PipelineStepRow(
                    step: $routine.pipelineStepDefs[idx],
                    index: idx + 1,
                    allStepIds: routine.pipelineStepDefs.enumerated().compactMap { i, s in
                        i != idx && !s.name.isEmpty ? stepSlug(s.name) : nil
                    },
                    onDelete: { routine.pipelineStepDefs.remove(at: idx) }
                )
            }

            Button {
                routine.pipelineStepDefs.append(PipelineStepDef(model: routine.model))
            } label: {
                Label("Add Step", systemImage: "plus.circle")
                    .font(.callout)
            }
            .buttonStyle(.borderless)
            .foregroundStyle(Color.accentColor)
        }
        .padding(.horizontal, Spacing.xl)
        .padding(.vertical, Spacing.lg)
    }

    // MARK: - Footer Bar

    private var footerBar: some View {
        HStack(spacing: Spacing.sm) {
            // Run Now
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
                case .idle:    Label("Run Now",   systemImage: "play.fill")
                case .running: Label("Running…",  systemImage: "arrow.trianglehead.2.clockwise")
                case .sent:    Label("Sent",       systemImage: "checkmark.circle.fill")
                case .failed:  Label("Failed",     systemImage: "xmark.circle.fill")
                }
            }
            .buttonStyle(.bordered)
            .disabled(dryRunState == .running)

            // Delete (hidden for built-in routines like update-check)
            if !routine.isBuiltIn {
                Button(role: .destructive) {
                    showDeleteConfirm = true
                } label: {
                    Label("Delete", systemImage: "trash")
                }
                .buttonStyle(.bordered)
                .tint(Color.statusRed)
            }

            Spacer()

            Button("Cancel") { dismiss() }
                .buttonStyle(.bordered)

            Button(isSaving ? "Saving…" : "Save") {
                isSaving = true
                Task {
                    try? await appState.saveRoutine(routine)
                    isSaving = false
                    dismiss()
                }
            }
            .buttonStyle(.borderedProminent)
            .disabled(isSaving)
        }
        .padding(.horizontal, Spacing.xl)
        .padding(.vertical, Spacing.md)
    }

    // MARK: - Helpers

    private func toggleDay(_ day: String) {
        if routine.schedule.days.contains("*") {
            // Deselect this specific day — switch to all except this
            routine.schedule.days = weekdays.filter { $0 != day }
        } else if routine.schedule.days.contains(day) {
            routine.schedule.days.removeAll { $0 == day }
            if routine.schedule.days.isEmpty { routine.schedule.days = ["*"] }
        } else {
            routine.schedule.days.append(day)
            if Set(routine.schedule.days) == Set(weekdays) {
                routine.schedule.days = ["*"]
            }
        }
    }

    private func stepSlug(_ name: String) -> String {
        name.lowercased()
            .replacingOccurrences(of: " ", with: "-")
            .filter { $0.isLetter || $0.isNumber || $0 == "-" }
    }
}

// MARK: - Time Chip

struct TimeChip: View {
    var time: String
    var onRemove: () -> Void

    var body: some View {
        HStack(spacing: Spacing.xs) {
            Text(time).font(.caption.monospacedDigit())
            Button(action: onRemove) {
                Image(systemName: "xmark.circle.fill").font(.caption)
            }
            .buttonStyle(.plain).foregroundStyle(.secondary)
        }
        .padding(.horizontal, 10).padding(.vertical, 5)
        .background(Color.primary.opacity(0.06))
        .clipShape(Capsule())
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
        Button { showPicker = true } label: {
            HStack(spacing: 4) {
                Image(systemName: "plus").font(.caption.bold())
                Text("Add Time").font(.caption.bold())
            }
            .padding(.horizontal, 10).padding(.vertical, 5)
            .foregroundStyle(Color.accentColor)
            .overlay(Capsule().strokeBorder(Color.accentColor.opacity(0.5), lineWidth: 1))
        }
        .buttonStyle(.plain)
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
        case .failed:    return .statusRed
        case .running:   return .statusBlue
        case .pending, .skipped: return Color(.secondaryLabelColor)
        }
    }

    var body: some View {
        GlassCard(padding: Spacing.md) {
            VStack(alignment: .leading, spacing: Spacing.sm) {
                HStack(spacing: Spacing.sm) {
                    Image(systemName: execution.status.symbol)
                        .font(.callout)
                        .foregroundStyle(statusColor)
                    Text("\(execution.date) at \(execution.timeSlot)")
                        .font(.callout.monospacedDigit())
                    Spacer()
                    if let duration = execution.duration {
                        Text(duration)
                            .font(.caption.monospacedDigit())
                            .foregroundStyle(.tertiary)
                    }
                    Text(execution.status.label)
                        .font(.caption.bold())
                        .foregroundStyle(statusColor)
                }
                if let error = execution.error {
                    Text(error)
                        .font(.caption)
                        .foregroundStyle(Color.statusRed)
                        .lineLimit(3)
                        .padding(Spacing.sm)
                        .background(Color.statusRed.opacity(0.08))
                        .clipShape(RoundedRectangle(cornerRadius: 6))
                }
            }
        }
        .padding(.vertical, 2)
    }
}

// MARK: - Pipeline Steps Tab (last execution status)

struct PipelineStepsTab: View {
    var routine: Routine

    private var steps: [StepExecution] {
        routine.lastExecution?.pipelineSteps ?? []
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                pipelineSummaryCard
                if !steps.isEmpty { stepsListCard } else { noStepsCard }
            }
            .padding(20)
        }
    }

    private var pipelineSummaryCard: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Image(systemName: "arrow.triangle.branch")
                        .font(.title3).foregroundStyle(Color.statusBlue)
                    Text("Pipeline").font(.headline)
                    Spacer()
                    Text("\(routine.stepCount) steps")
                        .font(.caption).foregroundStyle(.secondary)
                }
                if !steps.isEmpty {
                    let completed = steps.filter { $0.status == .completed }.count
                    let failed    = steps.filter { $0.status == .failed }.count
                    let running   = steps.filter { $0.status == .running }.count
                    let skipped   = steps.filter { $0.status == .skipped }.count

                    HStack(spacing: 16) {
                        StepCountBadge(count: completed, label: "Completed", color: .statusGreen)
                        if failed  > 0 { StepCountBadge(count: failed,  label: "Failed",  color: .statusRed)  }
                        if running > 0 { StepCountBadge(count: running, label: "Running", color: .statusBlue) }
                        if skipped > 0 { StepCountBadge(count: skipped, label: "Skipped", color: .secondary)  }
                    }
                    ProgressView(value: Double(completed) / Double(max(steps.count, 1)))
                        .tint(failed > 0 ? Color.statusRed : Color.statusGreen)
                }
            }
        }
    }

    private var stepsListCard: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 0) {
                Text("Step Execution")
                    .font(.caption.bold()).foregroundStyle(.secondary)
                    .padding(.bottom, 8)
                ForEach(Array(steps.enumerated()), id: \.element.id) { idx, step in
                    StepRow(step: step, index: idx + 1, total: steps.count)
                    if idx < steps.count - 1 { Divider().padding(.vertical, 4) }
                }
            }
        }
    }

    private var noStepsCard: some View {
        GlassCard {
            HStack {
                Image(systemName: "info.circle").foregroundStyle(.secondary)
                Text("No execution data yet. Run the pipeline to see step details.")
                    .font(.caption).foregroundStyle(.secondary)
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
        case .skipped, .pending: return .secondary
        }
    }

    var body: some View {
        HStack(spacing: 10) {
            Text("\(index)")
                .font(.caption2.monospacedDigit().bold())
                .foregroundStyle(.secondary).frame(width: 18)
            Group {
                if step.status == .running {
                    ProgressView().scaleEffect(0.5)
                } else {
                    Image(systemName: step.status.symbol).foregroundStyle(statusColor)
                }
            }
            .frame(width: 16, height: 16)
            VStack(alignment: .leading, spacing: 2) {
                Text(step.id).font(.callout)
                if let err = step.error {
                    Text(err).font(.caption2).foregroundStyle(Color.statusRed).lineLimit(1)
                }
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 2) {
                if let dur = step.duration {
                    Text(dur).font(.caption2.monospacedDigit()).foregroundStyle(.secondary)
                }
                if step.attempt > 1 {
                    Text("attempt \(step.attempt)").font(.caption2).foregroundStyle(.tertiary)
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
            Text("\(count)").font(.caption.bold().monospacedDigit()).foregroundStyle(color)
            Text(label).font(.caption2).foregroundStyle(.secondary)
        }
    }
}
