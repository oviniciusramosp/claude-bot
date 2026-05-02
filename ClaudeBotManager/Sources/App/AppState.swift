import SwiftUI
import Foundation
import Combine

@MainActor
final class AppState: ObservableObject {
    // Bot
    @Published var botStatus: BotProcessService.BotStatus = .unknown
    @Published var claudeUsage: ClaudeUsage = .unavailable
    @Published var zaiUsage: ZAIUsage = .empty
    @Published var gptUsage: GPTUsage = .empty
    @Published var activeRunners: Int = 0
    /// Whether the web dashboard service (port 27184) is reachable.
    @Published var webRunning: Bool = false

    // This week's total cost from ~/.claude-bot/costs.json — displayed as
    // the sidebar badge on the Usage row. Zero when the file is missing or
    // has no current week.
    @Published var weeklyCostUSD: Double = 0

    // Data
    @Published var agents: [Agent] = []

    /// v3.5: Main is a first-class agent that lives at `vault/main/` with its
    /// own `agent-main.md` hub file — no longer a synthetic placeholder. This
    /// computed property locates Main inside the loaded `agents` array so
    /// existing views can still read `appState.mainAgent.icon` etc. If Main
    /// hasn't been loaded yet (e.g. fresh install before migration), return a
    /// minimal fallback so the UI doesn't crash.
    var mainAgent: Agent {
        agents.first(where: { $0.id == "main" })
            ?? Agent(id: "main", name: "Main", icon: "🤖",
                     description: "Default bot agent (not yet initialized — run migrate_vault_per_agent.py)",
                     personality: "", model: "sonnet", color: "grey", tags: [],
                     isDefault: true, source: nil, sourceId: nil,
                     created: "", updated: "")
    }
    @Published var routines: [Routine] = []
    @Published var skills: [Skill] = []
    @Published var reactions: [Reaction] = []
    @Published var tunnel: TunnelService
    @Published var sessions: SessionsFile = SessionsFile(sessions: [:], activeSession: nil, cumulativeTurns: 0)
    @Published var contexts: [ContextService.TopicContext] = []
    @Published var recentLogs: [LogEntry] = []

    // Config
    @Published var botConfig: BotConfig = .defaults
    @Published var vaultEnvEntries: [VaultEnvEntry] = []
    @Published var vaultPath: String = ""
    @Published var dataDir: String = ""
    /// Universal vault rules (contents of `vault/CLAUDE.md`). Editable via
    /// Settings → Customization → Vault Rules. NOT specific to any agent.
    @Published var vaultClaudeMd: String = ""

    /// User-facing error message from the most recent failed operation (e.g.
    /// a routine delete that couldn't trash the step directory). Views bind
    /// an alert to this and clear it on dismissal. `nil` means no pending
    /// error to show.
    @Published var lastError: String?

    // Vault env internals (preserves comments/blanks on save)
    private var vaultEnvRawLines: [String] = []

    // Services
    private var vaultService: VaultService?
    private var sessionService: SessionService?
    private var routineStateService: RoutineStateService?
    private var logService: LogService?
    private var botProcessService: BotProcessService?
    private var claudeUsageService: ClaudeUsageService?
    private var zaiUsageService: ZAIUsageService?
    private var contextService: ContextService?
    private let fileWatcher = FileWatcher()

    // Timers
    private var statusTimer: Timer?
    private var usageTimer: Timer?

    // Dedup guard: prevents multiple concurrent loadAll() Tasks from piling up
    // when the FileWatcher fires for several watched paths in quick succession.
    private var loadAllTask: Task<Void, Never>?
    private static let maxRecentLogs = 500

    // Combine
    private var cancellables = Set<AnyCancellable>()

    init() {
        // Derive the tailscale-funnel.sh script path from the vault path.
        // AppState.setupPaths() may update vaultPath later, but TunnelService
        // only reads the script when invoked, so this resolves correctly as long
        // as ~/claude-bot is the repo root.
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        let scriptPath = "\(home)/claude-bot/scripts/tailscale-funnel.sh"
        let installPath = "\(home)/claude-bot/scripts/tailscale-install.sh"
        self.tunnel = TunnelService(
            webhookPort: 27183,
            scriptPath: scriptPath,
            installScriptPath: installPath
        )
        setupPaths()
        setupServices()
        // Forward nested ObservableObject changes so SwiftUI views that observe
        // AppState also re-render when `tunnel`'s @Published properties change.
        tunnel.objectWillChange
            .sink { [weak self] _ in self?.objectWillChange.send() }
            .store(in: &cancellables)
        // Auto-redetect tunnel state when the app becomes active (e.g. user came
        // back from installing/logging into Tailscale in another app).
        NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)
            .sink { [weak self] _ in
                Task { @MainActor in await self?.tunnel.detect() }
            }
            .store(in: &cancellables)
        Task { await self.loadAll() }
        Task { await tunnel.detect() }
        startTimers()
        startLogStream()
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
        zaiUsageService = ZAIUsageService(dataDir: dataDir)
        contextService = ContextService(dataDir: dataDir)

        // Load config from .env files
        loadConfig()
        loadVaultEnv()

        // Watch key files for changes
        watchFiles()
    }

    private func watchFiles() {
        let refresh: @Sendable () -> Void = { [weak self] in
            Task { @MainActor in self?.scheduleLoadAll() }
        }

        // v3.5: every agent lives directly under the vault root as `<id>/`
        // with the hub file `agent-<id>.md`. Watching the vault root catches
        // new/removed agent directories; watching each detected agent's
        // Routines/Skills/Reactions/Journal catches item-level changes.
        var watchPaths: [String] = [
            "\(dataDir)/sessions.json",
            "\(dataDir)/contexts.json",
            "\(dataDir)/reaction-stats.json",
            vaultPath,  // catches top-level vault changes (new agent dir created/deleted)
        ]
        // Reserved top-level names that are NEVER agents (mirrors
        // VaultService.reservedVaultNames so the two stay in sync).
        let reservedVaultNames: Set<String> = [
            "README.md", "CLAUDE.md", "Tooling.md", ".env",
            ".graphs", ".obsidian", ".claude", "Images", "__pycache__",
            "Agents",
        ]
        if let entries = try? FileManager.default.contentsOfDirectory(atPath: vaultPath) {
            for entry in entries {
                if entry.hasPrefix(".") { continue }
                if reservedVaultNames.contains(entry) { continue }
                let agentBase = "\(vaultPath)/\(entry)"
                var isDir: ObjCBool = false
                guard FileManager.default.fileExists(atPath: agentBase, isDirectory: &isDir),
                      isDir.boolValue else { continue }
                // v3.5 hub `agent-<id>.md` (or legacy `agent-info.md` mid-migration)
                let hub = "\(agentBase)/agent-\(entry).md"
                let legacyHub = "\(agentBase)/agent-info.md"
                guard FileManager.default.fileExists(atPath: hub)
                        || FileManager.default.fileExists(atPath: legacyHub) else {
                    continue
                }
                for sub in ["Routines", "Skills", "Reactions", "Journal"] {
                    let p = "\(agentBase)/\(sub)"
                    if FileManager.default.fileExists(atPath: p) {
                        watchPaths.append(p)
                    }
                }
            }
        }
        for path in watchPaths {
            fileWatcher.watch(path: path, onChange: refresh)
        }

        // Watch vault .env for external changes
        let vaultEnvRefresh: @Sendable () -> Void = { [weak self] in
            Task { @MainActor in self?.loadVaultEnv() }
        }
        fileWatcher.watch(path: "\(vaultPath)/.env", onChange: vaultEnvRefresh)

        // Watch routines-state directory AND today's state file
        let stateDir = "\(dataDir)/routines-state"
        fileWatcher.watch(path: stateDir, onChange: refresh)
        let todayFile = "\(stateDir)/\(todayDateString()).json"
        fileWatcher.watch(path: todayFile, onChange: refresh)

        // Watch pipeline activity sidecar (ephemeral, created during pipeline runs)
        let activityFile = "\(dataDir)/pipeline-activity.json"
        fileWatcher.watch(path: activityFile, onChange: refresh)
        // Also watch dataDir itself to detect activity file creation
        fileWatcher.watch(path: dataDir, onChange: refresh)
    }

    func loadAll() async {
        // v3.5: Main is loaded as part of `loadAgents()` — no separate call.
        await loadAgents()
        await loadVaultClaudeMd()
        await loadRoutines()
        await loadSkills()
        await loadReactions()
        await loadSessions()
        await loadContexts()
        await refreshBotStatus()
    }

    // Called by FileWatcher callbacks and the watchdog in watchFiles().
    // Cancels any already-running loadAll Task to prevent pile-up when multiple
    // watched paths fire in quick succession (e.g. during an active pipeline).
    private func scheduleLoadAll() {
        loadAllTask?.cancel()
        loadAllTask = Task { [weak self] in
            guard let self, !Task.isCancelled else { return }
            await self.loadAll()
        }
    }

    // Seed recentLogs once from disk, then tail new lines via the DispatchSource
    // stream so LogViewerView never needs to poll.
    private func startLogStream() {
        guard let ls = logService else { return }
        Task {
            recentLogs = await ls.loadRecent(lines: Self.maxRecentLogs)
        }
        Task { [weak self] in
            guard let self else { return }
            for await entry in ls.makeStream() {
                await MainActor.run {
                    self.recentLogs.append(entry)
                    if self.recentLogs.count > Self.maxRecentLogs {
                        self.recentLogs.removeFirst(
                            self.recentLogs.count - Self.maxRecentLogs)
                    }
                }
            }
        }
    }

    func loadAgents() async {
        guard let vs = vaultService else { return }
        do {
            let loaded = try await vs.loadAgents()
            agents = loaded
        } catch {}
    }

    /// Load the universal vault rules from `vault/CLAUDE.md` so Settings can
    /// display and edit them. NOT specific to any agent.
    func loadVaultClaudeMd() async {
        guard let vs = vaultService else { return }
        vaultClaudeMd = await vs.loadVaultClaudeMd()
    }

    /// Save the universal vault rules back to `vault/CLAUDE.md`. Any running
    /// bot session picks up the new rules on its next Claude CLI invocation
    /// (the file is walked automatically by the CLAUDE.md hierarchy loader).
    func saveVaultClaudeMd(_ content: String) async throws {
        try await vaultService?.saveVaultClaudeMd(content)
        vaultClaudeMd = content
    }

    func loadRoutines() async {
        guard let vs = vaultService, let rs = routineStateService else { return }
        do {
            var loaded = try await vs.loadRoutines()
            let todayState = await rs.loadTodayState()
            // Load live activity sidecar for running pipelines
            let pipelineActivity = await rs.loadPipelineActivity()
            for i in loaded.indices {
                let name = loaded[i].id
                let slots = todayState[name] ?? [:]
                loaded[i].todayExecutions = slots.values.sorted {
                    ($0.startedAt ?? .distantPast) < ($1.startedAt ?? .distantPast)
                }
                // Merge live activity into running pipeline steps
                if let activity = pipelineActivity[name],
                   let lastExecIdx = loaded[i].todayExecutions.indices.last,
                   loaded[i].todayExecutions[lastExecIdx].status == .running {
                    for j in loaded[i].todayExecutions[lastExecIdx].pipelineSteps.indices {
                        let stepId = loaded[i].todayExecutions[lastExecIdx].pipelineSteps[j].id
                        if let stepActivity = activity[stepId] {
                            loaded[i].todayExecutions[lastExecIdx].pipelineSteps[j].activity = stepActivity
                        }
                    }
                }
                // Load pipeline step definitions for expanded view
                if loaded[i].isPipeline && loaded[i].pipelineStepDefs.isEmpty {
                    loaded[i].pipelineStepDefs = await vs.loadPipelineStepDefs(
                        routineId: loaded[i].id,
                        promptBody: loaded[i].promptBody,
                        ownerAgentId: loaded[i].ownerAgentId)
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
        // Fetch active runners from bot health endpoint + web health
        await withTaskGroup(of: Void.self) { group in
            group.addTask { await self.fetchBotHealthStatus() }
            group.addTask { await self.fetchWebHealthStatus() }
        }
    }

    private func fetchBotHealthStatus() async {
        guard isRunning else { activeRunners = 0; return }
        let url = URL(string: "http://127.0.0.1:27182/health")!
        var req = URLRequest(url: url)
        req.timeoutInterval = 3
        do {
            let (data, _) = try await URLSession.shared.data(for: req)
            if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                activeRunners = json["active_runners"] as? Int ?? 0
            }
        } catch {
            activeRunners = 0
        }
    }

    private func fetchWebHealthStatus() async {
        guard let url = URL(string: "http://127.0.0.1:27184/health") else { return }
        var req = URLRequest(url: url)
        req.timeoutInterval = 2
        do {
            let (_, resp) = try await URLSession.shared.data(for: req)
            webRunning = (resp as? HTTPURLResponse)?.statusCode == 200
        } catch {
            webRunning = false
        }
    }

    func refreshUsage() async {
        // Refresh all providers in parallel. Either may be nil if services
        // aren't wired yet (very early in init) — we only update what we got.
        let claudeService = claudeUsageService
        let zaiService = zaiUsageService
        let zaiKey = botConfig.zaiApiKey
        let zaiBase = botConfig.zaiBaseUrl
        let codexPath = botConfig.codexPath
        let costSvc = CostHistoryService(dataDir: dataDir)

        async let claudeResult: ClaudeUsage? = {
            guard let s = claudeService else { return nil }
            return await s.fetchUsage()
        }()
        async let zaiResult: ZAIUsage? = {
            guard let s = zaiService else { return nil }
            return await s.fetchUsage(apiKey: zaiKey, baseUrl: zaiBase)
        }()
        async let gptResult: GPTUsage = {
            let configured = FileManager.default.fileExists(atPath: codexPath)
            let weekly = (try? await costSvc.totalThisWeek(provider: "openai")) ?? 0
            let today  = (try? await costSvc.totalToday(provider: "openai")) ?? 0
            return GPTUsage(isConfigured: configured, weeklyCostUSD: weekly, todayCostUSD: today)
        }()

        let c = await claudeResult
        let z = await zaiResult
        let g = await gptResult
        if let c = c { self.claudeUsage = c }
        if let z = z { self.zaiUsage = z }
        self.gptUsage = g
        writeUsageCache()
    }

    /// Write current usage snapshot to ~/.claude-bot/usage-cache.json so the
    /// web dashboard can read fresh data without making its own API calls.
    private func writeUsageCache() {
        let c = claudeUsage
        let z = zaiUsage
        let g = gptUsage
        let iso = ISO8601DateFormatter()
        let payload: [String: Any] = [
            "claude": [
                "available":      c.isAvailable,
                "weeklyPercent":  c.weeklyPercent * 100,
                "sessionPercent": c.sessionPercent * 100,
                "hasTokenData":   c.hasTokenData,
                "weeklyTokenPercent": c.weeklyTokenPercent * 100,
                "weeklyResetsAt": c.weeklyResetsAt.map { iso.string(from: $0) } as Any,
                "planName":       c.planName as Any,
                "rateTier":       c.rateTier as Any,
            ],
            "zai": [
                "configured":     z.isConfigured,
                "available":      z.isAvailable,
                "weeklyPercent":  z.weeklyPercent * 100,
                "sessionPercent": z.sessionPercent * 100,
                "weeklyResetsAt": z.weeklyResetsAt.map { iso.string(from: $0) } as Any,
                "weeklyCostUSD":  z.weeklyCostUSD,
                "todayCostUSD":   z.todayCostUSD,
                "planLevel":      z.planLevel as Any,
                "planName":       z.planName,
                "hasCostData":    z.hasCostData,
                "weeklyLabel":    z.weeklyLabel,
                "glmAgentCount":   glmAgentCount,
                "glmRoutineCount": glmRoutineCount,
                "glmStepCount":    glmStepCount,
            ],
            "gpt": [
                "configured":    g.isConfigured,
                "weeklyCostUSD": g.weeklyCostUSD,
                "todayCostUSD":  g.todayCostUSD,
                "hasCostData":   g.hasCostData,
                "weeklyLabel":   g.weeklyLabel,
                "gptAgentCount":   gptAgentCount,
                "gptRoutineCount": gptRoutineCount,
                "gptStepCount":    gptStepCount,
            ],
            "counts": [
                "agents":   agents.count + 1,
                "routines": routines.count,
                "skills":   skills.count,
            ],
            "updatedAt": iso.string(from: Date()),
        ]
        guard let json = try? JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted]) else { return }
        let path = URL(fileURLWithPath: "\(dataDir)/usage-cache.json")
        try? json.write(to: path)
    }

    private var glmAgentCount: Int {
        agents.filter { $0.model.hasPrefix("glm") }.count
    }
    private var glmRoutineCount: Int {
        routines.filter { r in
            r.model.hasPrefix("glm") || r.pipelineStepDefs.contains(where: { $0.model.hasPrefix("glm") })
        }.count
    }
    private var glmStepCount: Int {
        routines.reduce(0) { acc, r in
            acc + r.pipelineStepDefs.filter { $0.model.hasPrefix("glm") }.count
        }
    }

    private var gptAgentCount: Int {
        agents.filter { $0.model.hasPrefix("gpt") }.count
    }
    private var gptRoutineCount: Int {
        routines.filter { r in
            r.model.hasPrefix("gpt") || r.pipelineStepDefs.contains(where: { $0.model.hasPrefix("gpt") })
        }.count
    }
    private var gptStepCount: Int {
        routines.reduce(0) { acc, r in
            acc + r.pipelineStepDefs.filter { $0.model.hasPrefix("gpt") }.count
        }
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

    private func controlToken() -> String? {
        let path = "\(dataDir)/.control-token"
        return try? String(contentsOfFile: path, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines)
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
        if let token = controlToken() {
            req.setValue(token, forHTTPHeaderField: "X-Bot-Token")
        }
        req.httpBody = try JSONSerialization.data(withJSONObject: ["name": routine.id, "time_slot": "dry-run"])
        req.timeoutInterval = 10
        let (_, response) = try await URLSession.shared.data(for: req)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw URLError(.badServerResponse)
        }
        // Poll state file until bot marks it done (max 3 min)
        let result = await routineStateService?.pollUntilDone(routineId: routine.id, timeSlot: "dry-run")
        await loadRoutines()
        return result
    }

    /// Delete a routine by id. Returns `true` on full success; on failure,
    /// stores a user-facing message in `lastError` (which view-level alerts
    /// observe) and returns `false`. Never throws — the alert IS the error
    /// channel, so callers don't need to remember to `try?`.
    @discardableResult
    func deleteRoutine(id: String, ownerAgentId: String = "main") async -> Bool {
        guard let svc = vaultService else {
            self.lastError = "VaultService indisponível."
            return false
        }
        do {
            try await svc.deleteRoutine(id: id, ownerAgentId: ownerAgentId)
            await loadRoutines()
            return true
        } catch {
            self.lastError = error.localizedDescription
            NSLog("deleteRoutine failed for \(id): \(error)")
            // Reload anyway — the trash may have succeeded partially and the
            // UI should reflect whatever state we actually have on disk.
            await loadRoutines()
            return false
        }
    }

    @discardableResult
    func deleteRoutine(_ routine: Routine) async -> Bool {
        return await deleteRoutine(id: routine.id, ownerAgentId: routine.ownerAgentId)
    }

    func stopRoutine(_ routine: Routine) async throws {
        let url = URL(string: "http://127.0.0.1:27182/routine/stop")!
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let token = controlToken() {
            req.setValue(token, forHTTPHeaderField: "X-Bot-Token")
        }
        req.httpBody = try JSONSerialization.data(withJSONObject: ["name": routine.id])
        req.timeoutInterval = 10
        let (_, response) = try await URLSession.shared.data(for: req)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw URLError(.badServerResponse)
        }
        await loadRoutines()
    }

    func loadSkills() async {
        guard let vs = vaultService else { return }
        do {
            skills = try await vs.loadSkills()
        } catch {}
    }

    func saveSkill(_ skill: Skill) async throws {
        try await vaultService?.saveSkill(skill)
        await loadSkills()
    }

    func deleteSkill(id: String, ownerAgentId: String = "main") async throws {
        try await vaultService?.deleteSkill(id: id, ownerAgentId: ownerAgentId)
        await loadSkills()
    }

    func deleteSkill(_ skill: Skill) async throws {
        try await vaultService?.deleteSkill(id: skill.id, ownerAgentId: skill.ownerAgentId)
        await loadSkills()
    }

    // MARK: - Reactions

    func loadReactions() async {
        guard let vs = vaultService else { return }
        do {
            reactions = try await vs.loadReactions()
        } catch {}
    }

    func saveReaction(_ reaction: Reaction) async throws {
        try await vaultService?.saveReaction(reaction)
        await loadReactions()
    }

    func deleteReaction(id: String, ownerAgentId: String = "main") async throws {
        try await vaultService?.deleteReaction(id: id, ownerAgentId: ownerAgentId)
        await loadReactions()
    }

    func deleteReaction(_ reaction: Reaction) async throws {
        try await vaultService?.deleteReaction(id: reaction.id, ownerAgentId: reaction.ownerAgentId)
        await loadReactions()
    }

    /// Generate a fresh random reaction token (synchronous, no vault access).
    nonisolated func generateReactionToken() -> String {
        var bytes = [UInt8](repeating: 0, count: 16)
        _ = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        let hex = bytes.map { String(format: "%02x", $0) }.joined()
        return "rxn_\(hex)"
    }

    nonisolated func generateHmacSecret() -> String {
        var bytes = [UInt8](repeating: 0, count: 32)
        _ = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        return bytes.map { String(format: "%02x", $0) }.joined()
    }

    func routineHistory(id: String) async -> [RoutineExecution] {
        await routineStateService?.loadHistory(for: id) ?? []
    }

    func loadPipelineStepDefs(routineId: String, promptBody: String, ownerAgentId: String = "main") async -> [PipelineStepDef] {
        await vaultService?.loadPipelineStepDefs(
            routineId: routineId,
            promptBody: promptBody,
            ownerAgentId: ownerAgentId
        ) ?? []
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
        // Poll bot/web health every 5 s. Routine state updates come via
        // FileWatcher → scheduleLoadAll(), so no need to reload routines here.
        statusTimer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self else { return }
                await self.refreshBotStatus()
            }
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
                case "TTS_ENGINE" where config.ttsEngine == BotConfig.defaults.ttsEngine:
                    config.ttsEngine = value
                case "ZAI_API_KEY" where config.zaiApiKey.isEmpty:
                    config.zaiApiKey = value
                case "ZAI_BASE_URL" where config.zaiBaseUrl == BotConfig.defaults.zaiBaseUrl:
                    config.zaiBaseUrl = value
                case "CODEX_PATH" where config.codexPath == BotConfig.defaults.codexPath:
                    config.codexPath = value
                case "MODEL_FALLBACK_CHAIN" where config.modelFallbackChain == BotConfig.defaults.modelFallbackChain:
                    config.modelFallbackChain = value
                case "SHOW_SIGNATURE":
                    config.showSignature = value.lowercased() != "false" && value != "0"
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
            "CLAUDE_WORKSPACE=\(config.claudeWorkspace)",
            "TTS_ENGINE=\(config.ttsEngine)",
            "ZAI_API_KEY=\(config.zaiApiKey)",
            "ZAI_BASE_URL=\(config.zaiBaseUrl)",
            "CODEX_PATH=\(config.codexPath)",
            "MODEL_FALLBACK_CHAIN=\(config.modelFallbackChain)",
            "SHOW_SIGNATURE=\(config.showSignature ? "true" : "false")"
        ]
        // Preserve any extra keys already in the file
        if let existing = try? String(contentsOfFile: envPath, encoding: .utf8) {
            let knownKeys = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "CLAUDE_PATH", "CLAUDE_WORKSPACE", "TTS_ENGINE", "ZAI_API_KEY", "ZAI_BASE_URL", "CODEX_PATH", "MODEL_FALLBACK_CHAIN", "SHOW_SIGNATURE"]
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

    // MARK: - Vault .env

    private func loadVaultEnv() {
        let envPath = "\(vaultPath)/.env"
        guard let content = try? String(contentsOfFile: envPath, encoding: .utf8) else {
            vaultEnvRawLines = []
            vaultEnvEntries = []
            return
        }
        let lines = content.components(separatedBy: "\n")
        vaultEnvRawLines = lines
        var entries: [VaultEnvEntry] = []
        for line in lines {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            guard !trimmed.isEmpty, !trimmed.hasPrefix("#"), trimmed.contains("=") else { continue }
            // Parse inline comment as friendly name: KEY=value # Friendly Name
            var payload = trimmed
            var friendlyName: String? = nil
            if let hashRange = Self.inlineCommentRange(in: payload) {
                let comment = String(payload[hashRange.upperBound...]).trimmingCharacters(in: .whitespaces)
                if !comment.isEmpty { friendlyName = comment }
                payload = String(payload[..<hashRange.lowerBound]).trimmingCharacters(in: .whitespaces)
            }
            let parts = payload.components(separatedBy: "=")
            guard parts.count >= 2 else { continue }
            let key = parts[0].trimmingCharacters(in: .whitespaces)
            let value = parts[1...].joined(separator: "=").trimmingCharacters(in: .whitespaces)
            entries.append(VaultEnvEntry(id: key, value: value, friendlyName: friendlyName))
        }
        vaultEnvEntries = entries
    }

    /// Find the range of an inline comment `# ...` that is NOT inside a value.
    /// Skips `#` that appear to be part of passwords or tokens (no space before `#`).
    private static func inlineCommentRange(in line: String) -> Range<String.Index>? {
        // Look for " # " pattern (space-hash-space) after the = sign
        guard let eqIndex = line.firstIndex(of: "=") else { return nil }
        let afterEq = line[line.index(after: eqIndex)...]
        if let range = afterEq.range(of: " # ") {
            return range
        }
        return nil
    }

    func saveVaultEnv(_ entries: [VaultEnvEntry]) throws {
        let envPath = "\(vaultPath)/.env"
        let lookup = Dictionary(entries.map { ($0.id, $0) }, uniquingKeysWith: { _, last in last })

        // Reconstruct existing lines with updated values
        var output: [String] = []
        var handledKeys = Set<String>()
        for line in vaultEnvRawLines {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            if trimmed.isEmpty || trimmed.hasPrefix("#") || !trimmed.contains("=") {
                output.append(line)
                continue
            }
            // Strip inline comment to get the key
            var payload = trimmed
            if let hashRange = Self.inlineCommentRange(in: payload) {
                payload = String(payload[..<hashRange.lowerBound]).trimmingCharacters(in: .whitespaces)
            }
            let key = payload.components(separatedBy: "=").first?.trimmingCharacters(in: .whitespaces) ?? ""
            if let entry = lookup[key] {
                output.append(Self.formatEnvLine(entry))
                handledKeys.insert(key)
            } else {
                output.append(line)
                handledKeys.insert(key)
            }
        }

        // Append new keys that weren't in the original file
        for entry in entries where !handledKeys.contains(entry.id) {
            output.append(Self.formatEnvLine(entry))
        }

        try output.joined(separator: "\n").write(toFile: envPath, atomically: true, encoding: .utf8)
        loadVaultEnv()
    }

    private static func formatEnvLine(_ entry: VaultEnvEntry) -> String {
        if let name = entry.friendlyName, !name.isEmpty {
            return "\(entry.id)=\(entry.value) # \(name)"
        }
        return "\(entry.id)=\(entry.value)"
    }

    private func formatUptime(_ t: TimeInterval) -> String {
        let s = Int(t)
        if s < 60 { return "\(s)s" }
        if s < 3600 { return "\(s/60)m" }
        if s < 86400 { return "\(s/3600)h \((s%3600)/60)m" }
        return "\(s/86400)d \((s%86400)/3600)h"
    }

    private func todayDateString() -> String {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        return f.string(from: Date())
    }
}
