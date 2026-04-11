import SwiftUI

struct RoutineFormSheet: View {
    @EnvironmentObject var appState: AppState
    @Environment(\.dismiss) var dismiss

    /// Owner agent id that will be used when saving. Defaults to "main".
    /// Passed from the list view so the new routine inherits the current filter.
    let initialOwnerAgentId: String

    init(initialOwnerAgentId: String = "main") {
        self.initialOwnerAgentId = initialOwnerAgentId
        _ownerAgentId = State(initialValue: initialOwnerAgentId)
    }

    @State private var name = ""
    @State private var title = ""
    @State private var description = ""
    @State private var scheduleMode: String = "weekdays"   // "weekdays" | "monthdays" | "interval"
    @State private var times: [String] = ["09:00"]
    @State private var days: [String] = ["mon", "tue", "wed", "thu", "fri"]
    @State private var intervalValue: String = "1"
    @State private var intervalUnit: String = "h"          // "m" | "h" | "d" | "w"
    @State private var monthdays: [Int] = []
    @State private var model = "sonnet"
    @State private var agentId: String? = nil
    @State private var ownerAgentId: String = "main"
    @State private var promptBody = ""
    @State private var isSaving = false
    @State private var enabled = true
    @State private var executionType: String = "default" // "default" | "minimal" | "pipeline"
    @State private var pipelineSteps: [PipelineStepDef] = []
    @State private var lastAddedStepId: UUID?

    private let weekdays = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    private let weekdayLabels = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

    private var isPipeline: Bool { executionType == "pipeline" }

    private var canCreate: Bool {
        guard !title.isEmpty && !isSaving else { return false }
        if isPipeline { return !pipelineSteps.isEmpty && pipelineSteps.allSatisfy { !$0.name.isEmpty && !$0.prompt.isEmpty } }
        return !promptBody.isEmpty
    }

    // MARK: - Body

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                ScrollView {
                    VStack(spacing: 20) {
                        // Routine Name section
                        nameSection

                        sectionDivider

                        // Schedule section
                        scheduleSection

                        sectionDivider

                        // Execution section
                        executionSection

                        sectionDivider

                        // Prompt (routine) or Pipeline Steps
                        if isPipeline {
                            pipelineStepsSection
                        } else {
                            promptSection
                        }
                    }
                    .padding(.top, 20)
                }

                // Bottom bar
                bottomBar
            }
            .navigationTitle("")
            .toolbar {
                ToolbarItem(placement: .principal) {
                    Picker("", selection: .constant("config")) {
                        Text("Configuration").tag("config")
                        Text("History").tag("history")
                    }
                    .pickerStyle(.segmented)
                    .frame(width: 254)
                }
            }
        }
        .frame(minWidth: 720, minHeight: 560)
    }

    // MARK: - Name Section

    private var nameSection: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "info.circle.fill")
                .font(.system(size: 17))
                .foregroundStyle(Color(white: 0.75))
                .frame(width: 22)

            VStack(alignment: .leading, spacing: 10) {
                VStack(alignment: .leading, spacing: 0) {
                    TextField("Routine Name", text: $title)
                        .font(.system(size: 17, weight: .bold))
                        .textFieldStyle(.plain)
                        .onChange(of: title) { _, v in
                            name = v.lowercased()
                                .replacingOccurrences(of: " ", with: "-")
                                .filter { $0.isLetter || $0.isNumber || $0 == "-" }
                        }
                    if !name.isEmpty {
                        Text("\(name).md")
                            .font(.system(size: 10))
                            .foregroundStyle(Color(hex: 0x727272))
                    }
                }
                TextField("Routine description goes here", text: $description)
                    .font(.system(size: 13))
                    .foregroundStyle(Color(hex: 0x727272))
                    .textFieldStyle(.plain)
            }

            Toggle("", isOn: $enabled)
                .labelsHidden()
                .toggleStyle(.switch)
                .tint(.green)
                .frame(width: 54)
        }
        .padding(.horizontal, 20)
        .padding(.trailing, 12)
    }

    // MARK: - Schedule Section

    private let intervalUnits: [(String, String)] = [
        ("m", "minutes"), ("h", "hours"), ("d", "days"), ("w", "weeks")
    ]

    private var scheduleSection: some View {
        formSection(icon: "calendar", title: "Schedule") {
            // Mode selector — three mutually exclusive options
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
            fieldLabel("Days of the week the routine will run")
            HStack(spacing: 10) {
                ForEach(Array(zip(weekdays, weekdayLabels)), id: \.0) { day, label in
                    let selected = days.contains(day) || days.contains("*")
                    Button(label) { toggleDay(day) }
                        .font(.system(size: 13, weight: .medium))
                        .frame(width: 64, height: 24)
                        .background(selected ? Color(hex: 0x0D6FFF) : Color.black.opacity(0.05))
                        .foregroundStyle(selected ? .white : Color.primary)
                        .clipShape(RoundedRectangle(cornerRadius: 6))
                        .buttonStyle(.plain)
                }
            }
        }
    }

    private var monthdaysPickerView: some View {
        VStack(alignment: .leading, spacing: 5) {
            fieldLabel("Days of the month the routine will run")
            let columns = Array(repeating: GridItem(.fixed(36), spacing: 6), count: 10)
            LazyVGrid(columns: columns, alignment: .leading, spacing: 6) {
                ForEach(1...31, id: \.self) { day in
                    let isOn = monthdays.contains(day)
                    Button("\(day)") {
                        if isOn { monthdays.removeAll { $0 == day } }
                        else    { monthdays.append(day) }
                    }
                    .font(.system(size: 12, weight: .medium))
                    .frame(width: 36, height: 24)
                    .background(isOn ? Color(hex: 0x0D6FFF) : Color.black.opacity(0.05))
                    .foregroundStyle(isOn ? .white : Color.primary)
                    .clipShape(RoundedRectangle(cornerRadius: 6))
                    .buttonStyle(.plain)
                }
            }
        }
    }

    private var timesPickerView: some View {
        VStack(alignment: .leading, spacing: 5) {
            fieldLabel("Time of the day")
            FlowLayout(spacing: 10) {
                AddTimeButton { t in
                    if !times.contains(t) { times.append(t); times.sort() }
                }
                ForEach(times, id: \.self) { time in
                    TimeChip(time: time) { times.removeAll { $0 == time } }
                }
            }
        }
    }

    private var intervalPickerView: some View {
        VStack(alignment: .leading, spacing: 5) {
            fieldLabel("Repeat every")
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

    private var executionSection: some View {
        formSection(icon: "gear", title: "Execution") {
            // Row 1: Type + Agent
            HStack(alignment: .top, spacing: 40) {
                // Type
                VStack(alignment: .leading, spacing: 5) {
                    fieldLabel("Type")
                    CustomSegmentedControl(
                        selection: $executionType,
                        options: [("default", "Default"), ("minimal", "Minimal"), ("pipeline", "Pipeline")]
                    )
                    fieldLabel(executionTypeDescription)
                }
                .frame(maxWidth: .infinity)

                // Agent
                VStack(alignment: .leading, spacing: 5) {
                    fieldLabel("Agent")
                    formMenuPicker(label: agentPickerLabel, selection: Binding(
                        get: { agentId ?? "__none__" },
                        set: { agentId = $0 == "__none__" ? nil : $0 }
                    ), options: agentMenuOptions)
                    fieldLabel("Send to the Bot's conversation.")
                }
                .frame(maxWidth: .infinity)
            }

            // Row 2: Owner + Model (Model hidden when pipeline)
            HStack(alignment: .top, spacing: 40) {
                // Owner Agent — decides which agent's vault folder stores this routine
                VStack(alignment: .leading, spacing: 5) {
                    fieldLabel("Owner")
                    formMenuPicker(label: ownerAgentLabel, selection: $ownerAgentId,
                                   options: ownerAgentOptions)
                    fieldLabel("Lives under vault/<owner>/Routines/")
                }
                .frame(maxWidth: .infinity)

                if !isPipeline {
                    VStack(alignment: .leading, spacing: 5) {
                        fieldLabel("Model")
                        formMenuPicker(label: modelDisplayName, selection: $model, options: [
                            ("sonnet", "Sonnet 4.6"),
                            ("opus", "Opus 4.6"),
                            ("haiku", "Haiku 4.5"),
                        ])
                        fieldLabel(modelDescription)
                    }
                    .frame(maxWidth: .infinity)
                } else {
                    Spacer().frame(maxWidth: .infinity)
                }
            }
        }
    }

    // MARK: - Prompt Section

    private var promptSection: some View {
        formSection(icon: "text.alignleft", title: "Prompt") {
            TextEditor(text: $promptBody)
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

    // MARK: - Pipeline Steps Section

    private var pipelineStepsSection: some View {
        formSection(icon: "checklist", title: "Pipeline Steps") {
            ForEach(Array(pipelineSteps.enumerated()), id: \.element.id) { idx, _ in
                PipelineStepCard(
                    step: $pipelineSteps[idx],
                    index: idx + 1,
                    allPreviousSteps: Array(pipelineSteps.prefix(idx)),
                    pipelineName: name,
                    onDelete: { pipelineSteps.remove(at: idx) },
                    startExpanded: pipelineSteps[idx].id == lastAddedStepId
                )
            }

            Button {
                let newStep = PipelineStepDef(model: "sonnet")
                lastAddedStepId = newStep.id
                pipelineSteps.append(newStep)
            } label: {
                HStack(spacing: 4) {
                    Image(systemName: "plus").font(.system(size: 13, weight: .bold))
                    Text("Add Step").font(.system(size: 13, weight: .medium))
                }
                .foregroundStyle(Color(hex: 0x0088FF))
                .padding(.horizontal, 12)
                .padding(.vertical, 5)
                .background(Color(hex: 0x0D6FFF).opacity(0.1))
                .clipShape(Capsule())
            }
            .buttonStyle(.plain)
        }
    }

    // MARK: - Bottom Bar

    private var bottomBar: some View {
        HStack(spacing: 8) {
            // Run Now
            Button {
                // TODO: trigger dry run
            } label: {
                HStack(spacing: 4) {
                    Image(systemName: "play.circle.fill").font(.system(size: 13))
                    Text("Run Now").font(.system(size: 13, weight: .medium))
                }
                .padding(.horizontal, 16)
                .frame(height: 24)
                .background(Color.black.opacity(0.05))
                .clipShape(RoundedRectangle(cornerRadius: 6))
            }
            .buttonStyle(.plain)

            // Delete
            Button(role: .destructive) {
                // TODO: delete routine
            } label: {
                HStack(spacing: 4) {
                    Image(systemName: "trash").font(.system(size: 13))
                    Text("Delete").font(.system(size: 13, weight: .medium))
                }
                .foregroundStyle(Color(hex: 0xFF383C))
                .padding(.horizontal, 16)
                .frame(height: 24)
                .background(Color(hex: 0xFF383C).opacity(0.25))
                .clipShape(RoundedRectangle(cornerRadius: 6))
            }
            .buttonStyle(.plain)

            Spacer()

            // Cancel
            Button("Cancel") { dismiss() }
                .font(.system(size: 13, weight: .medium))
                .padding(.horizontal, 16)
                .frame(height: 24)
                .background(Color.black.opacity(0.05))
                .clipShape(RoundedRectangle(cornerRadius: 6))
                .buttonStyle(.plain)

            // Save
            Button("Save") {
                isSaving = true
                let todayStr = { let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; return f.string(from: Date()) }()
                for i in pipelineSteps.indices { pipelineSteps[i].autoId() }
                let savedSchedule: Routine.Schedule
                switch scheduleMode {
                case "interval":
                    savedSchedule = Routine.Schedule(
                        times: [], days: ["*"], until: nil,
                        interval: "\(intervalValue.trimmingCharacters(in: .whitespaces))\(intervalUnit)",
                        monthdays: []
                    )
                case "monthdays":
                    savedSchedule = Routine.Schedule(
                        times: times, days: ["*"], until: nil,
                        interval: nil, monthdays: monthdays
                    )
                default: // weekdays
                    savedSchedule = Routine.Schedule(
                        times: times, days: days, until: nil,
                        interval: nil, monthdays: []
                    )
                }
                var routine = Routine(
                    id: name,
                    title: title,
                    description: description,
                    schedule: savedSchedule,
                    model: model,
                    agentId: agentId,
                    enabled: enabled,
                    promptBody: isPipeline ? "" : promptBody,
                    created: todayStr,
                    updated: todayStr,
                    tags: [isPipeline ? "pipeline" : "routine"],
                    routineType: isPipeline ? "pipeline" : (executionType == "minimal" ? "routine" : "routine"),
                    notify: "final",
                    minimalContext: executionType == "minimal",
                    pipelineStepDefs: isPipeline ? pipelineSteps : []
                )
                routine.ownerAgentId = ownerAgentId.isEmpty ? "main" : ownerAgentId
                Task {
                    try? await appState.saveRoutine(routine)
                    isSaving = false
                    dismiss()
                }
            }
            .font(.system(size: 13, weight: .medium))
            .foregroundStyle(.white)
            .padding(.horizontal, 16)
            .frame(height: 24)
            .background(Color(hex: 0x0D6FFF))
            .clipShape(RoundedRectangle(cornerRadius: 6))
            .buttonStyle(.plain)
            .disabled(!canCreate)
            .opacity(canCreate ? 1 : 0.5)
        }
        .padding(.horizontal, 17)
        .padding(.top, 22)
        .padding(.bottom, 20)
        .overlay(alignment: .top) {
            Color.black.opacity(0.1).frame(height: 1)
        }
    }

    // MARK: - Helpers

    @ViewBuilder
    private func formSection<Content: View>(icon: String, title: String, @ViewBuilder content: () -> Content) -> some View {
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
    }

    private var sectionDivider: some View {
        Color.black.opacity(0.05)
            .frame(height: 1)
            .padding(.horizontal, 20)
    }

    private func fieldLabel(_ text: String) -> some View {
        Text(text)
            .font(.system(size: 10))
            .foregroundStyle(Color(hex: 0x727272))
    }

    /// Full-width dropdown using Menu (NSPopUpButton via Picker ignores maxWidth)
    private func formMenuPicker<V: Hashable>(label: String, selection: Binding<V>, options: [(V, String)]) -> some View {
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
        if let id = agentId, let agent = appState.agents.first(where: { $0.id == id }) {
            return "\(agent.icon) \(agent.name)"
        }
        return "\u{1F916} Main (Default)"
    }

    private var agentMenuOptions: [(String, String)] {
        var opts: [(String, String)] = [("__none__", "\u{1F916} Main (Default)")]
        for a in appState.agents {
            opts.append((a.id, "\(a.icon) \(a.name)"))
        }
        return opts
    }

    /// Human label for the currently-selected owner agent.
    private var ownerAgentLabel: String {
        if ownerAgentId == "main" {
            return "\(appState.mainAgent.icon) \(appState.mainAgent.name)"
        }
        if let agent = appState.agents.first(where: { $0.id == ownerAgentId }) {
            return "\(agent.icon) \(agent.name)"
        }
        return ownerAgentId
    }

    /// Owner agent options — always includes "main" plus any custom agents.
    private var ownerAgentOptions: [(String, String)] {
        var opts: [(String, String)] = [("main", "\(appState.mainAgent.icon) \(appState.mainAgent.name)")]
        for a in appState.agents {
            opts.append((a.id, "\(a.icon) \(a.name)"))
        }
        return opts
    }

    private var modelDisplayName: String {
        switch model {
        case "opus": return "Opus 4.6"
        case "haiku": return "Haiku 4.5"
        default: return "Sonnet 4.6"
        }
    }

    private var executionTypeDescription: String {
        switch executionType {
        case "minimal": return "Minimal context to execute the routine. Agent won't read the vault."
        case "pipeline": return "Multi-step pipeline with individual agents per step."
        default: return "Full context. Agent reads the vault for context."
        }
    }

    private var modelDescription: String {
        switch model {
        case "opus": return "Most capable for ambitious work"
        case "haiku": return "Fast and lightweight"
        default: return "Best balance of speed and quality"
        }
    }

    private func toggleDay(_ day: String) {
        if days.contains("*") { days = [day]; return }
        if days.contains(day) {
            days.removeAll { $0 == day }
            if days.isEmpty { days = ["*"] }
        } else {
            days.append(day)
        }
    }
}

// MARK: - Pipeline Step Card

struct PipelineStepCard: View {
    @Binding var step: PipelineStepDef
    var index: Int
    var allPreviousSteps: [PipelineStepDef]
    var pipelineName: String
    var onDelete: () -> Void

    @State private var isExpanded: Bool
    @State private var showDepPicker = false

    init(step: Binding<PipelineStepDef>, index: Int, allPreviousSteps: [PipelineStepDef], pipelineName: String, onDelete: @escaping () -> Void, startExpanded: Bool = false) {
        self._step = step
        self.index = index
        self.allPreviousSteps = allPreviousSteps
        self.pipelineName = pipelineName
        self.onDelete = onDelete
        self._isExpanded = State(initialValue: startExpanded)
    }

    private var effectiveStepId: String {
        step.stepId.isEmpty
            ? step.name.lowercased().replacingOccurrences(of: " ", with: "-").filter { $0.isLetter || $0.isNumber || $0 == "-" }
            : step.stepId
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Header: chevron + step label + name + model picker
            HStack(spacing: 5) {
                Button { withAnimation(.easeInOut(duration: 0.2)) { isExpanded.toggle() } } label: {
                    Image(systemName: isExpanded ? "chevron.down" : "chevron.right")
                        .font(.system(size: 17))
                        .foregroundStyle(Color(white: 0.75))
                        .frame(width: 22)
                }
                .buttonStyle(.plain)

                Text("Step \(index):")
                    .font(.system(size: 15, weight: .bold))
                    .tracking(-0.6)
                    .foregroundStyle(Color.primary.opacity(0.5))

                Text(step.name.isEmpty ? "Untitled" : step.name)
                    .font(.system(size: 15, weight: .bold))
                    .tracking(-0.6)
                    .foregroundStyle(step.name.isEmpty ? Color.primary.opacity(0.3) : Color.primary)
                    .lineLimit(1)

                Spacer(minLength: 8)

                Picker("", selection: $step.model) {
                    Text("Sonnet 4.6").tag("sonnet")
                    Text("Opus 4.6").tag("opus")
                    Text("Haiku 4.5").tag("haiku")
                }
                .fixedSize()
            }

            if isExpanded {
                Color.black.opacity(0.05).frame(height: 1).padding(.top, 10)

                VStack(alignment: .leading, spacing: 10) {
                    // Step name (editable inline)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Step Name")
                            .font(.system(size: 10))
                            .foregroundStyle(Color(hex: 0x727272))
                        TextField("e.g. Collect Data", text: $step.name)
                            .font(.system(size: 13, weight: .medium))
                            .textFieldStyle(.roundedBorder)
                    }

                    // Prompt
                    VStack(alignment: .leading, spacing: 5) {
                        Text("Prompt")
                            .font(.system(size: 10))
                            .foregroundStyle(Color(hex: 0x727272))

                        TextEditor(text: $step.prompt)
                            .font(.system(size: 13, weight: .medium))
                            .frame(height: 100)
                            .padding(8)
                            .scrollContentBackground(.hidden)
                            .background(Color.white)
                            .clipShape(RoundedRectangle(cornerRadius: 6))
                            .overlay(
                                RoundedRectangle(cornerRadius: 6)
                                    .stroke(Color.black.opacity(0.08), lineWidth: 1)
                            )
                    }

                    // Settings row: Output + File | Retries + Timeouts
                    HStack(alignment: .top, spacing: 20) {
                        // Left half: Output + File name
                        HStack(alignment: .top, spacing: 10) {
                            VStack(alignment: .leading, spacing: 5) {
                                Text("Output")
                                    .font(.system(size: 10))
                                    .foregroundStyle(Color(hex: 0x727272))
                                Picker("", selection: Binding(
                                    get: {
                                        let ot = step.outputType
                                        if ot == "none" || ot == "file" || ot == "telegram" { return ot }
                                        return "vault"
                                    },
                                    set: { val in
                                        step.outputType = val
                                        step.outputToTelegram = (val == "telegram")
                                        if val == "vault" {
                                            step.outputType = "Routines/\(pipelineName)/"
                                        }
                                    }
                                )) {
                                    Text("Temp. File").tag("file")
                                    Text("Vault Path").tag("vault")
                                    Text("Telegram Message").tag("telegram")
                                    Text("None").tag("none")
                                }
                                .labelsHidden()
                            }

                            // File name / File path field
                            if step.outputType == "file" || (step.outputType != "telegram" && step.outputType != "none") {
                                let isVault = step.outputType != "file" && step.outputType != "telegram" && step.outputType != "none"
                                VStack(alignment: .leading, spacing: 5) {
                                    Text(isVault ? "File path" : "File name")
                                        .font(.system(size: 10))
                                        .foregroundStyle(Color(hex: 0x727272))

                                    if isVault {
                                        TextField("Routines/pipeline/output.md", text: $step.outputType)
                                            .font(.system(size: 13, weight: .medium))
                                            .textFieldStyle(.roundedBorder)
                                            .frame(height: 24)
                                    } else {
                                        let defaultName = effectiveStepId.isEmpty ? "step.md" : "\(effectiveStepId).md"
                                        TextField(defaultName, text: Binding(
                                            get: { step.outputFile.isEmpty ? defaultName : step.outputFile },
                                            set: { newVal in
                                                // Only store custom value; clear if user restores default
                                                step.outputFile = (newVal == defaultName) ? "" : newVal
                                            }
                                        ))
                                            .font(.system(size: 13, weight: .medium))
                                            .textFieldStyle(.roundedBorder)
                                            .frame(height: 24)
                                    }
                                }
                            }
                        }

                        // Right half: Retries + Timeout (Idle) + Timeout (Max)
                        HStack(alignment: .top, spacing: 10) {
                            VStack(alignment: .leading, spacing: 5) {
                                Text("Retries")
                                    .font(.system(size: 10))
                                    .foregroundStyle(Color(hex: 0x727272))
                                TextField("0", value: $step.retry, format: .number)
                                    .font(.system(size: 13, weight: .medium))
                                    .textFieldStyle(.roundedBorder)
                                    .frame(height: 24)
                            }
                            VStack(alignment: .leading, spacing: 5) {
                                Text("Timeout (Idle)")
                                    .font(.system(size: 10))
                                    .foregroundStyle(Color(hex: 0x727272))
                                TextField("60s", value: $step.inactivityTimeout, format: .number)
                                    .font(.system(size: 13, weight: .medium))
                                    .textFieldStyle(.roundedBorder)
                                    .frame(height: 24)
                            }
                            VStack(alignment: .leading, spacing: 5) {
                                Text("Timeout (Max)")
                                    .font(.system(size: 10))
                                    .foregroundStyle(Color(hex: 0x727272))
                                TextField("600s", value: $step.timeout, format: .number)
                                    .font(.system(size: 13, weight: .medium))
                                    .textFieldStyle(.roundedBorder)
                                    .frame(height: 24)
                            }
                        }
                    }

                    // Dependencies (only for steps after step 1)
                    if index > 1 && !allPreviousSteps.isEmpty {
                        VStack(alignment: .leading, spacing: 5) {
                            Text("Dependencies")
                                .font(.system(size: 10))
                                .foregroundStyle(Color(hex: 0x727272))

                            FlowLayout(spacing: 10) {
                                // Add Dependency button
                                Menu {
                                    ForEach(Array(allPreviousSteps.enumerated()), id: \.element.id) { i, prev in
                                        let sid = prev.stepId.isEmpty
                                            ? prev.name.lowercased().replacingOccurrences(of: " ", with: "-").filter { $0.isLetter || $0.isNumber || $0 == "-" }
                                            : prev.stepId
                                        if !sid.isEmpty {
                                            let selected = step.dependsOn.contains(sid)
                                            Button {
                                                if selected { step.dependsOn.removeAll { $0 == sid } }
                                                else { step.dependsOn.append(sid) }
                                            } label: {
                                                HStack {
                                                    Text("Step \(i + 1): \(prev.name)")
                                                    if selected {
                                                        Image(systemName: "checkmark")
                                                    }
                                                }
                                            }
                                        }
                                    }
                                } label: {
                                    HStack(spacing: 4) {
                                        Image(systemName: "plus").font(.system(size: 13, weight: .bold))
                                        Text("Add Dependency").font(.system(size: 13, weight: .medium))
                                    }
                                    .foregroundStyle(Color(hex: 0x0088FF))
                                    .padding(.horizontal, 12)
                                    .frame(height: 24)
                                    .background(Color(hex: 0x0D6FFF).opacity(0.1))
                                    .clipShape(Capsule())
                                }
                                .buttonStyle(.plain)

                                // Dependency chips
                                ForEach(step.dependsOn, id: \.self) { depId in
                                    let depIndex = allPreviousSteps.firstIndex { ($0.stepId.isEmpty ? $0.name.lowercased().replacingOccurrences(of: " ", with: "-").filter { $0.isLetter || $0.isNumber || $0 == "-" } : $0.stepId) == depId }
                                    HStack(spacing: 4) {
                                        Text("Step \(depIndex.map { $0 + 1 } ?? 0)")
                                            .font(.system(size: 13, weight: .medium))
                                        Button {
                                            step.dependsOn.removeAll { $0 == depId }
                                        } label: {
                                            Image(systemName: "xmark.circle.fill")
                                                .font(.system(size: 13))
                                                .foregroundStyle(Color(hex: 0x8E8E93))
                                        }
                                        .buttonStyle(.plain)
                                    }
                                    .padding(.leading, 10)
                                    .padding(.trailing, 5)
                                    .frame(height: 24)
                                    .background(Color.black.opacity(0.05))
                                    .clipShape(Capsule())
                                }
                            }
                        }
                    }

                    // Delete step
                    HStack {
                        Spacer()
                        Button(role: .destructive, action: onDelete) {
                            Label("Delete Step", systemImage: "trash")
                                .font(.system(size: 13))
                        }
                        .buttonStyle(.borderless)
                    }
                }
                .padding(.top, 10)
            }
        }
        .padding(20)
        .background(Color(red: 0.965, green: 0.965, blue: 0.965, opacity: 0.6))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}

// MARK: - Color hex helper

private extension Color {
    init(hex: UInt, opacity: Double = 1.0) {
        self.init(
            red: Double((hex >> 16) & 0xFF) / 255,
            green: Double((hex >> 8) & 0xFF) / 255,
            blue: Double(hex & 0xFF) / 255,
            opacity: opacity
        )
    }
}
