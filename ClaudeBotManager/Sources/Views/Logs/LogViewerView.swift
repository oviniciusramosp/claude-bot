import SwiftUI

struct LogViewerView: View {
    @EnvironmentObject var appState: AppState
    @State private var entries: [LogEntry] = []
    @State private var filterLevel: LogEntry.Level? = nil
    @State private var searchText = ""
    @State private var autoScroll = true
    @State private var scrollProxy: ScrollViewProxy? = nil

    private var filtered: [LogEntry] {
        entries.filter { entry in
            let levelMatch = filterLevel == nil || entry.level == filterLevel
            let searchMatch = searchText.isEmpty || entry.message.localizedCaseInsensitiveContains(searchText)
            return levelMatch && searchMatch
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            // Toolbar
            HStack(spacing: 10) {
                // Level filters
                HStack(spacing: 6) {
                    FilterChip(label: "All", isSelected: filterLevel == nil) {
                        filterLevel = nil
                    }
                    ForEach(LogEntry.Level.allCases, id: \.self) { level in
                        FilterChip(label: level.label, isSelected: filterLevel == level, color: levelColor(level)) {
                            filterLevel = filterLevel == level ? nil : level
                        }
                    }
                }

                Spacer()

                // Search
                HStack {
                    Image(systemName: "magnifyingglass")
                        .foregroundStyle(.secondary)
                        .font(.caption)
                    TextField("Search logs…", text: $searchText)
                        .textFieldStyle(.plain)
                        .font(.caption)
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 5)
                .background(Color.primary.opacity(0.06))
                .clipShape(Capsule())
                .frame(width: 200)

                Toggle("Auto-scroll", isOn: $autoScroll)
                    .font(.caption)
                    .toggleStyle(.switch)
                    .controlSize(.mini)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .background(Color(.windowBackgroundColor))

            Divider()

            // Log list
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 2) {
                        ForEach(filtered) { entry in
                            LogEntryRow(entry: entry)
                                .id(entry.id)
                        }
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                }
                .onAppear {
                    scrollProxy = proxy
                    entries = appState.recentLogs
                }
                .onChange(of: filtered.count) { _, _ in
                    if autoScroll, let last = filtered.last {
                        withAnimation { proxy.scrollTo(last.id, anchor: .bottom) }
                    }
                }
            }
        }
        .navigationTitle("Logs")
        .toolbar {
            ToolbarItem {
                Button {
                    entries = appState.recentLogs
                } label: {
                    Label("Refresh", systemImage: "arrow.clockwise")
                }
            }
            ToolbarItem {
                Button {
                    NSWorkspace.shared.open(
                        URL(fileURLWithPath: appState.dataDir + "/bot.log")
                    )
                } label: {
                    Label("Open in Finder", systemImage: "doc.text")
                }
            }
        }
    }

    private func levelColor(_ level: LogEntry.Level) -> Color {
        switch level {
        case .error: return .statusRed
        case .warning: return .statusYellow
        case .info: return .statusBlue
        case .debug: return .secondary
        }
    }
}

struct LogEntryRow: View {
    var entry: LogEntry

    private var levelColor: Color {
        switch entry.level {
        case .error: return Color.statusRed
        case .warning: return Color.statusYellow
        case .info: return Color.primary.opacity(0.7)
        case .debug: return Color(.tertiaryLabelColor)
        }
    }

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Text(entry.timestamp, format: .dateTime.hour().minute().second())
                .font(.system(.caption2, design: .monospaced))
                .foregroundStyle(.tertiary)
                .frame(width: 70, alignment: .leading)

            Text(entry.level.rawValue)
                .font(.system(.caption2, design: .monospaced).bold())
                .foregroundStyle(levelColor)
                .frame(width: 52, alignment: .leading)

            Text(entry.message)
                .font(.system(.caption, design: .monospaced))
                .foregroundStyle(entry.level == .error ? Color.statusRed : Color.primary)
                .textSelection(.enabled)
                .lineLimit(entry.level == .error ? nil : 2)
        }
        .padding(.vertical, 2)
        .padding(.horizontal, 6)
        .background(entry.level == .error ? Color.statusRed.opacity(0.06) :
                    entry.level == .warning ? Color.statusYellow.opacity(0.04) : Color.clear)
        .clipShape(RoundedRectangle(cornerRadius: 4))
    }
}

struct FilterChip: View {
    var label: String
    var isSelected: Bool
    var color: Color = .statusBlue
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(label)
                .font(.caption2.bold())
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                .background(isSelected ? color.opacity(0.15) : Color.primary.opacity(0.06))
                .foregroundStyle(isSelected ? color : .secondary)
                .clipShape(Capsule())
        }
        .buttonStyle(.plain)
    }
}
