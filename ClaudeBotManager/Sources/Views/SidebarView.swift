import SwiftUI

struct SidebarView: View {
    @Binding var selection: SidebarItem
    @EnvironmentObject var appState: AppState

    var body: some View {
        List(SidebarItem.allCases, id: \.self, selection: $selection) { item in
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
        .listStyle(.sidebar)
        .navigationTitle("Claude Bot")
        .frame(minWidth: 180, idealWidth: 200)
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
