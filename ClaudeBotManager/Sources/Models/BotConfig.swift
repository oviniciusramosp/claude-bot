import Foundation

struct BotConfig: Sendable {
    var telegramBotToken: String
    var telegramChatId: String      // comma-separated IDs
    var claudePath: String
    var claudeWorkspace: String
    var ttsEngine: String           // "edge-tts" or "say"
    var zaiApiKey: String
    var zaiBaseUrl: String
    var modelFallbackChain: String  // comma-separated model IDs

    static var defaults: BotConfig {
        BotConfig(
            telegramBotToken: "",
            telegramChatId: "",
            claudePath: "/opt/homebrew/bin/claude",
            claudeWorkspace: FileManager.default.homeDirectoryForCurrentUser.path,
            ttsEngine: "edge-tts",
            zaiApiKey: "",
            zaiBaseUrl: "https://api.z.ai/api/anthropic",
            modelFallbackChain: "opus,glm-5.1,sonnet,glm-4.7,haiku"
        )
    }
}
