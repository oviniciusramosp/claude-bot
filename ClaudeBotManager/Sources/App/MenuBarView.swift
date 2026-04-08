import SwiftUI
import AppKit

struct MenuBarLabel: View {
    @EnvironmentObject var appState: AppState

    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: "cpu")
                .symbolRenderingMode(.hierarchical)
                .foregroundStyle(appState.isRunning ? Color.statusGreen : Color.statusRed)
        }
    }
}

struct MenuBarView: View {
    @EnvironmentObject var appState: AppState

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Header
            HStack {
                Image(systemName: "cpu")
                    .foregroundStyle(appState.isRunning ? Color.statusGreen : Color.statusRed)
                Text("Claude Bot")
                    .font(.headline)
                Spacer()
                StatusDot(isRunning: appState.isRunning)
            }
            .padding(.horizontal, 14)
            .padding(.top, 14)
            .padding(.bottom, 8)

            Divider()

            // Status
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text("Status")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Spacer()
                    Text(appState.botStatusLabel)
                        .font(.caption.monospacedDigit())
                }

                if appState.claudeUsage.isAvailable {
                    HStack {
                        Text("Session")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Spacer()
                        UsageMiniBar(percent: appState.claudeUsage.sessionPercent)
                        Text(appState.claudeUsage.sessionLabel)
                            .font(.caption2.monospacedDigit())
                            .frame(width: 32, alignment: .trailing)
                    }
                    HStack {
                        Text("Week")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Spacer()
                        UsageMiniBar(percent: appState.claudeUsage.weeklyPercent)
                        Text(appState.claudeUsage.weeklyLabel)
                            .font(.caption2.monospacedDigit())
                            .frame(width: 32, alignment: .trailing)
                    }
                }
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 8)

            Divider()

            // Actions
            VStack(spacing: 2) {
                MenuBarButton(title: "Open Manager", symbol: "macwindow") {
                    openMainWindow()
                }

                if appState.isRunning {
                    MenuBarButton(title: "Restart Bot", symbol: "arrow.trianglehead.2.clockwise") {
                        Task { await appState.restartBot() }
                    }
                    MenuBarButton(title: "Stop Bot", symbol: "stop.fill", destructive: true) {
                        Task { await appState.stopBot() }
                    }
                } else {
                    MenuBarButton(title: "Start Bot", symbol: "play.fill") {
                        Task { await appState.startBot() }
                    }
                }
            }
            .padding(.horizontal, 6)
            .padding(.vertical, 4)

            Divider()

            // Today's routines summary
            if !appState.routines.isEmpty {
                let todayExecs = appState.routines.flatMap { $0.todayExecutions }
                let completed = todayExecs.filter { $0.status == .completed }.count
                let failed = todayExecs.filter { $0.status == .failed }.count
                let running = todayExecs.filter { $0.status == .running }.count

                HStack(spacing: 10) {
                    Text("Routines today:")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    if completed > 0 {
                        Label("\(completed)", systemImage: "checkmark.circle.fill")
                            .foregroundStyle(Color.statusGreen)
                            .font(.caption2)
                    }
                    if failed > 0 {
                        Label("\(failed)", systemImage: "xmark.circle.fill")
                            .foregroundStyle(Color.statusRed)
                            .font(.caption2)
                    }
                    if running > 0 {
                        Label("\(running)", systemImage: "arrow.trianglehead.2.clockwise")
                            .foregroundStyle(Color.statusBlue)
                            .font(.caption2)
                    }
                }
                .padding(.horizontal, 14)
                .padding(.vertical, 6)

                Divider()
            }

            // Quit
            MenuBarButton(title: "Quit Claude Bot Manager", symbol: "power") {
                NSApplication.shared.terminate(nil)
            }
            .padding(.horizontal, 6)
            .padding(.bottom, 6)
        }
        .frame(width: 260)
    }

    private func openMainWindow() {
        NSApp.activate(ignoringOtherApps: true)
        for window in NSApp.windows where window.identifier?.rawValue == "main" {
            window.makeKeyAndOrderFront(nil)
            return
        }
        // If no window found, open via open URL
        NSApp.windows.first?.makeKeyAndOrderFront(nil)
    }
}

struct UsageMiniBar: View {
    var percent: Double

    private var color: Color {
        if percent < 0.6 { return .statusGreen }
        if percent < 0.85 { return .statusYellow }
        return .statusRed
    }

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                RoundedRectangle(cornerRadius: 2)
                    .fill(Color.primary.opacity(0.1))
                RoundedRectangle(cornerRadius: 2)
                    .fill(color)
                    .frame(width: geo.size.width * min(percent, 1.0))
            }
        }
        .frame(width: 60, height: 5)
    }
}

struct MenuBarButton: View {
    var title: String
    var symbol: String
    var destructive: Bool = false
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            Label(title, systemImage: symbol)
                .font(.callout)
                .foregroundStyle(destructive ? Color.statusRed : Color.primary)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 8)
                .padding(.vertical, 6)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .clipShape(RoundedRectangle(cornerRadius: 6))
    }
}
