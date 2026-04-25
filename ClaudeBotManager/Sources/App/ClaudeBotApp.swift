import SwiftUI
import AppKit

@main
struct ClaudeBotApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    @StateObject private var appState = AppState()

    var body: some Scene {
        Window("Claude Bot Manager", id: "main") {
            ContentView()
                .environmentObject(appState)
                .frame(minWidth: 900, minHeight: 600)
                .onAppear { updateDockBadge(running: appState.isRunning) }
                .onChange(of: appState.isRunning) { _, running in
                    updateDockBadge(running: running)
                }
        }
        .windowStyle(.hiddenTitleBar)
        .defaultSize(width: 1100, height: 700)
        .commands {
            CommandGroup(replacing: .appInfo) {}
        }

        MenuBarExtra {
            MenuBarView()
                .environmentObject(appState)
        } label: {
            MenuBarLabel()
                .environmentObject(appState)
        }
        .menuBarExtraStyle(.window)
    }
}

/// Sets the Dock tile badge based on bot state.
/// `nil` clears the badge (bot online); a short label is shown when offline.
@MainActor
private func updateDockBadge(running: Bool) {
    NSApp.dockTile.badgeLabel = running ? nil : "OFF"
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        // Show in Dock as a regular app (also keeps the MenuBarExtra item).
        NSApp.setActivationPolicy(.regular)
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag {
            for window in NSApp.windows {
                window.makeKeyAndOrderFront(nil)
            }
        }
        return true
    }
}
