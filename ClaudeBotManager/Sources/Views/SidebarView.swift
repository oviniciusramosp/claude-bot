import SwiftUI

struct SidebarView: View {
    @Binding var selection: SidebarItem
    @EnvironmentObject var appState: AppState

    var body: some View {
        List(selection: $selection) {
            Section("Overview") {
                sidebarLabel(.dashboard)
                sidebarLabel(.web)
            }
            Section("Manage") {
                sidebarLabel(.agents)
                sidebarLabel(.routines)
                sidebarLabel(.skills)
                sidebarLabel(.reactions)
            }
            Section("System") {
                sidebarLabel(.sessions)
                sidebarLabel(.usage)
                sidebarLabel(.logs)
                sidebarLabel(.settings)
                sidebarLabel(.changelog)
            }
        }
        .listStyle(.sidebar)
        .navigationTitle("Claude Bot")
        .frame(minWidth: 180, idealWidth: 200)
        .task {
            await refreshUsageBadge()
        }
        .onChange(of: selection) { _, newValue in
            if newValue == .usage {
                Task { await refreshUsageBadge() }
            }
        }
    }

    private func refreshUsageBadge() async {
        let service = CostHistoryService(dataDir: appState.dataDir)
        do {
            let total = try await service.totalThisWeek()
            appState.weeklyCostUSD = total
        } catch {
            // Missing file or decode failure is fine — keep badge hidden.
            appState.weeklyCostUSD = 0
        }
    }

    private func sidebarLabel(_ item: SidebarItem) -> some View {
        Label {
            HStack {
                Text(item.rawValue)
                Spacer()
                if let badge = badgeText(for: item) {
                    Text(badge)
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(.tertiary)
                }
            }
        } icon: {
            Image(systemName: item.symbol)
        }
        .tag(item)
    }

    private func badgeText(for item: SidebarItem) -> String? {
        switch item {
        case .dashboard:
            return appState.isRunning ? "Running" : nil
        case .agents:
            let c = appState.agents.count + 1 // +1 for Main agent
            return "\(c)"
        case .routines:
            let c = appState.routines.count
            return c > 0 ? "\(c)" : nil
        case .skills:
            let c = appState.skills.count
            return c > 0 ? "\(c)" : nil
        case .reactions:
            let c = appState.reactions.count
            return c > 0 ? "\(c)" : nil
        case .usage:
            let cost = appState.weeklyCostUSD
            return cost > 0 ? String(format: "$%.2f", cost) : nil
        case .logs:
            let errors = appState.routines.flatMap { $0.todayExecutions }.filter { $0.status == .failed }.count
            return errors > 0 ? "⚠ \(errors)" : nil
        case .changelog:
            let v = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String
            return v.map { "v\($0)" }
        case .web:
            return appState.webRunning ? "Running" : nil
        default:
            return nil
        }
    }
}

// MARK: - Shell helper (nonisolated, safe to call from detached tasks)

@discardableResult
private func runShell(_ cmd: String) -> String {
    let p = Process()
    let pipe = Pipe()
    p.executableURL = URL(fileURLWithPath: "/bin/bash")
    p.arguments = ["-c", cmd]
    p.standardOutput = pipe
    p.standardError = Pipe()
    try? p.run()
    p.waitUntilExit()
    return String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
}

// MARK: - Changelog

struct ChangelogEntry: Identifiable {
    var id: String { hash }
    var hash: String
    var message: String
    var date: String          // YYYY-MM-DD

    var commitType: String {
        let msg = message.lowercased()
        if msg.hasPrefix("feat")     { return "feat" }
        if msg.hasPrefix("fix")      { return "fix" }
        if msg.hasPrefix("refactor") { return "refactor" }
        if msg.hasPrefix("docs")     { return "docs" }
        if msg.hasPrefix("chore")    { return "chore" }
        if msg.hasPrefix("test")     { return "test" }
        if msg.hasPrefix("perf")     { return "perf" }
        if msg.hasPrefix("style")    { return "style" }
        if msg.hasPrefix("ci")       { return "ci" }
        return "other"
    }

    var typeIcon: String {
        switch commitType {
        case "feat":     return "sparkles"
        case "fix":      return "wrench.fill"
        case "refactor": return "arrow.triangle.2.circlepath"
        case "docs":     return "doc.text.fill"
        case "chore":    return "gearshape.fill"
        case "test":     return "checkmark.shield.fill"
        case "perf":     return "bolt.fill"
        case "style":    return "paintbrush.fill"
        case "ci":       return "server.rack"
        default:         return "circle.fill"
        }
    }

    var typeColor: Color {
        switch commitType {
        case "feat":     return .statusBlue
        case "fix":      return .statusGreen
        case "refactor": return .purple
        case "docs":     return .orange
        case "chore":    return .secondary
        case "test":     return .teal
        case "perf":     return .yellow
        case "style":    return .pink
        case "ci":       return .indigo
        default:         return .primary
        }
    }

    var shortHash: String { String(hash.prefix(7)) }

    /// Message without the conventional commit prefix (e.g. "feat: add X" → "add X")
    var cleanMessage: String {
        if let colonRange = message.range(of: ": ") {
            return String(message[colonRange.upperBound...])
        }
        return message
    }

    /// Conventional commit prefix label (e.g. "feat", "fix")
    var typeLabel: String {
        if let colonIdx = message.firstIndex(of: ":") {
            let prefix = String(message[message.startIndex..<colonIdx])
            if prefix.count <= 12, !prefix.contains(" ") { return prefix }
        }
        return commitType
    }
}

/// Groups entries by date for section display
struct ChangelogDateGroup: Identifiable {
    var id: String { date }
    var date: String                 // YYYY-MM-DD
    var entries: [ChangelogEntry]

    var displayDate: String {
        let df = DateFormatter()
        df.dateFormat = "yyyy-MM-dd"
        guard let d = df.date(from: date) else { return date }

        let cal = Calendar.current
        if cal.isDateInToday(d)     { return "Today" }
        if cal.isDateInYesterday(d) { return "Yesterday" }

        let out = DateFormatter()
        out.dateFormat = "MMM d, yyyy"
        return out.string(from: d)
    }
}

// MARK: - Changelog Page View

struct ChangelogPageView: View {
    @EnvironmentObject var appState: AppState
    @State private var groups: [ChangelogDateGroup] = []
    @State private var pendingCount = 0
    @State private var isUpdating = false
    @State private var showUpdateConfirm = false

    private var repoPath: String {
        URL(fileURLWithPath: appState.vaultPath).deletingLastPathComponent().path
    }

    private var appVersion: String {
        Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "—"
    }

    var body: some View {
        VStack(spacing: 0) {
            // Header
            HStack(spacing: Spacing.sm) {
                Text("v\(appVersion)")
                    .font(.system(size: 13, weight: .semibold, design: .monospaced))
                    .foregroundStyle(.secondary)

                Spacer()

                if isUpdating {
                    ProgressView()
                        .controlSize(.small)
                    Text("Updating…")
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                } else if pendingCount > 0 {
                    Button {
                        showUpdateConfirm = true
                    } label: {
                        HStack(spacing: 4) {
                            Image(systemName: "arrow.down.circle.fill")
                            Text("\(pendingCount) update\(pendingCount == 1 ? "" : "s")")
                        }
                        .font(.system(size: 11, weight: .medium))
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(.orange)
                    .controlSize(.small)
                }
            }
            .padding(.horizontal, Spacing.xl)
            .padding(.vertical, Spacing.md)

            Divider()

            // Grouped commit list
            if groups.isEmpty {
                EmptyStateView(
                    symbol: "doc.text.magnifyingglass",
                    title: "No git history found",
                    subtitle: "Could not read git log from the repository"
                )
            } else {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0, pinnedViews: .sectionHeaders) {
                        ForEach(groups) { group in
                            Section {
                                ForEach(group.entries) { entry in
                                    ChangelogRow(entry: entry)
                                    Divider().padding(.leading, 36)
                                }
                            } header: {
                                HStack {
                                    Text(group.displayDate)
                                        .font(.system(size: 11, weight: .semibold))
                                        .foregroundStyle(.secondary)
                                        .textCase(.uppercase)
                                    Spacer()
                                    Text("\(group.entries.count)")
                                        .font(.system(size: 10, weight: .medium, design: .monospaced))
                                        .foregroundStyle(.tertiary)
                                }
                                .padding(.horizontal, Spacing.xl)
                                .padding(.vertical, Spacing.sm)
                                .background(.bar)
                            }
                        }
                    }
                }
            }
        }
        .background(Color(.windowBackgroundColor))
        .navigationTitle("Changelog")
        .task {
            loadChangelog()
            checkForUpdates()
        }
        .confirmationDialog(
            "Update Available",
            isPresented: $showUpdateConfirm,
            titleVisibility: .visible
        ) {
            Button("Pull & Rebuild") { performUpdate() }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Pull \(pendingCount) new commit\(pendingCount == 1 ? "" : "s") and rebuild. The app will restart.")
        }
    }

    private func loadChangelog() {
        let path = repoPath
        // Format: hash<TAB>message<TAB>YYYY-MM-DD
        let raw = runShell(
            "git -C \"\(path)\" log --pretty=format:'%h\t%s\t%cs' --no-decorate -80 2>/dev/null"
        )
        let entries = raw
            .components(separatedBy: "\n")
            .filter { !$0.isEmpty }
            .compactMap { line -> ChangelogEntry? in
                let parts = line.split(separator: "\t", maxSplits: 2)
                guard parts.count == 3 else { return nil }
                return ChangelogEntry(
                    hash: String(parts[0]),
                    message: String(parts[1]),
                    date: String(parts[2])
                )
            }

        // Group by date, preserving order
        var seen: [String: Int] = [:]
        var result: [ChangelogDateGroup] = []
        for entry in entries {
            if let idx = seen[entry.date] {
                result[idx].entries.append(entry)
            } else {
                seen[entry.date] = result.count
                result.append(ChangelogDateGroup(date: entry.date, entries: [entry]))
            }
        }
        groups = result
    }

    private func checkForUpdates() {
        let path = repoPath
        Task.detached(priority: .background) {
            let result = runShell(
                "git -C \"\(path)\" fetch --quiet 2>/dev/null; " +
                "git -C \"\(path)\" log HEAD..origin/main --oneline 2>/dev/null | wc -l"
            )
            let count = Int(result.trimmingCharacters(in: .whitespacesAndNewlines)) ?? 0
            await MainActor.run { pendingCount = count }
        }
    }

    private func performUpdate() {
        isUpdating = true
        let path = repoPath
        let buildScript = "\(path)/ClaudeBotManager/build-app.sh"
        Task.detached(priority: .background) {
            _ = runShell(
                "cd \"\(path)\" && git pull --ff-only 2>&1 && bash \"\(buildScript)\" 2>&1"
            )
        }
    }
}

// MARK: - Changelog Row

private struct ChangelogRow: View {
    let entry: ChangelogEntry

    var body: some View {
        HStack(alignment: .center, spacing: Spacing.sm) {
            // Type icon
            Image(systemName: entry.typeIcon)
                .font(.system(size: 11))
                .foregroundStyle(entry.typeColor)
                .frame(width: 20, alignment: .center)

            // Commit content
            VStack(alignment: .leading, spacing: 2) {
                Text(entry.cleanMessage)
                    .font(.system(size: 12))
                    .foregroundStyle(.primary)
                    .lineLimit(2)

                HStack(spacing: Spacing.sm) {
                    Text(entry.typeLabel)
                        .font(.system(size: 9, weight: .semibold))
                        .foregroundStyle(entry.typeColor)
                        .padding(.horizontal, 5)
                        .padding(.vertical, 1)
                        .background(entry.typeColor.opacity(0.12), in: RoundedRectangle(cornerRadius: 3))

                    Text(entry.shortHash)
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(.tertiary)
                }
            }

            Spacer()
        }
        .padding(.horizontal, Spacing.xl)
        .padding(.vertical, Spacing.sm)
    }
}
