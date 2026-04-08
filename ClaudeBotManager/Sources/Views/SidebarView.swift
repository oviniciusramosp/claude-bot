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
                sidebarLabel(.sessions)
            }
            Section("System") {
                sidebarLabel(.logs)
                sidebarLabel(.settings)
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
            Text(item.rawValue)
        } icon: {
            ZStack(alignment: .topTrailing) {
                Image(systemName: item.symbol)
                if showBadge(for: item) {
                    Circle()
                        .fill(Color.statusRed)
                        .frame(width: 7, height: 7)
                        .offset(x: 5, y: -5)
                }
            }
        }
        .tag(item)
    }

    private func showBadge(for item: SidebarItem) -> Bool {
        switch item {
        case .dashboard:
            return !appState.isRunning
        case .routines:
            return appState.routines.contains { r in
                r.lastExecution?.status == .failed
            }
        default:
            return false
        }
    }
}

// MARK: - Sidebar Footer

struct SidebarFooterView: View {
    @EnvironmentObject var appState: AppState

    @State private var updateAvailable = false
    @State private var isUpdating = false
    @State private var showUpdateConfirm = false
    @State private var showChangelog = false
    @State private var changelog: [ChangelogEntry] = []

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
                // Version label + update dot
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

                // Changelog button
                Button("Changelog") {
                    loadChangelog()
                    showChangelog = true
                }
                .font(.caption2)
                .foregroundStyle(.tertiary)
                .buttonStyle(.plain)
                .help("View recent git commits")
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
        .sheet(isPresented: $showChangelog) {
            ChangelogSheet(entries: changelog, repoPath: repoPath)
        }
    }

    // MARK: - Git operations

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
            // App restarts via build-app.sh — isUpdating stays true, that's OK
        }
    }

    private func loadChangelog() {
        let path = repoPath
        let raw = runShell(
            "git -C \"\(path)\" log --oneline --no-decorate -40 2>/dev/null"
        )
        changelog = raw
            .components(separatedBy: "\n")
            .filter { !$0.isEmpty }
            .compactMap { line -> ChangelogEntry? in
                let parts = line.split(separator: " ", maxSplits: 1)
                guard parts.count == 2 else { return nil }
                return ChangelogEntry(hash: String(parts[0]), message: String(parts[1]))
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

struct ChangelogSheet: View {
    var entries: [ChangelogEntry]
    var repoPath: String

    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 0) {
            // Header
            HStack {
                Label("Changelog", systemImage: "clock.arrow.2.circlepath")
                    .font(.headline)
                Spacer()
                Button { dismiss() } label: {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundStyle(.secondary)
                        .font(.title3)
                }
                .buttonStyle(.plain)
            }
            .padding(Spacing.lg)

            Divider()

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
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        ForEach(entries) { entry in
                            HStack(alignment: .top, spacing: Spacing.sm) {
                                Text(entry.shortHash)
                                    .font(.system(size: 10, design: .monospaced))
                                    .foregroundStyle(.tertiary)
                                    .frame(width: 52, alignment: .leading)
                                    .padding(.top, 1)

                                Text(entry.message)
                                    .font(.caption)
                                    .foregroundStyle(entry.typeColor)
                                    .lineLimit(2)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }
                            .padding(.vertical, Spacing.xs)
                            .padding(.horizontal, Spacing.lg)

                            Divider()
                                .padding(.leading, Spacing.lg + 52 + Spacing.sm)
                        }
                    }
                }
            }
        }
        .frame(width: 420, height: 400)
        .background(Color(.windowBackgroundColor))
    }
}
