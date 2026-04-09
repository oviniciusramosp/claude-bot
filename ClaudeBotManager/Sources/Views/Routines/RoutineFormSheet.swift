import SwiftUI

struct RoutineFormSheet: View {
    @EnvironmentObject var appState: AppState
    @Environment(\.dismiss) var dismiss

    @State private var name = ""
    @State private var title = ""
    @State private var description = ""
    @State private var times: [String] = ["09:00"]
    @State private var days: [String] = ["mon", "tue", "wed", "thu", "fri"]
    @State private var model = "sonnet"
    @State private var agentId: String? = nil
    @State private var promptBody = ""
    @State private var isSaving = false
    @State private var isPipeline = false
    @State private var pipelineSteps: [PipelineStepDef] = []

    private let weekdays = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    private let weekdayLabels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    private var canCreate: Bool {
        guard !title.isEmpty && !isSaving else { return false }
        if isPipeline { return !pipelineSteps.isEmpty && pipelineSteps.allSatisfy { !$0.name.isEmpty && !$0.prompt.isEmpty } }
        return !promptBody.isEmpty
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: Spacing.lg) {
                    // Title card
                    GlassCard {
                        VStack(spacing: Spacing.md) {
                            TextField("Routine Title", text: $title)
                                .font(.title3.bold())
                                .textFieldStyle(.roundedBorder)
                                .onChange(of: title) { _, v in
                                    name = v.lowercased()
                                        .replacingOccurrences(of: " ", with: "-")
                                        .filter { $0.isLetter || $0.isNumber || $0 == "-" }
                                }
                            TextField("Description", text: $description, prompt: Text("What does this routine do?"))
                                .font(.callout)
                                .textFieldStyle(.roundedBorder)
                            if !name.isEmpty {
                                Text("File: \(name).md")
                                    .font(.caption.monospacedDigit())
                                    .foregroundStyle(.tertiary)
                            }
                        }
                    }

                    // Schedule card
                    SectionCard(title: "Schedule", symbol: "calendar") {
                        VStack(alignment: .leading, spacing: Spacing.sm) {
                            Text("Days").font(.caption).foregroundStyle(.secondary)
                            HStack(spacing: Spacing.sm) {
                                let isAll = days.contains("*")
                                Button("All") { days = ["*"] }
                                    .font(.caption.bold())
                                    .padding(.horizontal, 10).padding(.vertical, 6)
                                    .background(isAll ? Color.statusBlue.opacity(0.2) : Color.primary.opacity(0.06))
                                    .foregroundStyle(isAll ? Color.statusBlue : Color.secondary)
                                    .clipShape(Capsule())

                                ForEach(Array(zip(weekdays, weekdayLabels)), id: \.0) { day, label in
                                    let selected = days.contains(day)
                                    Button(label) { toggleDay(day) }
                                        .font(.caption.bold())
                                        .padding(.horizontal, 10).padding(.vertical, 6)
                                        .background(selected ? Color.statusBlue.opacity(0.2) : Color.primary.opacity(0.06))
                                        .foregroundStyle(selected ? Color.statusBlue : Color.secondary)
                                        .clipShape(Capsule())
                                }
                            }
                        }

                        VStack(alignment: .leading, spacing: Spacing.sm) {
                            Text("Times (24h)").font(.caption).foregroundStyle(.secondary)
                            FlowLayout(spacing: Spacing.sm) {
                                ForEach(times, id: \.self) { time in
                                    TimeChip(time: time) { times.removeAll { $0 == time } }
                                }
                                AddTimeButton { t in
                                    if !times.contains(t) { times.append(t); times.sort() }
                                }
                            }
                        }
                    }

                    // Execution settings
                    SectionCard(title: "Execution", symbol: "gearshape") {
                        SettingRow("Model") {
                            Picker("", selection: $model) {
                                ForEach(["sonnet", "opus", "haiku"], id: \.self) { m in
                                    Text(m.capitalized).tag(m)
                                }
                            }
                            .pickerStyle(.segmented).frame(width: 200)
                        }

                        SettingRow("Agent") {
                            Picker("", selection: $agentId) {
                                Text("None").tag(String?.none)
                                ForEach(appState.agents) { a in
                                    Text("\(a.icon) \(a.name)").tag(Optional(a.id))
                                }
                            }
                            .frame(maxWidth: 200)
                        }

                        SettingRow("Pipeline") {
                            Toggle("", isOn: $isPipeline)
                                .labelsHidden()
                                .toggleStyle(.switch)
                        }
                    }

                    // Prompt (routine) or Steps (pipeline)
                    if isPipeline {
                        PipelineStepEditorCard(steps: $pipelineSteps, defaultModel: model)
                    } else {
                        SectionCard(title: "Prompt", symbol: "text.alignleft") {
                            TextEditor(text: $promptBody)
                                .font(.callout)
                                .frame(minHeight: 120)
                                .scrollContentBackground(.hidden)
                                .background(Color.primary.opacity(0.03))
                                .clipShape(RoundedRectangle(cornerRadius: 8))
                        }
                    }
                }
                .padding(Spacing.xl)
            }
            .navigationTitle(isPipeline ? "New Pipeline" : "New Routine")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Create") {
                        isSaving = true
                        let todayStr = { let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; return f.string(from: Date()) }()
                        for i in pipelineSteps.indices { pipelineSteps[i].autoId() }
                        let routine = Routine(
                            id: name,
                            title: title,
                            description: description,
                            schedule: Routine.Schedule(times: times, days: days, until: nil),
                            model: model,
                            agentId: agentId,
                            enabled: true,
                            promptBody: isPipeline ? "" : promptBody,
                            created: todayStr,
                            updated: todayStr,
                            tags: [isPipeline ? "pipeline" : "routine"],
                            routineType: isPipeline ? "pipeline" : "routine",
                            notify: "final",
                            pipelineStepDefs: isPipeline ? pipelineSteps : []
                        )
                        Task {
                            try? await appState.saveRoutine(routine)
                            isSaving = false
                            dismiss()
                        }
                    }
                    .disabled(!canCreate)
                }
            }
        }
        .frame(minWidth: 640, minHeight: 520)
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

// MARK: - Pipeline Step Editor Card
// (TimeChip, AddTimeButton, FlowLayout are defined in RoutineDetailView.swift)

struct PipelineStepEditorCard: View {
    @Binding var steps: [PipelineStepDef]
    var defaultModel: String

    var body: some View {
        SectionCard(title: "Pipeline Steps", symbol: "arrow.triangle.branch") {
            Text("Steps share a workspace. Each reads previous outputs from data/{id}.md.")
                .font(.caption)
                .foregroundStyle(.tertiary)

            ForEach(Array(steps.enumerated()), id: \.element.id) { idx, _ in
                PipelineStepRow(
                    step: $steps[idx],
                    index: idx + 1,
                    allStepIds: steps.enumerated().compactMap { i, s in i != idx && !s.name.isEmpty ? stepSlug(s.name) : nil },
                    onDelete: { steps.remove(at: idx) }
                )
            }

            Button {
                steps.append(PipelineStepDef(model: defaultModel))
            } label: {
                Label("Add Step", systemImage: "plus.circle")
                    .font(.callout)
            }
            .buttonStyle(.borderless)
            .foregroundStyle(Color.statusBlue)
        }
    }

    private func stepSlug(_ name: String) -> String {
        name.lowercased()
            .replacingOccurrences(of: " ", with: "-")
            .filter { $0.isLetter || $0.isNumber || $0 == "-" }
    }
}

struct PipelineStepRow: View {
    @Binding var step: PipelineStepDef
    var index: Int
    var allStepIds: [String]
    var onDelete: () -> Void

    @State private var isExpanded = true

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Header — always visible
            Button { withAnimation(.easeInOut(duration: 0.2)) { isExpanded.toggle() } } label: {
                HStack(spacing: Spacing.sm) {
                    Text("Step \(index)")
                        .font(.callout.bold())
                        .foregroundStyle(Color.statusBlue)
                    if !step.name.isEmpty {
                        Text("— \(step.name)")
                            .font(.callout)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    ModelBadge(model: step.model)
                    Image(systemName: "chevron.right")
                        .font(.caption.bold())
                        .foregroundStyle(.tertiary)
                        .rotationEffect(.degrees(isExpanded ? 90 : 0))
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .padding(Spacing.lg)

            // Expanded content
            if isExpanded {
                Divider().padding(.horizontal, Spacing.lg)

                VStack(alignment: .leading, spacing: Spacing.lg) {
                    // Step name
                    VStack(alignment: .leading, spacing: Spacing.xs) {
                        Text("Step Name").font(.caption).foregroundStyle(.secondary)
                        TextField("e.g. Analyze Data", text: $step.name)
                            .textFieldStyle(.roundedBorder)
                            .font(.callout)
                    }

                    // Model
                    SettingRow("Model") {
                        Picker("", selection: $step.model) {
                            ForEach(["sonnet", "opus", "haiku"], id: \.self) { m in
                                Text(m.capitalized).tag(m)
                            }
                        }
                        .pickerStyle(.segmented)
                        .frame(width: 200)
                    }

                    // Dependencies
                    if !allStepIds.isEmpty {
                        VStack(alignment: .leading, spacing: Spacing.sm) {
                            Text("Depends on").font(.caption).foregroundStyle(.secondary)
                            FlowLayout(spacing: 6) {
                                ForEach(allStepIds, id: \.self) { sid in
                                    let selected = step.dependsOn.contains(sid)
                                    Button(sid) {
                                        if selected { step.dependsOn.removeAll { $0 == sid } }
                                        else { step.dependsOn.append(sid) }
                                    }
                                    .font(.caption)
                                    .padding(.horizontal, 10).padding(.vertical, 5)
                                    .background(selected ? Color.statusBlue.opacity(0.2) : Color.primary.opacity(0.06))
                                    .foregroundStyle(selected ? Color.statusBlue : .secondary)
                                    .clipShape(Capsule())
                                }
                            }
                        }
                    }

                    // Timeouts — vertical layout
                    VStack(alignment: .leading, spacing: Spacing.sm) {
                        Text("Timeouts").font(.caption).foregroundStyle(.secondary)

                        HStack(spacing: Spacing.xl) {
                            HStack(spacing: Spacing.xs) {
                                Text("Idle")
                                    .font(.callout)
                                    .foregroundStyle(.secondary)
                                    .frame(width: 40, alignment: .trailing)
                                TextField("", value: $step.inactivityTimeout, format: .number)
                                    .textFieldStyle(.roundedBorder)
                                    .frame(width: 70)
                                    .font(.body.monospacedDigit())
                                Text("s").font(.callout).foregroundStyle(.tertiary)
                            }
                            .help("Kill step after this many seconds without output")

                            HStack(spacing: Spacing.xs) {
                                Text("Max")
                                    .font(.callout)
                                    .foregroundStyle(.secondary)
                                    .frame(width: 40, alignment: .trailing)
                                TextField("", value: $step.timeout, format: .number)
                                    .textFieldStyle(.roundedBorder)
                                    .frame(width: 70)
                                    .font(.body.monospacedDigit())
                                Text("s").font(.callout).foregroundStyle(.tertiary)
                            }
                            .help("Hard time limit for this step")

                            HStack(spacing: Spacing.xs) {
                                Text("Retries")
                                    .font(.callout)
                                    .foregroundStyle(.secondary)
                                TextField("", value: $step.retry, format: .number)
                                    .textFieldStyle(.roundedBorder)
                                    .frame(width: 50)
                                    .font(.body.monospacedDigit())
                            }
                            .help("Number of retry attempts if this step fails")
                        }
                    }

                    // Output type
                    SettingRow("Output") {
                        Picker("", selection: Binding(
                            get: {
                                let ot = step.outputType
                                if ot == "none" || ot == "file" || ot == "telegram" { return ot }
                                return "vault"
                            },
                            set: { newVal in
                                step.outputType = newVal
                                step.outputToTelegram = (newVal == "telegram")
                                if newVal == "vault" { step.outputType = "Notes/" }
                            }
                        )) {
                            Text("Temp file").tag("file")
                            Text("Telegram").tag("telegram")
                            Text("Vault path").tag("vault")
                            Text("None").tag("none")
                        }
                        .labelsHidden()
                        .frame(width: 120)
                    }

                    // Vault path field (only when vault output selected)
                    if step.outputType != "file" && step.outputType != "telegram" && step.outputType != "none" {
                        SettingRow("Vault path") {
                            TextField("Notes/report.md", text: $step.outputType)
                                .textFieldStyle(.roundedBorder)
                                .frame(width: 200)
                                .font(.system(.callout, design: .monospaced))
                        }
                    }

                    // Prompt
                    VStack(alignment: .leading, spacing: Spacing.sm) {
                        Text("Prompt").font(.caption).foregroundStyle(.secondary)
                        TextEditor(text: $step.prompt)
                            .font(.system(.callout, design: .monospaced))
                            .frame(minHeight: 120)
                            .scrollContentBackground(.hidden)
                            .background(Color.primary.opacity(0.03))
                            .clipShape(RoundedRectangle(cornerRadius: 8))
                    }

                    // Delete at bottom
                    HStack {
                        Spacer()
                        Button(role: .destructive, action: onDelete) {
                            Label("Delete Step", systemImage: "trash")
                                .font(.callout)
                        }
                        .buttonStyle(.borderless)
                    }
                }
                .padding(Spacing.lg)
            }
        }
        .background(Color.primary.opacity(0.03))
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay(
            RoundedRectangle(cornerRadius: 12)
                .strokeBorder(Color.glassBorder, lineWidth: 0.5)
        )
    }
}
