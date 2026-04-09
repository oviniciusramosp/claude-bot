import Foundation

struct BotConfig: Sendable {
    var telegramBotToken: String
    var telegramChatId: String      // comma-separated IDs
    var claudePath: String
    var claudeWorkspace: String
    var claudeAccountEmail: String

    static var defaults: BotConfig {
        BotConfig(
            telegramBotToken: "",
            telegramChatId: "",
            claudePath: "/opt/homebrew/bin/claude",
            claudeWorkspace: FileManager.default.homeDirectoryForCurrentUser.path,
            claudeAccountEmail: ""
        )
    }
}
