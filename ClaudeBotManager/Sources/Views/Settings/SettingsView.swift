import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var appState: AppState
    @State private var config: BotConfig = .defaults
    @State private var selectedTab = "tokens"
    @State private var showToken = false
    @State private var showZaiKey = false
    @State private var isSaving = false
    @State private var savedMessage = ""
    @State private var validationError = ""
    @State private var showValidationAlert = false
    @State private var showSwitchAccountConfirm = false
    @State private var isSwitching = false
    @State private var userIds: [String] = [""]   // positive IDs — personal chats
    @State private var groupIds: [String] = []     // negative IDs — groups/channels

    // Vault API Keys
    @State private var vaultEntries: [VaultEnvEntry] = []
    @State private var showVaultSecrets: Set<String> = []
    @State private var vaultNeedsRestart = false

    // Universal vault rules — editable text for `vault/CLAUDE.md`
    @State private var vaultClaudeDraft: String = ""
    @State private var vaultClaudeSaved: Bool = false
    @State private var vaultClaudeSaving: Bool = false
    @State private var expandedGroups: Set<String> = []
    @State private var addingInGroup: String? = nil  // group id currently showing add form
    @State private var newKeyName = ""
    @State private var newKeyValue = ""
    @State private var newKeyEnvName = ""  // auto-generated, editable

    var body: some View {
        VStack(spacing: 0) {
            // Tab navigation
            CustomSegmentedControl(
                selection: $selectedTab,
                options: [("tokens", "Tokens"), ("customization", "Customization")]
            )
            .padding(.horizontal, Spacing.xl)
            .padding(.top, Spacing.lg)
            .padding(.bottom, Spacing.sm)

            ScrollView {
                VStack(spacing: Spacing.lg) {
                    if selectedTab == "tokens" {
                        tokensTab
                    } else {
                        customizationTab
                    }
                }
                .padding(Spacing.xl)
            }
        }
        .navigationTitle("Settings")
        .onAppear {
            config = appState.botConfig
            let ids = appState.botConfig.telegramChatId
                .components(separatedBy: ",")
                .map { $0.trimmingCharacters(in: .whitespaces) }
                .filter { !$0.isEmpty }
            let parsed = ids.reduce(into: (users: [String](), groups: [String]())) { acc, id in
                if id.hasPrefix("-") { acc.groups.append(id) } else { acc.users.append(id) }
            }
            userIds = parsed.users.isEmpty ? [""] : parsed.users
            groupIds = parsed.groups
            vaultEntries = appState.vaultEnvEntries.filter { !$0.isAgentRouting }
            vaultClaudeDraft = appState.vaultClaudeMd
        }
        .onChange(of: appState.vaultClaudeMd) { _, newValue in
            // Pull disk changes into the editor only when the user hasn't
            // touched the draft yet (avoid trampling unsaved edits).
            if !vaultClaudeSaving && vaultClaudeDraft == "" {
                vaultClaudeDraft = newValue
            }
        }
        .alert("Validation Error", isPresented: $showValidationAlert) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(validationError)
        }
        .alert("Switch Account", isPresented: $showSwitchAccountConfirm) {
            Button("Cancel", role: .cancel) {}
            Button("Switch") {
                switchAccount()
            }
        } message: {
            Text("This will sign out of the current account and open the browser to sign in with a different one.")
        }
    }

    // MARK: - Tokens Tab

    @ViewBuilder
    private var tokensTab: some View {
        // Telegram Config
        SectionCard(title: "Telegram", symbol: "paperplane.fill") {
            SettingRow("Bot Token") {
                HStack {
                    if showToken {
                        TextField("", text: $config.telegramBotToken)
                            .font(.system(.callout, design: .monospaced))
                            .textFieldStyle(.roundedBorder)
                    } else {
                        SecureField("", text: $config.telegramBotToken)
                            .font(.system(.callout, design: .monospaced))
                            .textFieldStyle(.roundedBorder)
                    }
                    Button {
                        showToken.toggle()
                    } label: {
                        Image(systemName: showToken ? "eye.slash" : "eye")
                            .font(.callout)
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(.secondary)
                }
            }

            // User IDs (required — at least 1)
            ForEach(userIds.indices, id: \.self) { i in
                SettingRow(i == 0 ? "My User ID" : "User ID") {
                    HStack {
                        TextField("6948798151", text: $userIds[i])
                            .font(.system(.callout, design: .monospaced))
                            .textFieldStyle(.roundedBorder)
                        if userIds.count > 1 {
                            Button {
                                userIds.remove(at: i)
                            } label: {
                                Image(systemName: "minus.circle.fill").font(.callout)
                            }
                            .buttonStyle(.plain)
                            .foregroundStyle(.secondary)
                        }
                    }
                }
            }

            // Group Peer IDs
            ForEach(groupIds.indices, id: \.self) { i in
                SettingRow("Group Peer ID") {
                    HStack {
                        TextField("-100123456789", text: $groupIds[i])
                            .font(.system(.callout, design: .monospaced))
                            .textFieldStyle(.roundedBorder)
                        Button {
                            groupIds.remove(at: i)
                        } label: {
                            Image(systemName: "minus.circle.fill").font(.callout)
                        }
                        .buttonStyle(.plain)
                        .foregroundStyle(.secondary)
                    }
                }
            }

            // Group Peer ID warning when agents exist but no group is configured
            if appState.agents.count > 0 && groupIds.filter({ !$0.trimmingCharacters(in: .whitespaces).isEmpty }).isEmpty {
                HStack(spacing: Spacing.xs) {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .font(.caption)
                        .foregroundStyle(.orange)
                    Text("You have agents beyond Main — a Group Peer ID is required for routing.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .padding(.top, Spacing.xs)
            }

            // Add buttons
            HStack {
                Spacer()
                Button {
                    userIds.append("")
                } label: {
                    Label("User ID", systemImage: "plus")
                        .font(.caption)
                }
                .buttonStyle(.plain)
                .foregroundStyle(.secondary)

                Divider().frame(height: 12)

                Button {
                    groupIds.append("")
                } label: {
                    Label("Group Peer ID", systemImage: "plus")
                        .font(.caption)
                }
                .buttonStyle(.plain)
                .foregroundStyle(.secondary)
            }
            .padding(.top, Spacing.xs)
        }

        // Claude Config
        SectionCard(title: "Claude", symbol: "cpu") {
            SettingRow("CLI Path") {
                TextField("/opt/homebrew/bin/claude", text: $config.claudePath)
                    .font(.system(.callout, design: .monospaced))
                    .textFieldStyle(.roundedBorder)
            }

            SettingRow("Workspace") {
                HStack {
                    TextField("~/", text: $config.claudeWorkspace)
                        .font(.system(.callout, design: .monospaced))
                        .textFieldStyle(.roundedBorder)
                    Button {
                        let panel = NSOpenPanel()
                        panel.canChooseFiles = false
                        panel.canChooseDirectories = true
                        panel.begin { response in
                            if response == .OK, let url = panel.url {
                                config.claudeWorkspace = url.path
                            }
                        }
                    } label: {
                        Image(systemName: "folder.badge.plus")
                            .font(.callout)
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(.secondary)
                }
            }
        }

        // z.AI (GLM Models)
        SectionCard(title: "z.AI (GLM Models)", symbol: "sparkles") {
            SettingRow("API Key") {
                HStack {
                    if showZaiKey {
                        TextField("sk-...", text: $config.zaiApiKey)
                            .font(.system(.callout, design: .monospaced))
                            .textFieldStyle(.roundedBorder)
                    } else {
                        SecureField("sk-...", text: $config.zaiApiKey)
                            .font(.system(.callout, design: .monospaced))
                            .textFieldStyle(.roundedBorder)
                    }
                    Button {
                        showZaiKey.toggle()
                    } label: {
                        Image(systemName: showZaiKey ? "eye.slash" : "eye")
                            .font(.callout)
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(.secondary)
                }
            }

            SettingRow("Base URL") {
                TextField("https://api.z.ai/api/anthropic", text: $config.zaiBaseUrl)
                    .font(.system(.callout, design: .monospaced))
                    .textFieldStyle(.roundedBorder)
            }

            Text("Get a key at z.ai/manage-apikey — enables GLM 5.1 / 4.7 / 4.5 Air in routines and pipelines.")
                .font(.caption)
                .foregroundStyle(.secondary)
                .padding(.top, Spacing.xs)
        }

        // ChatGPT (Codex CLI)
        SectionCard(title: "ChatGPT (Codex CLI)", symbol: "brain") {
            SettingRow("Binary") {
                HStack(spacing: Spacing.sm) {
                    Circle()
                        .fill(codexBinaryExists ? Color.statusGreen : Color.statusRed)
                        .frame(width: 8, height: 8)
                    Text(codexBinaryExists ? config.codexPath : "Não instalado")
                        .font(.system(.caption, design: .monospaced))
                        .foregroundStyle(codexBinaryExists ? .primary : .secondary)
                        .lineLimit(1)
                        .truncationMode(.middle)
                }
            }

            SettingRow("Login") {
                HStack(spacing: Spacing.sm) {
                    Circle()
                        .fill(codexAuthExists ? Color.statusGreen : Color.statusRed)
                        .frame(width: 8, height: 8)
                    Text(codexAuthExists ? "Logado com ChatGPT" : "Rode `codex login`")
                        .font(.callout)
                        .foregroundStyle(codexAuthExists ? .primary : .secondary)
                }
            }

            HStack {
                Spacer()
                if !codexBinaryExists {
                    Button {
                        openTerminal(with: "brew install --cask codex && codex login")
                    } label: {
                        Label("Instalar Codex", systemImage: "arrow.down.circle")
                            .font(.callout)
                    }
                    .buttonStyle(.bordered)
                } else if !codexAuthExists {
                    Button {
                        openTerminal(with: "codex login")
                    } label: {
                        Label("codex login", systemImage: "key.fill")
                            .font(.callout)
                    }
                    .buttonStyle(.bordered)
                }
            }
            .padding(.top, Spacing.xs)

            Text("Conecta sua assinatura ChatGPT Plus/Pro via OAuth. Habilita GPT-5 e GPT-5 Codex em rotinas, pipelines e /model.")
                .font(.caption)
                .foregroundStyle(.secondary)
                .padding(.top, Spacing.xs)
        }

        // Paths Info
        SectionCard(title: "Data Paths", symbol: "folder") {
            PathRow(label: "Bot Dir", path: appState.dataDir)
            PathRow(label: "Vault (Brain)", path: appState.vaultPath)
            PathRow(label: "Logs", path: "\(appState.dataDir)/bot.log")
        }

        // Vault API Keys
        SectionCard(title: "Vault API Keys", symbol: "key.fill") {
            ForEach(VaultKeyGroup.allGroups) { group in
                vaultGroupSection(group)
            }

            // "Other" group for unmatched entries
            vaultOtherSection(otherVaultIndices())

        }

        // Unified save bar
        HStack {
            if !savedMessage.isEmpty {
                Label(savedMessage, systemImage: "checkmark.circle.fill")
                    .foregroundStyle(Color.statusGreen)
                    .font(.callout)
            }
            if vaultNeedsRestart {
                Button {
                    Task {
                        await appState.restartBot()
                        vaultNeedsRestart = false
                    }
                } label: {
                    Label("Restart Bot", systemImage: "arrow.clockwise")
                        .font(.callout)
                }
                .buttonStyle(.bordered)
                .tint(.orange)
            }
            Spacer()
            Button("Save") {
                saveAll()
            }
            .buttonStyle(.borderedProminent)
            .disabled(isSaving)
        }
        .padding(.horizontal, Spacing.xs)
    }

    // MARK: - Customization Tab

    @ViewBuilder
    private var customizationTab: some View {
        // Account
        SectionCard(title: "Account", symbol: "person.crop.circle") {
            let usage = appState.claudeUsage

            SettingRow("Status") {
                HStack(spacing: Spacing.sm) {
                    Circle()
                        .fill(usage.hasPlanInfo ? Color.statusGreen : Color.statusRed)
                        .frame(width: 8, height: 8)
                    Text(usage.hasPlanInfo ? "Logged in" : "Not logged in")
                        .font(.callout)
                        .foregroundStyle(usage.hasPlanInfo ? .primary : .secondary)
                }
            }

            if let org = usage.organizationName {
                SettingRow("Organization") {
                    Text(org)
                        .font(.callout)
                }
            }

            if let plan = usage.planName {
                SettingRow("Plan") {
                    HStack(spacing: Spacing.sm) {
                        Text(plan)
                            .font(.callout)
                        if let tier = usage.rateTier {
                            Text(tier)
                                .font(.caption2.weight(.medium))
                                .padding(.horizontal, 6)
                                .padding(.vertical, 2)
                                .background(.quaternary)
                                .clipShape(Capsule())
                        }
                    }
                }
            }

            HStack {
                Spacer()
                Button {
                    showSwitchAccountConfirm = true
                } label: {
                    Label("Switch Account", systemImage: "arrow.triangle.2.circlepath")
                        .font(.callout)
                }
                .disabled(isSwitching)
            }
            .padding(.top, Spacing.xs)
        }

        // Voice (TTS)
        SectionCard(title: "Voice (TTS)", symbol: "waveform") {
            SettingRow("Engine") {
                Picker("", selection: $config.ttsEngine) {
                    Text("Edge TTS (Neural)").tag("edge-tts")
                    Text("macOS Say").tag("say")
                }
                .pickerStyle(.segmented)
            }

            Text(config.ttsEngine == "edge-tts"
                 ? "Voz neural Microsoft — natural, requer internet"
                 : "Voz nativa macOS — robótica, funciona offline")
                .font(.caption)
                .foregroundStyle(.secondary)
        }

        // Signature
        SectionCard(title: "Signature", symbol: "pencil.and.outline") {
            SettingRow("Show Signature") {
                Toggle("", isOn: $config.showSignature)
                    .labelsHidden()
                    .toggleStyle(.switch)
            }
            Text("Append agent name and model ID to every response (e.g. _Main · claude-sonnet-4-6_)")
                .font(.caption)
                .foregroundStyle(.secondary)
                .padding(.top, Spacing.xs)
        }

        // Model Fallback
        SectionCard(title: "Model Fallback", symbol: "arrow.triangle.branch") {
            Text("When a model fails after retries, the bot tries the next one in this chain. GLM models require a z.AI API key.")
                .font(.caption)
                .foregroundStyle(.secondary)
                .padding(.bottom, Spacing.xs)

            FallbackChainEditor(
                chain: $config.modelFallbackChain,
                zaiKeySet: !config.zaiApiKey.isEmpty,
                codexAvailable: codexBinaryExists && codexAuthExists
            )
        }

        // Vault Rules (universal — vault/CLAUDE.md)
        SectionCard(title: "Vault Rules", symbol: "doc.text.fill") {
            Text("vault/CLAUDE.md — universal rules loaded by every agent session. Contains the frontmatter contract, graph conventions, and linking rules. NOT specific to any agent — the Main agent's personality lives in vault/main/CLAUDE.md.")
                .font(.caption)
                .foregroundStyle(.secondary)
                .padding(.bottom, Spacing.xs)

            TextEditor(text: $vaultClaudeDraft)
                .font(.system(size: 12, design: .monospaced))
                .frame(minHeight: 280)
                .padding(Spacing.sm)
                .scrollContentBackground(.hidden)
                .background(Color.black.opacity(0.04))
                .clipShape(RoundedRectangle(cornerRadius: 6))
                .overlay(
                    RoundedRectangle(cornerRadius: 6)
                        .stroke(Color.black.opacity(0.08), lineWidth: 1)
                )

            HStack {
                if vaultClaudeSaved {
                    Label("Saved", systemImage: "checkmark.circle.fill")
                        .font(.caption)
                        .foregroundStyle(Color.statusGreen)
                }
                Spacer()
                Button("Reload from disk") {
                    Task {
                        await appState.loadVaultClaudeMd()
                        vaultClaudeDraft = appState.vaultClaudeMd
                        vaultClaudeSaved = false
                    }
                }
                .buttonStyle(.bordered)
                .disabled(vaultClaudeSaving)

                Button(vaultClaudeSaving ? "Saving…" : "Save Rules") {
                    vaultClaudeSaving = true
                    vaultClaudeSaved = false
                    let draft = vaultClaudeDraft
                    Task {
                        try? await appState.saveVaultClaudeMd(draft)
                        vaultClaudeSaving = false
                        vaultClaudeSaved = true
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(vaultClaudeSaving || vaultClaudeDraft == appState.vaultClaudeMd)
            }
            .padding(.top, Spacing.xs)
        }

        // Save (customization)
        HStack {
            if !savedMessage.isEmpty {
                Label(savedMessage, systemImage: "checkmark.circle.fill")
                    .foregroundStyle(Color.statusGreen)
                    .font(.callout)
            }
            Spacer()
            Button("Save") {
                saveAll()
            }
            .buttonStyle(.borderedProminent)
            .disabled(isSaving)
        }
        .padding(.horizontal, Spacing.xs)
    }

    // MARK: - Actions

    private func saveAll() {
        let fm = FileManager.default
        let expandedClaude = NSString(string: config.claudePath).expandingTildeInPath
        let expandedWorkspace = NSString(string: config.claudeWorkspace).expandingTildeInPath

        if !fm.fileExists(atPath: expandedClaude) {
            validationError = "Claude CLI path does not exist: \(config.claudePath)"
            showValidationAlert = true
            return
        }

        var isDir: ObjCBool = false
        if !fm.fileExists(atPath: expandedWorkspace, isDirectory: &isDir) || !isDir.boolValue {
            validationError = "Workspace path is not a valid directory: \(config.claudeWorkspace)"
            showValidationAlert = true
            return
        }

        let cleanUserIds = userIds.map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
        if cleanUserIds.isEmpty {
            validationError = "At least one User ID is required."
            showValidationAlert = true
            return
        }
        config.telegramChatId = (cleanUserIds + groupIds.map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty })
            .joined(separator: ",")

        isSaving = true
        do {
            try appState.saveConfig(config)
            try appState.saveVaultEnv(vaultEntries)
            savedMessage = "Saved"
            vaultNeedsRestart = true
            DispatchQueue.main.asyncAfter(deadline: .now() + 2) { savedMessage = "" }
        } catch {
            savedMessage = "Error: \(error.localizedDescription)"
        }
        isSaving = false
    }

    // MARK: - Vault Key Groups

    private func indicesForGroup(_ group: VaultKeyGroup) -> [Int] {
        vaultEntries.indices.filter { i in
            if let matched = VaultKeyGroup.group(for: vaultEntries[i].id) {
                return matched.id == group.id
            }
            return false
        }
    }

    private func otherVaultIndices() -> [Int] {
        vaultEntries.indices.filter { i in
            let e = vaultEntries[i]
            if e.isAgentRouting { return false }
            return VaultKeyGroup.group(for: e.id) == nil
        }
    }

    @ViewBuilder
    private func vaultGroupSection(_ group: VaultKeyGroup) -> some View {
        let groupIndices = indicesForGroup(group)
        let predefinedKeys = Set(group.predefinedKeys.map(\.envKey))
        let customIndices = groupIndices.filter { !predefinedKeys.contains(vaultEntries[$0].id) }
        let isExpanded = Binding(
            get: { expandedGroups.contains(group.id) },
            set: { val in
                if val { expandedGroups.insert(group.id) } else { expandedGroups.remove(group.id) }
            }
        )

        DisclosureGroup(isExpanded: isExpanded) {
            // Predefined keys
            ForEach(Array(group.predefinedKeys.enumerated()), id: \.offset) { _, predef in
                if let idx = vaultEntries.firstIndex(where: { $0.id == predef.envKey }) {
                    vaultEntryRow(binding: $vaultEntries[idx], label: predef.label)
                } else {
                    // Predefined slot not yet in .env — show empty field
                    HStack {
                        Text(predef.label)
                            .font(.callout)
                            .foregroundStyle(.secondary)
                            .frame(width: 120, alignment: .leading)
                        TextField("Not set", text: .constant(""))
                            .font(.system(.callout, design: .monospaced))
                            .textFieldStyle(.roundedBorder)
                            .disabled(true)
                        Button {
                            vaultEntries.append(VaultEnvEntry(id: predef.envKey, value: ""))
                            expandedGroups.insert(group.id)
                        } label: {
                            Image(systemName: "plus.circle").font(.callout)
                        }
                        .buttonStyle(.plain)
                        .foregroundStyle(Color.accentColor)
                    }
                }
            }

            // Custom entries (matched by prefix but not predefined)
            ForEach(customIndices, id: \.self) { idx in
                vaultEntryRow(binding: $vaultEntries[idx], label: vaultEntries[idx].friendlyLabel, showRemove: true)
            }

            // Add custom entry form
            if let addGroup = addingInGroup, addGroup == group.id {
                addCustomEntryForm(group: group)
            }

            // Add button
            if let label = group.customLabel {
                Button {
                    addingInGroup = group.id
                    newKeyName = ""
                    newKeyValue = ""
                    newKeyEnvName = ""
                } label: {
                    Label(label, systemImage: "plus")
                        .font(.callout)
                }
                .buttonStyle(.plain)
                .foregroundStyle(Color.accentColor)
                .padding(.top, Spacing.xs)
            }
        } label: {
            Label(group.name, systemImage: group.symbol)
                .font(.callout.weight(.medium))
        }
    }

    @ViewBuilder
    private func vaultOtherSection(_ indices: [Int]) -> some View {
        let isExpanded = Binding(
            get: { expandedGroups.contains("other") },
            set: { val in
                if val { expandedGroups.insert("other") } else { expandedGroups.remove("other") }
            }
        )

        DisclosureGroup(isExpanded: isExpanded) {
            ForEach(indices, id: \.self) { idx in
                vaultEntryRow(binding: $vaultEntries[idx], label: vaultEntries[idx].friendlyLabel, showRemove: true)
            }

            // Add form for "Other"
            if addingInGroup == "other" {
                addOtherEntryForm()
            }

            Button {
                addingInGroup = "other"
                newKeyName = ""
                newKeyValue = ""
                newKeyEnvName = ""
            } label: {
                Label("Add Key", systemImage: "plus")
                    .font(.callout)
            }
            .buttonStyle(.plain)
            .foregroundStyle(Color.accentColor)
            .padding(.top, Spacing.xs)
        } label: {
            Label("Other", systemImage: "ellipsis.circle")
                .font(.callout.weight(.medium))
        }
    }

    @ViewBuilder
    private func vaultEntryRow(binding: Binding<VaultEnvEntry>, label: String, showRemove: Bool = false) -> some View {
        HStack {
            Text(label)
                .font(.callout)
                .foregroundStyle(.secondary)
                .frame(width: 120, alignment: .leading)
                .lineLimit(1)
            if binding.wrappedValue.isSensitive && !showVaultSecrets.contains(binding.wrappedValue.id) {
                SecureField("", text: binding.value)
                    .font(.system(.callout, design: .monospaced))
                    .textFieldStyle(.roundedBorder)
            } else {
                TextField("", text: binding.value)
                    .font(.system(.callout, design: .monospaced))
                    .textFieldStyle(.roundedBorder)
            }
            if binding.wrappedValue.isSensitive {
                Button {
                    if showVaultSecrets.contains(binding.wrappedValue.id) {
                        showVaultSecrets.remove(binding.wrappedValue.id)
                    } else {
                        showVaultSecrets.insert(binding.wrappedValue.id)
                    }
                } label: {
                    Image(systemName: showVaultSecrets.contains(binding.wrappedValue.id) ? "eye.slash" : "eye")
                        .font(.callout)
                }
                .buttonStyle(.plain)
                .foregroundStyle(.secondary)
            }
            if showRemove {
                Button {
                    vaultEntries.removeAll { $0.id == binding.wrappedValue.id }
                } label: {
                    Image(systemName: "minus.circle.fill").font(.callout)
                }
                .buttonStyle(.plain)
                .foregroundStyle(.secondary)
            }
        }
    }

    @ViewBuilder
    private func addCustomEntryForm(group: VaultKeyGroup) -> some View {
        VStack(spacing: Spacing.sm) {
            HStack(spacing: Spacing.sm) {
                TextField("Name (e.g. Posts Database)", text: $newKeyName)
                    .font(.callout)
                    .textFieldStyle(.roundedBorder)
                    .onChange(of: newKeyName) { _, name in
                        let slug = name.trimmingCharacters(in: .whitespaces)
                            .uppercased()
                            .replacingOccurrences(of: " ", with: "_")
                        let suffix = group.customSuggestedSuffix ?? ""
                        newKeyEnvName = slug.isEmpty ? "" : "\(group.prefix)\(slug)\(suffix)"
                    }
            }
            HStack(spacing: Spacing.sm) {
                TextField("ENV_KEY", text: $newKeyEnvName)
                    .font(.system(.caption, design: .monospaced))
                    .textFieldStyle(.roundedBorder)
                    .frame(maxWidth: 200)
                TextField("Value", text: $newKeyValue)
                    .font(.system(.callout, design: .monospaced))
                    .textFieldStyle(.roundedBorder)
                Button("Add") {
                    let key = newKeyEnvName.trimmingCharacters(in: .whitespaces)
                    guard !key.isEmpty, !vaultEntries.contains(where: { $0.id == key }) else { return }
                    let friendly = newKeyName.trimmingCharacters(in: .whitespaces)
                    vaultEntries.append(VaultEnvEntry(
                        id: key,
                        value: newKeyValue,
                        friendlyName: friendly.isEmpty ? nil : friendly
                    ))
                    addingInGroup = nil
                    newKeyName = ""
                    newKeyValue = ""
                    newKeyEnvName = ""
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.small)
                .disabled(newKeyEnvName.trimmingCharacters(in: .whitespaces).isEmpty)
                Button("Cancel") {
                    addingInGroup = nil
                    newKeyName = ""
                    newKeyValue = ""
                    newKeyEnvName = ""
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
            }
        }
        .padding(.top, Spacing.xs)
    }

    @ViewBuilder
    private func addOtherEntryForm() -> some View {
        HStack(spacing: Spacing.sm) {
            TextField("KEY_NAME", text: $newKeyEnvName)
                .font(.system(.callout, design: .monospaced))
                .textFieldStyle(.roundedBorder)
                .frame(maxWidth: 180)
            Text("=")
                .font(.system(.callout, design: .monospaced))
                .foregroundStyle(.secondary)
            TextField("value", text: $newKeyValue)
                .font(.system(.callout, design: .monospaced))
                .textFieldStyle(.roundedBorder)
            Button("Add") {
                let key = newKeyEnvName.trimmingCharacters(in: .whitespaces)
                    .uppercased()
                    .replacingOccurrences(of: " ", with: "_")
                guard !key.isEmpty, !vaultEntries.contains(where: { $0.id == key }) else { return }
                vaultEntries.append(VaultEnvEntry(id: key, value: newKeyValue))
                addingInGroup = nil
                newKeyEnvName = ""
                newKeyValue = ""
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.small)
            .disabled(newKeyEnvName.trimmingCharacters(in: .whitespaces).isEmpty)
            Button("Cancel") {
                addingInGroup = nil
                newKeyEnvName = ""
                newKeyValue = ""
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
        }
        .padding(.top, Spacing.xs)
    }

    private func switchAccount() {
        isSwitching = true
        let claudePath = NSString(string: config.claudePath).expandingTildeInPath

        DispatchQueue.global(qos: .userInitiated).async {
            // Logout
            let logout = Process()
            logout.executableURL = URL(fileURLWithPath: claudePath)
            logout.arguments = ["auth", "logout"]
            logout.environment = ProcessInfo.processInfo.environment.filter { $0.key != "CLAUDECODE" }
            logout.standardOutput = Pipe()
            logout.standardError = Pipe()
            try? logout.run()
            logout.waitUntilExit()

            // Login (opens browser)
            let login = Process()
            login.executableURL = URL(fileURLWithPath: claudePath)
            login.arguments = ["auth", "login"]
            login.environment = ProcessInfo.processInfo.environment.filter { $0.key != "CLAUDECODE" }
            login.standardOutput = Pipe()
            login.standardError = Pipe()
            try? login.run()
            login.waitUntilExit()

            DispatchQueue.main.async {
                isSwitching = false
                // Refresh usage to pick up new account info
                Task { await appState.refreshUsage() }
            }
        }
    }

    // MARK: - Webhooks Tab

    // MARK: - Codex (ChatGPT) status helpers

    private var codexBinaryExists: Bool {
        FileManager.default.fileExists(atPath: config.codexPath)
    }

    private var codexAuthExists: Bool {
        let home = FileManager.default.homeDirectoryForCurrentUser
        return FileManager.default.fileExists(atPath: home.appendingPathComponent(".codex/auth.json").path)
    }

    private func openTerminal(with command: String) {
        // Escape double quotes inside the command for AppleScript embedding.
        let escaped = command.replacingOccurrences(of: "\"", with: "\\\"")
        let script = "tell application \"Terminal\" to do script \"\(escaped)\""
        let task = Process()
        task.launchPath = "/usr/bin/osascript"
        task.arguments = ["-e", script]
        try? task.run()
    }
}

struct PathRow: View {
    var label: String
    var path: String

    var body: some View {
        HStack {
            Text(label)
                .font(.callout)
                .foregroundStyle(.secondary)
                .frame(width: 80, alignment: .leading)
            Text(path)
                .font(.system(.callout, design: .monospaced))
                .foregroundStyle(.primary)
                .lineLimit(1)
                .truncationMode(.middle)
            Spacer()
            Button {
                NSWorkspace.shared.selectFile(nil, inFileViewerRootedAtPath: path)
            } label: {
                Image(systemName: "arrow.up.forward.square")
                    .font(.callout)
            }
            .buttonStyle(.plain)
            .foregroundStyle(.secondary)
        }
    }
}
