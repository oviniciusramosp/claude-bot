import Foundation

struct BotConfig: Sendable {
    var telegramBotToken: String
    var telegramChatId: String      // comma-separated IDs
    var claudePath: String
    var claudeWorkspace: String
    var ttsEngine: String           // "edge-tts" or "say"

    static var defaults: BotConfig {
        BotConfig(
            telegramBotToken: "",
            telegramChatId: "",
            claudePath: "/opt/homebrew/bin/claude",
            claudeWorkspace: FileManager.default.homeDirectoryForCurrentUser.path,
            ttsEngine: "edge-tts"
        )
    }
}
