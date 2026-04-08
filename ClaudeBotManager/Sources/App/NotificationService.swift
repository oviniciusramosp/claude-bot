import Foundation
import UserNotifications

@MainActor
final class NotificationService {
    static let shared = NotificationService()

    func requestPermission() async {
        let center = UNUserNotificationCenter.current()
        _ = try? await center.requestAuthorization(options: [.alert, .sound, .badge])
    }

    func notifyRoutineFailure(routineName: String, timeSlot: String, error: String?) {
        let content = UNMutableNotificationContent()
        content.title = "Routine Failed"
        content.body = "'\(routineName)' at \(timeSlot)\(error.map { ": \($0.prefix(100))" } ?? "")"
        content.sound = .default
        schedule(content, identifier: "routine-\(routineName)-\(timeSlot)")
    }

    func notifyBotStopped() {
        let content = UNMutableNotificationContent()
        content.title = "Claude Bot Stopped"
        content.body = "The bot is no longer running. Tap to restart."
        content.sound = .default
        schedule(content, identifier: "bot-stopped")
    }

    func notifyBotStarted() {
        let content = UNMutableNotificationContent()
        content.title = "Claude Bot Running"
        content.body = "The bot is back online."
        schedule(content, identifier: "bot-started")
    }

    private func schedule(_ content: UNMutableNotificationContent, identifier: String) {
        let request = UNNotificationRequest(
            identifier: identifier,
            content: content,
            trigger: nil  // deliver immediately
        )
        UNUserNotificationCenter.current().add(request)
    }
}
