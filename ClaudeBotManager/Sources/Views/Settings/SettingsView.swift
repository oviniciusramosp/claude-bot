import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var appState: AppState
    @State private var config: BotConfig = .defaults
    @State private var selectedTab = "tokens"
    @State private var showToken = false
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
    @State private var isVaultSaving = false
    @State private var vaultSavedMessage = ""
    @State private var vaultNeedsRestart = false
    @State private var showAddKey = false
    @State private var newKeyName = ""
    @State private var newKeyValue = ""

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

        // Paths Info
        SectionCard(title: "Data Paths", symbol: "folder") {
            PathRow(label: "Vault", path: appState.vaultPath)
            PathRow(label: "Data Dir", path: appState.dataDir)
            PathRow(label: "Log", path: "\(appState.dataDir)/bot.log")
        }

        // Vault API Keys
        SectionCard(title: "Vault API Keys", symbol: "key.fill") {
            if vaultEntries.isEmpty {
                Text("No keys found in vault/.env")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            } else {
                ForEach($vaultEntries) { $entry in
                    SettingRow(entry.friendlyLabel) {
                        HStack {
                            if entry.isSensitive && !showVaultSecrets.contains(entry.id) {
                                SecureField("", text: $entry.value)
                                    .font(.system(.callout, design: .monospaced))
                                    .textFieldStyle(.roundedBorder)
                            } else {
                                TextField("", text: $entry.value)
                                    .font(.system(.callout, design: .monospaced))
                                    .textFieldStyle(.roundedBorder)
                            }
                            if entry.isSensitive {
                                Button {
                                    if showVaultSecrets.contains(entry.id) {
                                        showVaultSecrets.remove(entry.id)
                                    } else {
                                        showVaultSecrets.insert(entry.id)
                                    }
                                } label: {
                                    Image(systemName: showVaultSecrets.contains(entry.id) ? "eye.slash" : "eye")
                                        .font(.callout)
                                }
                                .buttonStyle(.plain)
                                .foregroundStyle(.secondary)
                            }
                        }
                    }
                }
            }

            // Add new key form
            if showAddKey {
                Divider()
                HStack(spacing: Spacing.sm) {
                    TextField("KEY_NAME", text: $newKeyName)
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
                        let key = newKeyName.trimmingCharacters(in: .whitespaces)
                            .uppercased()
                            .replacingOccurrences(of: " ", with: "_")
                        guard !key.isEmpty,
                              !vaultEntries.contains(where: { $0.id == key }) else { return }
                        vaultEntries.append(VaultEnvEntry(id: key, value: newKeyValue))
                        newKeyName = ""
                        newKeyValue = ""
                        showAddKey = false
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(newKeyName.trimmingCharacters(in: .whitespaces).isEmpty)
                    Button("Cancel") {
                        newKeyName = ""
                        newKeyValue = ""
                        showAddKey = false
                    }
                    .buttonStyle(.bordered)
                }
                .padding(.top, Spacing.xs)
            }

            HStack {
                if !vaultSavedMessage.isEmpty {
                    Label(vaultSavedMessage, systemImage: "checkmark.circle.fill")
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
                Button {
                    showAddKey.toggle()
                } label: {
                    Image(systemName: "plus")
                        .font(.callout)
                }
                .buttonStyle(.bordered)
                Button("Save") {
                    isVaultSaving = true
                    do {
                        try appState.saveVaultEnv(vaultEntries)
                        vaultSavedMessage = "Saved"
                        vaultNeedsRestart = true
                        DispatchQueue.main.asyncAfter(deadline: .now() + 2) { vaultSavedMessage = "" }
                    } catch {
                        vaultSavedMessage = "Error: \(error.localizedDescription)"
                    }
                    isVaultSaving = false
                }
                .buttonStyle(.borderedProminent)
                .disabled(isVaultSaving)
            }
            .padding(.top, Spacing.xs)
        }

        // Save (bot config)
        HStack {
            if !savedMessage.isEmpty {
                Label(savedMessage, systemImage: "checkmark.circle.fill")
                    .foregroundStyle(Color.statusGreen)
                    .font(.callout)
            }
            Spacer()
            Button("Save") {
                saveBotConfig()
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

        // Save (customization)
        HStack {
            if !savedMessage.isEmpty {
                Label(savedMessage, systemImage: "checkmark.circle.fill")
                    .foregroundStyle(Color.statusGreen)
                    .font(.callout)
            }
            Spacer()
            Button("Save") {
                saveBotConfig()
            }
            .buttonStyle(.borderedProminent)
            .disabled(isSaving)
        }
        .padding(.horizontal, Spacing.xs)
    }

    // MARK: - Actions

    private func saveBotConfig() {
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
            savedMessage = "Saved"
            DispatchQueue.main.asyncAfter(deadline: .now() + 2) { savedMessage = "" }
        } catch {
            savedMessage = "Error: \(error.localizedDescription)"
        }
        isSaving = false
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
