import SwiftUI

enum SidebarItem: String, CaseIterable, Identifiable {
    case dashboard = "Dashboard"
    case agents = "Agents"
    case routines = "Routines"
    case sessions = "Sessions"
    case logs = "Logs"
    case settings = "Settings"

    var id: String { rawValue }

    var symbol: String {
        switch self {
        case .dashboard: "gauge.open.with.lines.needle.33percent"
        case .agents: "person.2.fill"
        case .routines: "clock.arrow.2.circlepath"
        case .sessions: "list.bullet.rectangle"
        case .logs: "exclamationmark.triangle"
        case .settings: "gearshape"
        }
    }
}

struct ContentView: View {
    @EnvironmentObject var appState: AppState
    @State private var selection: SidebarItem = .dashboard

    var body: some View {
        ZStack {
            NavigationSplitView(columnVisibility: .constant(.all)) {
                SidebarView(selection: $selection)
            } detail: {
                switch selection {
                case .dashboard: DashboardView()
                case .agents: AgentListView()
                case .routines: RoutineListView()
                case .sessions: SessionBrowserView()
                case .logs: LogViewerView()
                case .settings: SettingsView()
                }
            }
            .navigationSplitViewStyle(.prominentDetail)

            if !appState.isConfigured {
                OnboardingView()
                    .environmentObject(appState)
                    .transition(.opacity.combined(with: .scale(scale: 0.96)))
            }
        }
        .animation(.easeInOut(duration: 0.3), value: appState.isConfigured)
    }
}
