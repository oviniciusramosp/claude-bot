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

    // Schedule UI state (separate from routine model to drive the pickers)
    @State private var scheduleMode: String   // "weekdays" | "monthdays" | "interval"
    @State private var intervalValue: String
    @State private var intervalUnit: String

    enum DryRunState { case idle, running, sent, failed }

    init(routine: Routine) {
        _routine = State(initialValue: routine)
        let mode: String
        if routine.schedule.isIntervalMode {
            mode = "interval"
        } else if !routine.schedule.monthdays.isEmpty {
            mode = "monthdays"
        } else {
            mode = "weekdays"
        }
        _scheduleMode = State(initialValue: mode)
        if let iv = routine.schedule.interval, !iv.isEmpty, let last = iv.last {
            let unit = String(last)
            _intervalValue = State(initialValue: String(iv.dropLast()))
            _intervalUnit = State(initialValue: ["m","h","d","w"].contains(unit) ? unit : "h")
        } else {
            _intervalValue = State(initialValue: "1")
            _intervalUnit = State(initialValue: "h")
        }
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
        .frame(minWidth: 720, minHeight: 560)
        .background(Color(.windowBackgroundColor))
        .confirmationDialog("Move to Trash?", isPresented: $showDeleteConfirm, titleVisibility: .visible) {
            Button("Move to Trash", role: .destructive) {
                Task {
                    // Only dismiss on full success — if the delete failed,
                    // leave the sheet open so the user can see the alert
                    // bound to `appState.lastError` below and retry.
                    let ok = await appState.deleteRoutine(routine)
                    if ok { dismiss() }
                }
            }
        } message: {
            Text("The routine will be moved to Trash. You can restore from Finder.")
        }
        .alert(
            "Erro",
            isPresented: Binding(
                get: { appState.lastError != nil },
                set: { if !$0 { appState.lastError = nil } }
            )
        ) {
            Button("OK") { appState.lastError = nil }
        } message: {
            Text(appState.lastError ?? "")
        }
        .task {
            history = await appState.routineHistory(id: routine.id)
            if routine.isPipeline && routine.pipelineStepDefs.isEmpty {
                routine.pipelineStepDefs = await appState.loadPipelineStepDefs(
                    routineId: routine.id,
                    promptBody: routine.promptBody,
                    ownerAgentId: routine.ownerAgentId)
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
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "info.circle.fill")
                .font(.system(size: 17))
                .foregroundStyle(Color(white: 0.75))
                .frame(width: 22)

            VStack(alignment: .leading, spacing: 10) {
                VStack(alignment: .leading, spacing: 0) {
                    TextField("Title", text: $routine.title)
                        .font(.system(size: 17, weight: .bold))
                        .textFieldStyle(.plain)
                    Text("\(routine.id).md")
                        .font(.system(size: 10))
                        .foregroundStyle(Color(white: 0.45))
                }
                TextField("Description", text: $routine.description,
                          prompt: Text("Routine description goes here").foregroundStyle(.quaternary))
                    .font(.system(size: 13))
                    .foregroundStyle(Color(white: 0.45))
                    .textFieldStyle(.plain)
            }

            Spacer()

            Toggle("", isOn: $routine.enabled)
                .labelsHidden()
                .toggleStyle(.switch)
                .tint(.green)
        }
        .padding(.horizontal, 20)
        .padding(.trailing, 12)
        .padding(.vertical, 16)
    }

    // MARK: - Schedule Section

    private let weekdays      = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    private let weekdayLabels = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

    private let intervalUnits: [(String, String)] = [
        ("m", "minutes"), ("h", "hours"), ("d", "days"), ("w", "weeks")
    ]

    private var scheduleSection: some View {
        detailFormSection(icon: "calendar", title: "Schedule") {
            CustomSegmentedControl(
                selection: $scheduleMode,
                options: [
                    ("weekdays", "Days of the week"),
                    ("monthdays", "Days of the month"),
                    ("interval", "Fixed interval"),
                ]
            )

            switch scheduleMode {
            case "weekdays":
                weekdaysPickerView
                timesPickerView
            case "monthdays":
                monthdaysPickerView
                timesPickerView
            case "interval":
                intervalPickerView
            default:
                EmptyView()
            }
        }
    }

    private var weekdaysPickerView: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text("Days of the week the routine will run")
                .font(.system(size: 10)).foregroundStyle(Color(white: 0.45))
            HStack(spacing: 10) {
                ForEach(Array(zip(weekdays, weekdayLabels)), id: \.0) { day, label in
                    let isSelected = routine.schedule.days.contains(day) || routine.schedule.days.contains("*")
                    Button(label) { toggleDay(day) }
                        .font(.system(size: 13, weight: .medium))
                        .frame(width: 64, height: 24)
                        .background(isSelected ? Color(red: 0.05, green: 0.44, blue: 1.0) : Color.black.opacity(0.05))
                        .foregroundStyle(isSelected ? .white : Color.primary)
                        .clipShape(RoundedRectangle(cornerRadius: 6))
                        .buttonStyle(.plain)
                }
            }
        }
    }

    private var monthdaysPickerView: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text("Days of the month the routine will run")
                .font(.system(size: 10)).foregroundStyle(Color(white: 0.45))
            let columns = Array(repeating: GridItem(.fixed(36), spacing: 6), count: 10)
            LazyVGrid(columns: columns, alignment: .leading, spacing: 6) {
                ForEach(1...31, id: \.self) { day in
                    let isOn = routine.schedule.monthdays.contains(day)
                    Button("\(day)") {
                        if isOn { routine.schedule.monthdays.removeAll { $0 == day } }
                        else    { routine.schedule.monthdays.append(day) }
                    }
                    .font(.system(size: 12, weight: .medium))
                    .frame(width: 36, height: 24)
                    .background(isOn ? Color(red: 0.05, green: 0.44, blue: 1.0) : Color.black.opacity(0.05))
                    .foregroundStyle(isOn ? .white : Color.primary)
                    .clipShape(RoundedRectangle(cornerRadius: 6))
                    .buttonStyle(.plain)
                }
            }
        }
    }

    private var timesPickerView: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text("Time of the day").font(.system(size: 10)).foregroundStyle(Color(white: 0.45))
            FlowLayout(spacing: 10) {
                AddTimeButton { time in
                    if !routine.schedule.times.contains(time) {
                        routine.schedule.times.append(time)
                        routine.schedule.times.sort()
                    }
                }
                ForEach(routine.schedule.times, id: \.self) { time in
                    TimeChip(time: time) { routine.schedule.times.removeAll { $0 == time } }
                }
            }
        }
    }

    private var intervalPickerView: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text("Repeat every").font(.system(size: 10)).foregroundStyle(Color(white: 0.45))
            HStack(spacing: 8) {
                TextField("1", text: $intervalValue)
                    .textFieldStyle(.roundedBorder)
                    .frame(width: 52)
                    .multilineTextAlignment(.center)
                Picker("", selection: $intervalUnit) {
                    ForEach(intervalUnits, id: \.0) { unit, label in
                        Text(label).tag(unit)
                    }
                }
                .frame(width: 130)
            }
        }
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
        ModelCatalog.label(for: id)
    }

    private func modelDescription(_ id: String) -> String {
        ModelCatalog.description(for: id)
    }

    private var agentDescription: String {
        guard let id = routine.agentId,
              let agent = appState.agents.first(where: { $0.id == id })
        else { return "Send to the Bot's conversation." }
        return agent.description.isEmpty ? "Custom agent" : agent.description
    }

    private var executionSection: some View {
        detailFormSection(icon: "gear", title: "Execution") {
            // Row 1: Type + Agent (equal columns via GeometryReader)
            HStack(alignment: .top, spacing: 40) {
                VStack(alignment: .leading, spacing: 5) {
                    Text("Type").font(.system(size: 10)).foregroundStyle(Color(white: 0.45))
                    CustomSegmentedControl(
                        selection: Binding(get: { execType }, set: { setExecType($0) }),
                        options: [("default", "Default"), ("minimal", "Minimal"), ("pipeline", "Pipeline")]
                    )
                    Text(execTypeDescription)
                        .font(.system(size: 10))
                        .foregroundStyle(Color(white: 0.45))
                }
                .frame(maxWidth: .infinity)

                VStack(alignment: .leading, spacing: 5) {
                    Text("Agent").font(.system(size: 10)).foregroundStyle(Color(white: 0.45))
                    menuPicker(label: agentPickerLabel, selection: $routine.agentId, options: agentOptions)
                    Text(agentDescription)
                        .font(.system(size: 10))
                        .foregroundStyle(Color(white: 0.45))
                }
                .frame(maxWidth: .infinity)
            }

            // Row 2: Model (hidden when pipeline)
            if !routine.isPipeline {
                HStack(alignment: .top, spacing: 40) {
                    VStack(alignment: .leading, spacing: 5) {
                        Text("Model").font(.system(size: 10)).foregroundStyle(Color(white: 0.45))
                        menuPicker(label: modelDisplayName(routine.model), selection: $routine.model, options: ModelCatalog.pickerOptions)
                        Text(modelDescription(routine.model))
                            .font(.system(size: 10))
                            .foregroundStyle(Color(white: 0.45))
                    }
                    .frame(maxWidth: .infinity)
                    Spacer().frame(maxWidth: .infinity)
                }
            }
        }
    }

    // MARK: - Prompt Section

    private var promptSection: some View {
        detailFormSection(icon: "text.alignleft", title: "Prompt") {
            TextEditor(text: $routine.promptBody)
                .font(.system(size: 13))
                .frame(minHeight: 181)
                .padding(8)
                .scrollContentBackground(.hidden)
                .background(Color.white)
                .clipShape(RoundedRectangle(cornerRadius: 6))
                .overlay(
                    RoundedRectangle(cornerRadius: 6)
                        .stroke(Color.black.opacity(0.08), lineWidth: 1)
                )
        }
    }

    // MARK: - Pipeline Section

    private var pipelineSection: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "checklist")
                .font(.system(size: 17))
                .foregroundStyle(Color(white: 0.75))
                .frame(width: 22)

            VStack(alignment: .leading, spacing: 10) {
                Text("Pipeline Steps")
                    .font(.system(size: 15, weight: .bold))
                    .tracking(-0.6)
                    .foregroundStyle(Color.primary.opacity(0.5))

                Text("Steps share a workspace. Each reads previous outputs from data/{id}.md.")
                    .font(.system(size: 10))
                    .foregroundStyle(Color(white: 0.45))

                ForEach(Array(routine.pipelineStepDefs.enumerated()), id: \.element.id) { idx, _ in
                    PipelineStepCard(
                        step: $routine.pipelineStepDefs[idx],
                        index: idx + 1,
                        allPreviousSteps: Array(routine.pipelineStepDefs.prefix(idx)),
                        pipelineName: routine.id,
                        onDelete: { routine.pipelineStepDefs.remove(at: idx) }
                    )
                }

                Button {
                    routine.pipelineStepDefs.append(PipelineStepDef(model: routine.model))
                } label: {
                    HStack(spacing: 4) {
                        Image(systemName: "plus").font(.system(size: 13, weight: .bold))
                        Text("Add Step").font(.system(size: 13, weight: .medium))
                    }
                    .foregroundStyle(Color.accentColor)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 5)
                    .background(Color.accentColor.opacity(0.1))
                    .clipShape(Capsule())
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.leading, 20)
        .padding(.trailing, 32)
        .padding(.vertical, 16)
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
                // Sync schedule mode UI state back to the model before saving
                switch scheduleMode {
                case "interval":
                    routine.schedule.interval = "\(intervalValue.trimmingCharacters(in: .whitespaces))\(intervalUnit)"
                    routine.schedule.times = []
                    routine.schedule.monthdays = []
                    routine.schedule.days = ["*"]
                case "monthdays":
                    routine.schedule.interval = nil
                    routine.schedule.days = ["*"]
                    // monthdays + times already on the model
                default: // weekdays
                    routine.schedule.interval = nil
                    routine.schedule.monthdays = []
                    // days + times already on the model
                }
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

    @ViewBuilder
    private func detailFormSection<Content: View>(icon: String, title: String, @ViewBuilder content: () -> Content) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: icon)
                .font(.system(size: 17))
                .foregroundStyle(Color(white: 0.75))
                .frame(width: 22)

            VStack(alignment: .leading, spacing: 10) {
                Text(title)
                    .font(.system(size: 15, weight: .bold))
                    .tracking(-0.6)
                    .foregroundStyle(Color.primary.opacity(0.5))

                content()
            }
        }
        .padding(.leading, 20)
        .padding(.trailing, 32)
        .padding(.vertical, 16)
    }

    /// A full-width dropdown that actually stretches (Menu-based, not Picker)
    private func menuPicker<V: Hashable>(label: String, selection: Binding<V>, options: [(V, String)]) -> some View {
        Menu {
            ForEach(options, id: \.0) { value, text in
                Button {
                    selection.wrappedValue = value
                } label: {
                    HStack {
                        Text(text)
                        if selection.wrappedValue == value {
                            Image(systemName: "checkmark")
                        }
                    }
                }
            }
        } label: {
            HStack {
                Text(label)
                    .font(.system(size: 13))
                    .foregroundStyle(.primary)
                Spacer()
                Image(systemName: "chevron.up.chevron.down")
                    .font(.system(size: 10))
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 8)
            .frame(maxWidth: .infinity)
            .frame(height: 24)
            .background(Color.black.opacity(0.05))
            .clipShape(RoundedRectangle(cornerRadius: 6))
        }
        .buttonStyle(.plain)
    }

    private var agentPickerLabel: String {
        if let id = routine.agentId, let agent = appState.agents.first(where: { $0.id == id }) {
            return "\(agent.icon) \(agent.name)"
        }
        return "\u{1F916} Main (Default)"
    }

    private var agentOptions: [(String?, String)] {
        var opts: [(String?, String)] = [(nil, "\u{1F916} Main (Default)")]
        for a in appState.agents {
            opts.append((a.id, "\(a.icon) \(a.name)"))
        }
        return opts
    }

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
                    Image(systemName: "checklist")
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
                    let def = routine.pipelineStepDefs.first { $0.stepId == step.id }
                    StepRow(step: step, stepDef: def, index: idx + 1, total: steps.count,
                            workspace: routine.lastExecution?.workspace)
                    if idx < steps.count - 1 { Divider().padding(.vertical, 4) }
                }
            }
        }
    }

    private var noStepsCard: some View {
        GlassCard {
            HStack {
                Image(systemName: "info.circle.fill").foregroundStyle(.secondary)
                Text("No execution data yet. Run the pipeline to see step details.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
    }
}

struct StepRow: View {
    var step: StepExecution
    var stepDef: PipelineStepDef?
    var index: Int
    var total: Int
    var workspace: String?

    private var statusColor: Color {
        switch step.status {
        case .completed: return .statusGreen
        case .failed:    return .statusRed
        case .running:   return .statusBlue
        case .skipped, .pending: return .secondary
        }
    }

    private var effectiveOutputType: String {
        step.outputType ?? stepDef?.outputType ?? "file"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
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
                    Text(stepDef?.name ?? step.id).font(.callout)
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

            // Details row: dependencies + output type
            HStack(spacing: 8) {
                // Dependencies
                if let def = stepDef, !def.dependsOn.isEmpty {
                    HStack(spacing: 3) {
                        Image(systemName: "arrow.turn.down.right")
                            .font(.system(size: 8))
                        Text(def.dependsOn.joined(separator: ", "))
                            .font(.system(size: 9))
                    }
                    .foregroundStyle(.tertiary)
                }

                // Output type badge
                let ot = effectiveOutputType
                if ot == "telegram" {
                    HStack(spacing: 2) {
                        Image(systemName: "paperplane.fill").font(.system(size: 8))
                        Text("Telegram").font(.system(size: 9, weight: .medium))
                    }
                    .foregroundStyle(.blue)
                    .padding(.horizontal, 5).padding(.vertical, 1)
                    .background(Color.blue.opacity(0.08))
                    .clipShape(Capsule())
                } else if ot == "none" {
                    // nothing
                } else if ot != "file" {
                    // Vault path
                    HStack(spacing: 2) {
                        Image(systemName: "folder.fill").font(.system(size: 8))
                        Text(ot).font(.system(size: 9, weight: .medium)).lineLimit(1)
                    }
                    .foregroundStyle(.orange)
                    .padding(.horizontal, 5).padding(.vertical, 1)
                    .background(Color.orange.opacity(0.08))
                    .clipShape(Capsule())
                } else {
                    // Temp file
                    let fname = stepDef?.resolvedFilename ?? "\(step.id).md"
                    let filePath = workspace.map { "\($0)/data/\(fname)" }
                    let fileExists = filePath.map { FileManager.default.fileExists(atPath: $0) } ?? false
                    if step.status == .completed && fileExists, let fp = filePath {
                        Button {
                            NSWorkspace.shared.open(URL(fileURLWithPath: fp))
                        } label: {
                            HStack(spacing: 2) {
                                Image(systemName: "doc.text").font(.system(size: 8))
                                Text("data/\(fname)").font(.system(size: 9, weight: .medium))
                            }
                            .foregroundStyle(.secondary)
                        }
                        .buttonStyle(.plain)
                        .padding(.horizontal, 5).padding(.vertical, 1)
                        .background(Color.primary.opacity(0.04))
                        .clipShape(Capsule())
                    } else {
                        HStack(spacing: 2) {
                            Image(systemName: "doc.text").font(.system(size: 8))
                            Text("data/\(fname)").font(.system(size: 9, weight: .medium))
                        }
                        .foregroundStyle(.tertiary)
                        .padding(.horizontal, 5).padding(.vertical, 1)
                        .background(Color.primary.opacity(0.04))
                        .clipShape(Capsule())
                    }
                }
            }
            .padding(.leading, 44) // align with step name (18 + 10 + 16)
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
