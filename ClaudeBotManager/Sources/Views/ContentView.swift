import SwiftUI

enum SidebarItem: String, CaseIterable, Identifiable {
    case dashboard = "Dashboard"
    case agents = "Agents"
    case routines = "Routines"
    case skills = "Skills"
    case sessions = "Sessions"
    case logs = "Logs"
    case settings = "Settings"
    case changelog = "Changelog"

    var id: String { rawValue }

    var symbol: String {
        switch self {
        case .dashboard: "square.grid.2x2.fill"
        case .agents: "person.2"
        case .routines: "clock.arrow.2.circlepath"
        case .skills: "bolt"
        case .sessions: "folder"
        case .logs: "info.triangle"
        case .settings: "gear"
        case .changelog: "cloud"
        }
    }
}

struct ContentView: View {
    @EnvironmentObject var appState: AppState
    @State private var selection: SidebarItem = .dashboard
    @State private var columnVisibility: NavigationSplitViewVisibility = .all

    var body: some View {
        ZStack {
            NavigationSplitView(columnVisibility: $columnVisibility) {
                SidebarView(selection: $selection)
            } detail: {
                switch selection {
                case .dashboard: DashboardView()
                case .agents: AgentListView()
                case .routines: RoutineListView()
                case .skills: SkillListView()
                case .sessions: SessionBrowserView()
                case .logs: LogViewerView()
                case .settings: SettingsView()
                case .changelog: ChangelogPageView()
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
