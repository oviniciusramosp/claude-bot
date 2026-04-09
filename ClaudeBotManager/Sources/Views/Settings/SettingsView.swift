import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var appState: AppState
    @State private var config: BotConfig = .defaults
    @State private var showToken = false
    @State private var isSaving = false
    @State private var savedMessage = ""
    @State private var validationError = ""
    @State private var showValidationAlert = false
    @State private var showSwitchAccountConfirm = false
    @State private var isSwitching = false

    var body: some View {
        ScrollView {
            VStack(spacing: Spacing.lg) {
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

                    SettingRow("Chat ID(s)") {
                        TextField("e.g. 123456,789012", text: $config.telegramChatId)
                            .font(.system(.callout, design: .monospaced))
                            .textFieldStyle(.roundedBorder)
                    }
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

                // Account
                SectionCard(title: "Account", symbol: "person.crop.circle") {
                    let usage = appState.claudeUsage

                    SettingRow("Email") {
                        TextField("email@example.com", text: $config.claudeAccountEmail)
                            .font(.system(.callout, design: .monospaced))
                            .textFieldStyle(.roundedBorder)
                    }

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

                // Paths Info
                SectionCard(title: "Data Paths", symbol: "folder") {
                    PathRow(label: "Vault", path: appState.vaultPath)
                    PathRow(label: "Data Dir", path: appState.dataDir)
                    PathRow(label: "Log", path: "\(appState.dataDir)/bot.log")
                }

                // Save
                HStack {
                    if !savedMessage.isEmpty {
                        Label(savedMessage, systemImage: "checkmark.circle.fill")
                            .foregroundStyle(Color.statusGreen)
                            .font(.callout)
                    }
                    Spacer()
                    Button("Save") {
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
                    .buttonStyle(.borderedProminent)
                    .disabled(isSaving)
                }
                .padding(.horizontal, Spacing.xs)
            }
            .padding(Spacing.xl)
        }
        .navigationTitle("Settings")
        .onAppear {
            config = appState.botConfig
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

    private func switchAccount() {
        isSwitching = true
        let claudePath = NSString(string: config.claudePath).expandingTildeInPath
        let email = config.claudeAccountEmail.trimmingCharacters(in: .whitespaces)

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
            login.arguments = email.isEmpty ? ["auth", "login"] : ["auth", "login", "--email", email]
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
