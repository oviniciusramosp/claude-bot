import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var appState: AppState
    @State private var config: BotConfig = .defaults
    @State private var showToken = false
    @State private var isSaving = false
    @State private var savedMessage = ""

    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                // Telegram Config
                GlassCard {
                    VStack(alignment: .leading, spacing: 12) {
                        SectionHeader(title: "Telegram", symbol: "paperplane.fill")

                        LabeledContent("Bot Token") {
                            HStack {
                                if showToken {
                                    TextField("", text: $config.telegramBotToken)
                                        .font(.system(.caption, design: .monospaced))
                                        .textFieldStyle(.roundedBorder)
                                } else {
                                    SecureField("", text: $config.telegramBotToken)
                                        .font(.system(.caption, design: .monospaced))
                                        .textFieldStyle(.roundedBorder)
                                }
                                Button {
                                    showToken.toggle()
                                } label: {
                                    Image(systemName: showToken ? "eye.slash" : "eye")
                                        .font(.caption)
                                }
                                .buttonStyle(.plain)
                                .foregroundStyle(.secondary)
                            }
                        }
                        .font(.caption)

                        LabeledContent("Chat ID(s)") {
                            TextField("e.g. 123456,789012", text: $config.telegramChatId)
                                .font(.system(.caption, design: .monospaced))
                                .textFieldStyle(.roundedBorder)
                        }
                        .font(.caption)
                    }
                }

                // Claude Config
                GlassCard {
                    VStack(alignment: .leading, spacing: 12) {
                        SectionHeader(title: "Claude", symbol: "cpu")

                        LabeledContent("CLI Path") {
                            TextField("/opt/homebrew/bin/claude", text: $config.claudePath)
                                .font(.system(.caption, design: .monospaced))
                                .textFieldStyle(.roundedBorder)
                        }
                        .font(.caption)

                        LabeledContent("Workspace") {
                            HStack {
                                TextField("~/", text: $config.claudeWorkspace)
                                    .font(.system(.caption, design: .monospaced))
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
                                        .font(.caption)
                                }
                                .buttonStyle(.plain)
                                .foregroundStyle(.secondary)
                            }
                        }
                        .font(.caption)
                    }
                }

                // Paths Info
                GlassCard {
                    VStack(alignment: .leading, spacing: 10) {
                        SectionHeader(title: "Data Paths", symbol: "folder")

                        PathRow(label: "Vault", path: appState.vaultPath)
                        PathRow(label: "Data Dir", path: appState.dataDir)
                        PathRow(label: "Log", path: "\(appState.dataDir)/bot.log")
                    }
                }

                // Save
                HStack {
                    if !savedMessage.isEmpty {
                        Label(savedMessage, systemImage: "checkmark.circle.fill")
                            .foregroundStyle(Color.statusGreen)
                            .font(.caption)
                    }
                    Spacer()
                    Button("Save") {
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
                .padding(.horizontal, 4)
            }
            .padding(20)
        }
        .navigationTitle("Settings")
        .onAppear {
            config = appState.botConfig
        }
    }
}

struct PathRow: View {
    var label: String
    var path: String

    var body: some View {
        HStack {
            Text(label)
                .font(.caption)
                .foregroundStyle(.secondary)
                .frame(width: 70, alignment: .leading)
            Text(path)
                .font(.system(.caption, design: .monospaced))
                .foregroundStyle(.primary)
                .lineLimit(1)
                .truncationMode(.middle)
            Spacer()
            Button {
                NSWorkspace.shared.selectFile(nil, inFileViewerRootedAtPath: path)
            } label: {
                Image(systemName: "arrow.up.forward.square")
                    .font(.caption)
            }
            .buttonStyle(.plain)
            .foregroundStyle(.secondary)
        }
    }
}
