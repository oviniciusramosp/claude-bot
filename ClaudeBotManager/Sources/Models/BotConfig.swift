import Foundation

struct BotConfig: Sendable {
    var telegramBotToken: String
    var telegramChatId: String      // comma-separated IDs
    var claudePath: String
    var claudeWorkspace: String
    var ttsEngine: String           // "edge-tts" or "say"
    var zaiApiKey: String
    var zaiBaseUrl: String
    var codexPath: String           // OpenAI Codex CLI binary (ChatGPT Plus/Pro)
    var modelFallbackChain: String  // comma-separated model IDs
    var showSignature: Bool

    static var defaults: BotConfig {
        BotConfig(
            telegramBotToken: "",
            telegramChatId: "",
            claudePath: "/opt/homebrew/bin/claude",
            claudeWorkspace: FileManager.default.homeDirectoryForCurrentUser.path,
            ttsEngine: "edge-tts",
            zaiApiKey: "",
            zaiBaseUrl: "https://api.z.ai/api/anthropic",
            codexPath: "/opt/homebrew/bin/codex",
            modelFallbackChain: "opus,glm-5.1,sonnet,glm-4.7,haiku",
            showSignature: true
        )
    }
}
