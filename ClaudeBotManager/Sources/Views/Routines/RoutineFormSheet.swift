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
                VStack(spacing: 16) {
                    // Title card
                    GlassCard {
                        VStack(spacing: 12) {
                            TextField("Routine Title", text: $title)
                                .font(.title3.bold())
                                .textFieldStyle(.roundedBorder)
                                .onChange(of: title) { _, v in
                                    name = v.lowercased()
                                        .replacingOccurrences(of: " ", with: "-")
                                        .filter { $0.isLetter || $0.isNumber || $0 == "-" }
                                }
                            TextField("Description", text: $description, prompt: Text("What does this routine do?"))
                                .textFieldStyle(.roundedBorder)
                            if !name.isEmpty {
                                Text("File: \(name).md")
                                    .font(.caption2.monospacedDigit())
                                    .foregroundStyle(.tertiary)
                            }
                        }
                    }

                    // Schedule card
                    GlassCard {
                        VStack(alignment: .leading, spacing: 12) {
                            HStack {
                                Text("Schedule").font(.headline)
                                Spacer()
                                Toggle("Pipeline", isOn: $isPipeline)
                                    .toggleStyle(.switch)
                                    .font(.caption)
                            }

                            VStack(alignment: .leading, spacing: 6) {
                                Text("Days").font(.caption).foregroundStyle(.secondary)
                                HStack(spacing: 6) {
                                    let isAll = days.contains("*")
                                    Button("All") { days = ["*"] }
                                        .font(.caption2.bold())
                                        .padding(.horizontal, 8).padding(.vertical, 4)
                                        .background(isAll ? Color.statusBlue.opacity(0.2) : Color.primary.opacity(0.06))
                                        .foregroundStyle(isAll ? Color.statusBlue : Color.secondary)
                                        .clipShape(Capsule())

                                    ForEach(Array(zip(weekdays, weekdayLabels)), id: \.0) { day, label in
                                        let selected = days.contains(day)
                                        Button(label) { toggleDay(day) }
                                            .font(.caption2.bold())
                                            .padding(.horizontal, 8).padding(.vertical, 4)
                                            .background(selected ? Color.statusBlue.opacity(0.2) : Color.primary.opacity(0.06))
                                            .foregroundStyle(selected ? Color.statusBlue : Color.secondary)
                                            .clipShape(Capsule())
                                    }
                                }
                            }

                            VStack(alignment: .leading, spacing: 6) {
                                Text("Times").font(.caption).foregroundStyle(.secondary)
                                FlowLayout(spacing: 6) {
                                    ForEach(times, id: \.self) { time in
                                        HStack(spacing: 4) {
                                            Text(time).font(.caption.monospacedDigit())
                                            Button { times.removeAll { $0 == time } } label: {
                                                Image(systemName: "xmark.circle.fill").font(.caption2)
                                            }
                                            .buttonStyle(.plain).foregroundStyle(.secondary)
                                        }
                                        .padding(.horizontal, 8).padding(.vertical, 4)
                                        .background(Color.primary.opacity(0.06))
                                        .clipShape(Capsule())
                                    }
                                    AddTimeButton { t in
                                        if !times.contains(t) { times.append(t); times.sort() }
                                    }
                                }
                            }

                            Divider()

                            HStack {
                                Text("Default Model").font(.caption).foregroundStyle(.secondary)
                                Spacer()
                                Picker("", selection: $model) {
                                    ForEach(["sonnet", "opus", "haiku"], id: \.self) { m in
                                        Text(m.capitalized).tag(m)
                                    }
                                }
                                .pickerStyle(.segmented).frame(width: 200)
                            }

                            HStack {
                                Text("Agent").font(.caption).foregroundStyle(.secondary)
                                Spacer()
                                Picker("", selection: $agentId) {
                                    Text("None").tag(String?.none)
                                    ForEach(appState.agents) { a in
                                        Text("\(a.icon) \(a.name)").tag(Optional(a.id))
                                    }
                                }
                                .frame(maxWidth: 200)
                            }
                        }
                    }

                    // Prompt (routine) or Steps (pipeline)
                    if isPipeline {
                        PipelineStepEditorCard(steps: $pipelineSteps, defaultModel: model)
                    } else {
                        GlassCard {
                            VStack(alignment: .leading, spacing: 8) {
                                Text("Prompt").font(.caption).foregroundStyle(.secondary)
                                TextEditor(text: $promptBody)
                                    .font(.callout)
                                    .frame(minHeight: 120)
                                    .scrollContentBackground(.hidden)
                                    .background(Color.primary.opacity(0.03))
                                    .clipShape(RoundedRectangle(cornerRadius: 8))
                            }
                        }
                    }
                }
                .padding(20)
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
                        // Auto-generate step ids
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
        .frame(minWidth: 600, minHeight: 520)
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

struct PipelineStepEditorCard: View {
    @Binding var steps: [PipelineStepDef]
    var defaultModel: String

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Label("Pipeline Steps", systemImage: "arrow.triangle.branch")
                        .font(.headline)
                    Spacer()
                    Text("\(steps.count) step\(steps.count == 1 ? "" : "s")")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Text("Steps share a workspace automatically. Each step can read outputs from previous steps (data/{id}.md) and writes its own output. No need to mention file sharing in your prompts.")
                    .font(.caption2)
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
                        .font(.caption)
                }
                .buttonStyle(.borderless)
                .foregroundStyle(Color.statusBlue)
            }
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
        DisclosureGroup(isExpanded: $isExpanded) {
            VStack(alignment: .leading, spacing: 10) {
                TextField("Step Name", text: $step.name)
                    .textFieldStyle(.roundedBorder)
                    .font(.callout)

                HStack {
                    Text("Model").font(.caption2).foregroundStyle(.secondary)
                    Spacer()
                    Picker("", selection: $step.model) {
                        ForEach(["sonnet", "opus", "haiku"], id: \.self) { m in
                            Text(m.capitalized).tag(m)
                        }
                    }
                    .pickerStyle(.segmented).frame(width: 180)
                }

                if !allStepIds.isEmpty {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Depends on").font(.caption2).foregroundStyle(.secondary)
                        FlowLayout(spacing: 4) {
                            ForEach(allStepIds, id: \.self) { sid in
                                let selected = step.dependsOn.contains(sid)
                                Button(sid) {
                                    if selected { step.dependsOn.removeAll { $0 == sid } }
                                    else { step.dependsOn.append(sid) }
                                }
                                .font(.caption2)
                                .padding(.horizontal, 8).padding(.vertical, 3)
                                .background(selected ? Color.statusBlue.opacity(0.2) : Color.primary.opacity(0.06))
                                .foregroundStyle(selected ? Color.statusBlue : .secondary)
                                .clipShape(Capsule())
                            }
                        }
                    }
                }

                HStack(spacing: 12) {
                    HStack(spacing: 4) {
                        Text("Idle").font(.caption2).foregroundStyle(.secondary)
                        TextField("", value: $step.inactivityTimeout, format: .number)
                            .textFieldStyle(.roundedBorder).frame(width: 50)
                            .font(.caption2)
                        Text("s").font(.caption2).foregroundStyle(.tertiary)
                    }
                    .help("Kill step after this many seconds without output")
                    HStack(spacing: 4) {
                        Text("Max").font(.caption2).foregroundStyle(.secondary)
                        TextField("", value: $step.timeout, format: .number)
                            .textFieldStyle(.roundedBorder).frame(width: 50)
                            .font(.caption2)
                        Text("s").font(.caption2).foregroundStyle(.tertiary)
                    }
                    .help("Hard time limit — kill step after this total elapsed time")
                    HStack(spacing: 4) {
                        Text("Retry").font(.caption2).foregroundStyle(.secondary)
                        TextField("", value: $step.retry, format: .number)
                            .textFieldStyle(.roundedBorder).frame(width: 35)
                            .font(.caption2)
                    }
                    .help("Number of retry attempts if this step fails")
                    Spacer()
                    Toggle("Output to Telegram", isOn: $step.outputToTelegram)
                        .font(.caption2)
                        .toggleStyle(.checkbox)
                        .help("Send this step's output as the pipeline's Telegram message")
                }

                VStack(alignment: .leading, spacing: 4) {
                    Text("Prompt").font(.caption2).foregroundStyle(.secondary)
                    TextEditor(text: $step.prompt)
                        .font(.system(.caption, design: .monospaced))
                        .frame(minHeight: 80)
                        .scrollContentBackground(.hidden)
                        .background(Color.primary.opacity(0.03))
                        .clipShape(RoundedRectangle(cornerRadius: 6))
                }
            }
            .padding(.top, 6)
        } label: {
            HStack {
                Text("Step \(index)")
                    .font(.caption.bold())
                    .foregroundStyle(Color.statusBlue)
                if !step.name.isEmpty {
                    Text("— \(step.name)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                ModelBadge(model: step.model)
                Button(role: .destructive) { onDelete() } label: {
                    Image(systemName: "trash")
                        .font(.caption2)
                }
                .buttonStyle(.borderless)
                .foregroundStyle(Color.statusRed)
            }
        }
        .padding(10)
        .background(Color.primary.opacity(0.03))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}
