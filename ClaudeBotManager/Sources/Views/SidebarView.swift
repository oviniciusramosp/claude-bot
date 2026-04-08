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
