import SwiftUI

struct OnboardingView: View {
    @EnvironmentObject var appState: AppState
    @State private var step = 0
    @State private var token = ""
    @State private var chatId = ""
    @State private var claudePath = "/opt/homebrew/bin/claude"
    @State private var claudeDetected = false
    @State private var isSaving = false

    private let totalSteps = 3

    var body: some View {
        ZStack {
            Color.black.opacity(0.45).ignoresSafeArea()

            VStack(spacing: 0) {
                // Progress dots
                HStack(spacing: 8) {
                    ForEach(0..<totalSteps, id: \.self) { i in
                        Circle()
                            .fill(i <= step ? Color.statusBlue : Color.primary.opacity(0.15))
                            .frame(width: 7, height: 7)
                            .animation(.easeInOut, value: step)
                    }
                }
                .padding(.top, 28)
                .padding(.bottom, 24)

                Group {
                    switch step {
                    case 0: welcomeStep
                    case 1: telegramStep
                    case 2: claudeStep
                    default: EmptyView()
                    }
                }
                .padding(.horizontal, 36)
                .padding(.bottom, 32)
            }
            .frame(width: 500)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 20))
            .shadow(color: .black.opacity(0.35), radius: 50)
        }
        .onAppear {
            token = appState.botConfig.telegramBotToken
            chatId = appState.botConfig.telegramChatId
            claudePath = appState.botConfig.claudePath
            detectClaude()
        }
    }

    // MARK: - Steps

    private var welcomeStep: some View {
        VStack(spacing: 20) {
            Image(systemName: "cpu.fill")
                .font(.system(size: 52))
                .foregroundStyle(Color.statusBlue)

            VStack(spacing: 8) {
                Text("Claude Bot Manager")
                    .font(.title2.bold())
                Text("Controle total do seu bot Claude Code via Telegram — agentes, rotinas, logs e uso em um só lugar.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }

            VStack(alignment: .leading, spacing: 10) {
                OnboardingFeatureRow(symbol: "paperplane.fill", color: .statusBlue,
                    text: "Conecta ao seu bot Telegram existente")
                OnboardingFeatureRow(symbol: "person.2.fill", color: .statusGreen,
                    text: "Gerencia agentes e mapeamento de tópicos")
                OnboardingFeatureRow(symbol: "clock.arrow.2.circlepath", color: .statusYellow,
                    text: "Cria e monitora rotinas agendadas")
                OnboardingFeatureRow(symbol: "cpu", color: .secondary,
                    text: "Requer Claude Code CLI instalado")
            }
            .padding(.top, 4)

            nextButton(label: "Começar", action: { step = 1 })
        }
    }

    private var telegramStep: some View {
        VStack(alignment: .leading, spacing: 20) {
            VStack(alignment: .leading, spacing: 6) {
                Label("Telegram", systemImage: "paperplane.fill")
                    .font(.title3.bold())
                    .foregroundStyle(Color.statusBlue)
                Text("Insira as credenciais do seu bot Telegram. Obtenha o token no @BotFather.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            VStack(alignment: .leading, spacing: 12) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Bot Token").font(.caption).foregroundStyle(.secondary)
                    SecureField("1234567890:ABCDEF...", text: $token)
                        .textFieldStyle(.roundedBorder)
                        .font(.system(.caption, design: .monospaced))
                }

                VStack(alignment: .leading, spacing: 4) {
                    Text("Chat ID(s) autorizados").font(.caption).foregroundStyle(.secondary)
                    TextField("ex: 6948798151 ou -1001234567890,6948798151", text: $chatId)
                        .textFieldStyle(.roundedBorder)
                        .font(.system(.caption, design: .monospaced))
                    Text("Use /status no bot para descobrir seu Chat ID.")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
            }

            HStack {
                Button("Voltar") { step = 0 }
                    .buttonStyle(.plain)
                    .foregroundStyle(.secondary)
                Spacer()
                nextButton(label: "Próximo", action: { step = 2 })
                    .disabled(token.isEmpty)
            }
        }
    }

    private var claudeStep: some View {
        VStack(alignment: .leading, spacing: 20) {
            VStack(alignment: .leading, spacing: 6) {
                Label("Claude Code CLI", systemImage: "cpu")
                    .font(.title3.bold())
                    .foregroundStyle(Color.statusBlue)
                Text("O bot precisa do Claude Code CLI instalado e autenticado.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            VStack(alignment: .leading, spacing: 12) {
                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        Text("Caminho do CLI").font(.caption).foregroundStyle(.secondary)
                        Spacer()
                        Button("Auto-detectar") { detectClaude() }
                            .font(.caption2)
                            .foregroundStyle(Color.statusBlue)
                            .buttonStyle(.plain)
                    }
                    HStack {
                        TextField("/opt/homebrew/bin/claude", text: $claudePath)
                            .textFieldStyle(.roundedBorder)
                            .font(.system(.caption, design: .monospaced))
                            .onChange(of: claudePath) { _, _ in
                                claudeDetected = FileManager.default.fileExists(atPath: claudePath)
                            }
                        Image(systemName: claudeDetected ? "checkmark.circle.fill" : "xmark.circle.fill")
                            .foregroundStyle(claudeDetected ? Color.statusGreen : Color.statusRed)
                            .font(.callout)
                    }
                }

                if !claudeDetected {
                    HStack(alignment: .top, spacing: 8) {
                        Image(systemName: "exclamationmark.triangle.fill")
                            .foregroundStyle(Color.statusYellow)
                            .font(.caption)
                        Text("CLI não encontrado neste caminho. Instale com `npm install -g @anthropic-ai/claude-code` ou ajuste o caminho.")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                    .padding(8)
                    .background(Color.statusYellow.opacity(0.08))
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                }
            }

            HStack {
                Button("Voltar") { step = 1 }
                    .buttonStyle(.plain)
                    .foregroundStyle(.secondary)
                Spacer()
                Button {
                    save()
                } label: {
                    if isSaving {
                        ProgressView().controlSize(.small)
                    } else {
                        Text("Concluir")
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(isSaving)
            }
        }
    }

    // MARK: - Helpers

    private func nextButton(label: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(label)
                .frame(maxWidth: .infinity)
        }
        .buttonStyle(.borderedProminent)
        .controlSize(.large)
    }

    private func detectClaude() {
        let candidates = [
            "/opt/homebrew/bin/claude",
            "/usr/local/bin/claude",
            NSHomeDirectory() + "/.bun/bin/claude",
            NSHomeDirectory() + "/.npm-global/bin/claude",
            "/usr/bin/claude",
        ]
        for path in candidates where FileManager.default.fileExists(atPath: path) {
            claudePath = path
            claudeDetected = true
            return
        }
        claudeDetected = FileManager.default.fileExists(atPath: claudePath)
    }

    private func save() {
        isSaving = true
        var config = appState.botConfig
        config.telegramBotToken = token
        config.telegramChatId = chatId
        config.claudePath = claudePath
        try? appState.saveConfig(config)
        isSaving = false
    }
}

struct OnboardingFeatureRow: View {
    var symbol: String
    var color: Color
    var text: String

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: symbol)
                .foregroundStyle(color)
                .frame(width: 20)
                .font(.callout)
            Text(text)
                .font(.subheadline)
                .foregroundStyle(.primary.opacity(0.85))
        }
    }
}
