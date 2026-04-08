import SwiftUI

struct SidebarView: View {
    @Binding var selection: SidebarItem
    @EnvironmentObject var appState: AppState

    var body: some View {
        List(selection: $selection) {
            Section("Overview") {
                sidebarLabel(.dashboard)
            }
            Section("Manage") {
                sidebarLabel(.agents)
                sidebarLabel(.routines)
                sidebarLabel(.skills)
            }
            Section("System") {
                sidebarLabel(.sessions)
                sidebarLabel(.logs)
                sidebarLabel(.settings)
                sidebarLabel(.changelog)
            }
        }
        .listStyle(.sidebar)
        .navigationTitle("Claude Bot")
        .frame(minWidth: 180, idealWidth: 200)
        .safeAreaInset(edge: .bottom, spacing: 0) {
            SidebarFooterView()
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
            let c = appState.agents.count
            return c > 0 ? "\(c)" : nil
        case .routines:
            let c = appState.routines.count
            return c > 0 ? "\(c)" : nil
        case .skills:
            let c = appState.skills.count
            return c > 0 ? "\(c)" : nil
        case .logs:
            let errors = appState.routines.flatMap { $0.todayExecutions }.filter { $0.status == .failed }.count
            return errors > 0 ? "⚠ \(errors)" : nil
        case .changelog:
            let v = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String
            return v.map { "v\($0)" }
        default:
            return nil
        }
    }
}

// MARK: - Sidebar Footer

struct SidebarFooterView: View {
    @EnvironmentObject var appState: AppState

    @State private var updateAvailable = false
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
            Divider()
            HStack(spacing: Spacing.sm) {
                Button {
                    if updateAvailable { showUpdateConfirm = true }
                } label: {
                    HStack(spacing: 5) {
                        Text("v\(appVersion)")
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                        if isUpdating {
                            ProgressView()
                                .controlSize(.mini)
                                .frame(width: 10, height: 10)
                        } else if updateAvailable {
                            Circle()
                                .fill(.orange)
                                .frame(width: 6, height: 6)
                        }
                    }
                }
                .buttonStyle(.plain)
                .help(updateAvailable ? "Update available — click to pull & rebuild" : "Up to date")
                .disabled(isUpdating)

                Spacer()
            }
            .padding(.horizontal, Spacing.md)
            .padding(.vertical, Spacing.sm)
        }
        .background(.regularMaterial)
        .onAppear { checkForUpdates() }
        .confirmationDialog(
            "Update Available",
            isPresented: $showUpdateConfirm,
            titleVisibility: .visible
        ) {
            Button("Pull & Rebuild") { performUpdate() }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("The app will restart after pulling the latest changes from git.")
        }
    }

    private func checkForUpdates() {
        let path = repoPath
        Task.detached(priority: .background) {
            let result = runShell(
                "git -C \"\(path)\" fetch --quiet 2>/dev/null; " +
                "git -C \"\(path)\" log HEAD..origin/main --oneline 2>/dev/null | wc -l"
            )
            let count = Int(result.trimmingCharacters(in: .whitespacesAndNewlines)) ?? 0
            await MainActor.run { updateAvailable = count > 0 }
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

// MARK: - Changelog Sheet

struct ChangelogEntry: Identifiable {
    var id: String { hash }
    var hash: String
    var message: String

    var typeColor: Color {
        if message.hasPrefix("feat")     { return .statusBlue }
        if message.hasPrefix("fix")      { return .statusGreen }
        if message.hasPrefix("refactor") { return .purple }
        if message.hasPrefix("chore")    { return .secondary }
        return .primary
    }

    var shortHash: String { String(hash.prefix(7)) }
}

// MARK: - Changelog Page View (full tab, not a modal)

struct ChangelogPageView: View {
    @EnvironmentObject var appState: AppState
    @State private var entries: [ChangelogEntry] = []

    private var repoPath: String {
        URL(fileURLWithPath: appState.vaultPath).deletingLastPathComponent().path
    }

    var body: some View {
        Group {
            if entries.isEmpty {
                VStack(spacing: Spacing.md) {
                    Image(systemName: "doc.text.magnifyingglass")
                        .font(.system(size: 36))
                        .foregroundStyle(.tertiary)
                    Text("No git history found")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                List(entries) { entry in
                    HStack(alignment: .top, spacing: Spacing.sm) {
                        Text(entry.shortHash)
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundStyle(.tertiary)
                            .frame(width: 52, alignment: .leading)

                        Text(entry.message)
                            .font(.caption)
                            .foregroundStyle(entry.typeColor)
                            .lineLimit(2)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .listRowSeparator(.visible)
                }
                .listStyle(.plain)
                .scrollContentBackground(.hidden)
            }
        }
        .background(Color(.windowBackgroundColor))
        .navigationTitle("Changelog")
        .task { loadChangelog() }
    }

    private func loadChangelog() {
        let path = repoPath
        let raw = runShell(
            "git -C \"\(path)\" log --oneline --no-decorate -60 2>/dev/null"
        )
        entries = raw
            .components(separatedBy: "\n")
            .filter { !$0.isEmpty }
            .compactMap { line -> ChangelogEntry? in
                let parts = line.split(separator: " ", maxSplits: 1)
                guard parts.count == 2 else { return nil }
                return ChangelogEntry(hash: String(parts[0]), message: String(parts[1]))
            }
    }
}
