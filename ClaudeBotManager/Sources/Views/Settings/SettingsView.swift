import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var appState: AppState
    @State private var config: BotConfig = .defaults
    @State private var showToken = false
    @State private var isSaving = false
    @State private var savedMessage = ""
    @State private var validationError = ""
    @State private var showValidationAlert = false

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
