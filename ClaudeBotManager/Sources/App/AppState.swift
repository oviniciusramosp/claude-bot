import SwiftUI
import Foundation

@MainActor
final class AppState: ObservableObject {
    // Bot
    @Published var botStatus: BotProcessService.BotStatus = .unknown
    @Published var claudeUsage: ClaudeUsage = .unavailable

    // Data
    @Published var mainAgent: Agent = Agent(id: "main", name: "Main", icon: "🤖",
        description: "Bot padrão — nenhum agente específico ativo",
        personality: "", model: "sonnet", tags: [], isDefault: true,
        source: nil, sourceId: nil, instructions: "", created: "", updated: "")
    @Published var agents: [Agent] = []
    @Published var routines: [Routine] = []
    @Published var skills: [Skill] = []
    @Published var sessions: SessionsFile = SessionsFile(sessions: [:], activeSession: nil, cumulativeTurns: 0)
    @Published var contexts: [ContextService.TopicContext] = []
    @Published var recentLogs: [LogEntry] = []

    // Config
    @Published var botConfig: BotConfig = .defaults
    @Published var vaultPath: String = ""
    @Published var dataDir: String = ""

    // Services
    private var vaultService: VaultService?
    private var sessionService: SessionService?
    private var routineStateService: RoutineStateService?
    private var logService: LogService?
    private var botProcessService: BotProcessService?
    private var claudeUsageService: ClaudeUsageService?
    private var contextService: ContextService?
    private let fileWatcher = FileWatcher()

    // Timers
    private var statusTimer: Timer?
    private var usageTimer: Timer?

    init() {
        setupPaths()
        setupServices()
        Task { await self.loadAll() }
        startTimers()
    }

    private func setupPaths() {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        dataDir = "\(home)/.claude-bot"
        // Try to find vault relative to the script location
        // Default: ~/claude-bot/vault
        vaultPath = "\(home)/claude-bot/vault"
        if !FileManager.default.fileExists(atPath: vaultPath) {
            // Fallback: same dir as executable
            vaultPath = "\(home)/vault"
        }
    }

    private func setupServices() {
        vaultService = VaultService(vaultPath: vaultPath)
        sessionService = SessionService(dataDir: dataDir)
        routineStateService = RoutineStateService(dataDir: dataDir)
        logService = LogService(dataDir: dataDir)
        botProcessService = BotProcessService()
        claudeUsageService = ClaudeUsageService()
        contextService = ContextService(dataDir: dataDir)

        // Load config from .env
        loadConfig()

        // Watch key files for changes
        watchFiles()
    }

    private func watchFiles() {
        let refresh: @Sendable () -> Void = { [weak self] in
            Task { @MainActor in await self?.loadAll() }
        }

        for path in [
            "\(dataDir)/sessions.json",
            "\(dataDir)/contexts.json",
            "\(vaultPath)/Agents",
            "\(vaultPath)/Routines",
            "\(vaultPath)/Skills"
        ] {
            fileWatcher.watch(path: path, onChange: refresh)
        }

        // Watch routines-state directory
        let stateDir = "\(dataDir)/routines-state"
        fileWatcher.watch(path: stateDir, onChange: refresh)
    }

    func loadAll() async {
        await loadMainAgent()
        await loadAgents()
        await loadRoutines()
        await loadSkills()
        await loadSessions()
        await loadContexts()
        await refreshBotStatus()
        if let ls = logService { recentLogs = await ls.loadRecent(lines: 200) }
    }

    func loadMainAgent() async {
        guard let vs = vaultService else { return }
        mainAgent = await vs.loadMainAgent()
    }

    func saveMainAgent(_ agent: Agent) async throws {
        try await vaultService?.saveMainAgent(instructions: agent.instructions)
        await loadMainAgent()
    }

    func loadAgents() async {
        guard let vs = vaultService else { return }
        do {
            let loaded = try await vs.loadAgents()
            agents = loaded
        } catch {}
    }

    func loadRoutines() async {
        guard let vs = vaultService, let rs = routineStateService else { return }
        do {
            var loaded = try await vs.loadRoutines()
            let todayState = await rs.loadTodayState()
            for i in loaded.indices {
                let name = loaded[i].id
                let slots = todayState[name] ?? [:]
                loaded[i].todayExecutions = slots.values.sorted {
                    ($0.startedAt ?? .distantPast) < ($1.startedAt ?? .distantPast)
                }
            }
            routines = loaded
        } catch {}
    }

    func loadSessions() async {
        guard let ss = sessionService else { return }
        do { sessions = try await ss.loadSessions() } catch {}
    }

    func loadContexts() async {
        guard let cs = contextService else { return }
        contexts = await cs.loadContexts()
    }

    func refreshBotStatus() async {
        guard let bs = botProcessService else { return }
        botStatus = await bs.status()
    }

    func refreshUsage() async {
        guard let us = claudeUsageService else { return }
        claudeUsage = await us.fetchUsage()
    }

    func startBot() async {
        await botProcessService?.start()
        try? await Task.sleep(nanoseconds: 1_500_000_000)
        await refreshBotStatus()
    }

    func stopBot() async {
        await botProcessService?.stop()
        try? await Task.sleep(nanoseconds: 1_000_000_000)
        await refreshBotStatus()
    }

    func restartBot() async {
        await botProcessService?.restart()
        try? await Task.sleep(nanoseconds: 2_000_000_000)
        await refreshBotStatus()
    }

    func saveAgent(_ agent: Agent) async throws {
        try await vaultService?.saveAgent(agent)
        await loadAgents()
    }

    func deleteAgent(id: String) async throws {
        try await vaultService?.deleteAgent(id: id)
        await loadAgents()
    }

    func saveRoutine(_ routine: Routine) async throws {
        try await vaultService?.saveRoutine(routine)
        await loadRoutines()
    }

    @discardableResult
    func dryRunRoutine(_ routine: Routine) async throws -> RoutineExecution? {
        // Save first so the bot picks up any edits
        try await vaultService?.saveRoutine(routine)
        await loadRoutines()
        // Trigger via control server
        let url = URL(string: "http://127.0.0.1:27182/routine/run")!
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONSerialization.data(withJSONObject: ["name": routine.id, "time_slot": "dry-run"])
        let sessionConfig = URLSessionConfiguration.default
        sessionConfig.timeoutIntervalForRequest = 10
        let session = URLSession(configuration: sessionConfig)
        let (_, response) = try await session.data(for: req)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw URLError(.badServerResponse)
        }
        // Poll state file until bot marks it done (max 3 min)
        let result = await routineStateService?.pollUntilDone(routineId: routine.id, timeSlot: "dry-run")
        await loadRoutines()
        return result
    }

    func deleteRoutine(id: String) async throws {
        try await vaultService?.deleteRoutine(id: id)
        await loadRoutines()
    }

    func loadSkills() async {
        guard let vs = vaultService else { return }
        do {
            skills = try await vs.loadSkills()
        } catch {}
    }

    func deleteSkill(id: String) async throws {
        try await vaultService?.deleteSkill(id: id)
        await loadSkills()
    }

    func routineHistory(id: String) async -> [RoutineExecution] {
        await routineStateService?.loadHistory(for: id) ?? []
    }

    func loadPipelineStepDefs(routineId: String, promptBody: String) async -> [PipelineStepDef] {
        await vaultService?.loadPipelineStepDefs(routineId: routineId, promptBody: promptBody) ?? []
    }

    func allRoutineHistory() async -> [RoutineExecution] {
        await routineStateService?.loadAllHistory() ?? []
    }

    var botStatusLabel: String {
        switch botStatus {
        case .running(_, let uptime):
            return "Running · \(formatUptime(uptime))"
        case .stopped:
            return "Stopped"
        case .unknown:
            return "Unknown"
        }
    }

    var isRunning: Bool {
        if case .running = botStatus { return true }
        return false
    }

    var isConfigured: Bool {
        !botConfig.telegramBotToken.isEmpty &&
        FileManager.default.fileExists(atPath: botConfig.claudePath)
    }

    private func startTimers() {
        statusTimer = Timer.scheduledTimer(withTimeInterval: 15, repeats: true) { [weak self] _ in
            Task { @MainActor in await self?.refreshBotStatus() }
        }
        usageTimer = Timer.scheduledTimer(withTimeInterval: 300, repeats: true) { [weak self] _ in
            Task { @MainActor in await self?.refreshUsage() }
        }
        // Initial usage fetch
        Task { await refreshUsage() }
    }

    // ~/claude-bot/.env — the bot's actual config file (parent of vault/)
    private var botEnvPath: String {
        URL(fileURLWithPath: vaultPath).deletingLastPathComponent()
            .appendingPathComponent(".env").path
    }

    private func loadConfig() {
        var config = BotConfig.defaults
        // Read bot's .env (~/claude-bot/.env) — contains TELEGRAM_* and CLAUDE_*
        for envPath in [botEnvPath, "\(vaultPath)/.env"] {
            guard let content = try? String(contentsOfFile: envPath, encoding: .utf8) else { continue }
            for line in content.components(separatedBy: "\n") {
                let trimmed = line.trimmingCharacters(in: .whitespaces)
                guard !trimmed.hasPrefix("#"), trimmed.contains("=") else { continue }
                let parts = trimmed.components(separatedBy: "=")
                guard parts.count >= 2 else { continue }
                let key = parts[0].trimmingCharacters(in: .whitespaces)
                let value = parts[1...].joined(separator: "=").trimmingCharacters(in: .whitespaces)
                // Only set if not already found in a higher-priority file
                switch key {
                case "TELEGRAM_BOT_TOKEN" where config.telegramBotToken.isEmpty:
                    config.telegramBotToken = value
                case "TELEGRAM_CHAT_ID" where config.telegramChatId.isEmpty:
                    config.telegramChatId = value
                case "CLAUDE_PATH" where config.claudePath == BotConfig.defaults.claudePath:
                    config.claudePath = value
                case "CLAUDE_WORKSPACE" where config.claudeWorkspace == BotConfig.defaults.claudeWorkspace:
                    config.claudeWorkspace = value
                default: break
                }
            }
        }
        botConfig = config
    }

    func saveConfig(_ config: BotConfig) throws {
        // Save bot config to ~/claude-bot/.env (the file the bot reads)
        let envPath = botEnvPath
        var lines: [String] = [
            "TELEGRAM_BOT_TOKEN=\(config.telegramBotToken)",
            "TELEGRAM_CHAT_ID=\(config.telegramChatId)",
            "CLAUDE_PATH=\(config.claudePath)",
            "CLAUDE_WORKSPACE=\(config.claudeWorkspace)"
        ]
        // Preserve any extra keys already in the file
        if let existing = try? String(contentsOfFile: envPath, encoding: .utf8) {
            let knownKeys = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "CLAUDE_PATH", "CLAUDE_WORKSPACE"]
            for line in existing.components(separatedBy: "\n") {
                let trimmed = line.trimmingCharacters(in: .whitespaces)
                if trimmed.hasPrefix("#") { continue }
                let key = trimmed.components(separatedBy: "=").first ?? ""
                if !knownKeys.contains(key) && !key.isEmpty && trimmed.contains("=") {
                    lines.append(line)
                }
            }
        }
        try lines.joined(separator: "\n").write(toFile: envPath, atomically: true, encoding: .utf8)
        botConfig = config
    }

    private func formatUptime(_ t: TimeInterval) -> String {
        let s = Int(t)
        if s < 60 { return "\(s)s" }
        if s < 3600 { return "\(s/60)m" }
        if s < 86400 { return "\(s/3600)h \((s%3600)/60)m" }
        return "\(s/86400)d \((s%86400)/3600)h"
    }
}
