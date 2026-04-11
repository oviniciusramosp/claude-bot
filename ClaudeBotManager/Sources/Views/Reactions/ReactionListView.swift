import SwiftUI

struct ReactionListView: View {
    @EnvironmentObject var appState: AppState
    @State private var showCreateSheet = false
    @State private var selectedReaction: Reaction? = nil
    @State private var searchText = ""
    @State private var agentFilter: String = "__all__"

    private func newReactionWithToken() -> Reaction {
        let owner = agentFilter == "__all__" ? "main" : agentFilter
        var template = Reaction.newTemplate(ownerAgentId: owner)
        template.token = appState.generateReactionToken()
        return template
    }

    private var filteredReactions: [Reaction] {
        let items = appState.reactions
            .filter { agentFilter == "__all__" || $0.ownerAgentId == agentFilter }
            .sorted { $0.title.lowercased() < $1.title.lowercased() }
        guard !searchText.isEmpty else { return items }
        let q = searchText.lowercased()
        return items.filter {
            $0.title.lowercased().contains(q)
            || $0.description.lowercased().contains(q)
            || ($0.routineName ?? "").lowercased().contains(q)
        }
    }

    var body: some View {
        ScrollView {
            VStack(spacing: Spacing.xl) {
                // Tunnel status banner
                TunnelStatusBanner()

                AgentFilterBar(selection: $agentFilter)

                if appState.reactions.isEmpty {
                    EmptyStateView(
                        symbol: "bolt.horizontal.circle.fill",
                        title: "No Reactions",
                        subtitle: "Create a reaction to trigger routines or forward payloads when a webhook arrives."
                    )
                } else if filteredReactions.isEmpty {
                    EmptyStateView(
                        symbol: "magnifyingglass",
                        title: "No Results",
                        subtitle: searchText.isEmpty
                            ? "No reactions for this agent yet."
                            : "No reactions match \"\(searchText)\"."
                    )
                } else {
                    VStack(spacing: Spacing.lg) {
                        ForEach(filteredReactions) { reaction in
                            ReactionRow(reaction: reaction, onTap: { selectedReaction = reaction })
                        }
                    }
                }
            }
            .padding(Spacing.xl)
        }
        .background(Color(.windowBackgroundColor))
        .navigationTitle("Reactions")
        .searchable(text: $searchText, placement: .toolbar, prompt: "Search reactions")
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    showCreateSheet = true
                } label: {
                    Label("New Reaction", systemImage: "plus")
                }
            }
        }
        .sheet(item: $selectedReaction) { reaction in
            ReactionDetailView(reaction: reaction)
        }
        .sheet(isPresented: $showCreateSheet) {
            // Pre-generate a token so it's visible in the form from the start.
            // Users shouldn't have to click Save to see their secret.
            ReactionDetailView(reaction: newReactionWithToken(), isNew: true)
        }
        .task {
            await appState.tunnel.detect()
        }
    }
}

// MARK: - Tunnel status banner (full control card)

private struct TunnelStatusBanner: View {
    @EnvironmentObject var appState: AppState

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: Spacing.md) {
                // Header row
                HStack(spacing: Spacing.sm) {
                    Image(systemName: iconName)
                        .font(.system(size: 18))
                        .foregroundStyle(iconColor)
                        .frame(width: 24)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(title)
                            .font(.system(size: 13, weight: .semibold))
                        Text(subtitle)
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    Spacer()
                    Button {
                        Task { await appState.tunnel.detect() }
                    } label: {
                        if appState.tunnel.isBusy {
                            ProgressView().controlSize(.small)
                        } else {
                            Image(systemName: "arrow.clockwise")
                        }
                    }
                    .buttonStyle(.borderless)
                    .help("Re-check Tailscale status")
                    .disabled(appState.tunnel.isBusy)
                    primaryAction
                }

                // Step-by-step guide for states that need user action outside the app
                if case .notInstalled = appState.tunnel.state, !appState.tunnel.isInstalling {
                    Divider()
                    ExternalStepsGuide(title: "What will happen when you click Install", steps: [
                        ExternalStep(number: 1, symbol: "arrow.down.circle", text: "Downloads the official Tailscale installer (~20 MB) from pkgs.tailscale.com."),
                        ExternalStep(number: 2, symbol: "lock.shield", text: "macOS asks for your password once to run the installer (standard system dialog)."),
                        ExternalStep(number: 3, symbol: "checkmark.seal", text: "Tailscale.app appears in /Applications. The first launch will ask you to approve a System Extension — click Allow."),
                        ExternalStep(number: 4, symbol: "person.circle", text: "Sign in with Google, Microsoft, GitHub, or email — Tailscale opens your browser. No credit card, free personal plan works."),
                        ExternalStep(number: 5, symbol: "arrow.uturn.backward", text: "Come back here — this card will update automatically once you sign in.")
                    ])
                } else if case .notLoggedIn = appState.tunnel.state {
                    Divider()
                    ExternalStepsGuide(title: "Finish signing in to Tailscale", steps: [
                        ExternalStep(number: 1, symbol: "arrow.up.forward.app", text: "Click 'Open Tailscale' — the Tailscale app will open."),
                        ExternalStep(number: 2, symbol: "person.circle", text: "Click 'Log in' in Tailscale's window. Your browser opens an authentication page."),
                        ExternalStep(number: 3, symbol: "checkmark.circle", text: "Choose an account (Google, Microsoft, GitHub, or email). Approve the login."),
                        ExternalStep(number: 4, symbol: "globe.badge.chevron.backward", text: "On first run, Tailscale's admin panel asks you to enable HTTPS and Funnel features — click Enable."),
                        ExternalStep(number: 5, symbol: "arrow.uturn.backward", text: "Come back here — this card will detect the login automatically.")
                    ])
                } else if case .installed = appState.tunnel.state {
                    Divider()
                    ExternalStepsGuide(title: "What happens when you enable Funnel", steps: [
                        ExternalStep(number: 1, symbol: "bolt.horizontal.circle", text: "Tailscale runs `tailscale funnel 27183` in the background."),
                        ExternalStep(number: 2, symbol: "link", text: "Your reactions become reachable at https://<your-machine>.<your-tailnet>.ts.net/webhook/<reaction-id>."),
                        ExternalStep(number: 3, symbol: "lock", text: "Each reaction's token or HMAC signature is the only thing protecting the endpoint from the public internet.")
                    ])
                }

                // Public URL row when active
                if case .active(let base) = appState.tunnel.state {
                    Divider()
                    HStack {
                        Image(systemName: "link")
                            .foregroundStyle(.secondary)
                            .frame(width: 24)
                        Text(base)
                            .font(.system(.callout, design: .monospaced))
                            .textSelection(.enabled)
                            .lineLimit(1)
                            .truncationMode(.middle)
                        Spacer()
                        Button {
                            NSPasteboard.general.clearContents()
                            NSPasteboard.general.setString(base, forType: .string)
                        } label: {
                            Image(systemName: "doc.on.doc")
                        }
                        .buttonStyle(.borderless)
                        .help("Copy base URL")
                    }
                }

                // Funnel tailnet authorization required
                if let authURL = appState.tunnel.funnelAuthURL {
                    Divider()
                    VStack(alignment: .leading, spacing: Spacing.sm) {
                        Label("One-time Funnel authorization needed", systemImage: "lock.open.trianglebadge.exclamationmark")
                            .font(.system(size: 12, weight: .semibold))
                            .foregroundStyle(.orange)
                        Text("Tailscale requires you to approve the Funnel feature on your tailnet admin panel — just once, for your whole account. Click the button below, approve in the browser, then click the Funnel toggle again.")
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                        HStack {
                            Button {
                                if let url = URL(string: authURL) {
                                    NSWorkspace.shared.open(url)
                                }
                                appState.tunnel.clearFunnelAuthURL()
                            } label: {
                                Label("Open Tailscale authorization", systemImage: "arrow.up.forward.app")
                            }
                            .buttonStyle(.borderedProminent)
                            Spacer()
                        }
                    }
                }

                // Error row — only when not in a working state
                if let err = appState.tunnel.lastError,
                   appState.tunnel.funnelAuthURL == nil,
                   !appState.tunnel.state.isActive {
                    Divider()
                    Label(err, systemImage: "xmark.octagon.fill")
                        .font(.system(size: 11))
                        .foregroundStyle(.red)
                        .fixedSize(horizontal: false, vertical: true)
                }

                // Informational: reminder that tokens protect the public endpoints
                if appState.tunnel.state.isActive {
                    HStack(spacing: 6) {
                        Image(systemName: "lock.shield")
                            .font(.system(size: 10))
                            .foregroundStyle(.tertiary)
                        Text("Each reaction is protected by its own token. Make sure every reaction has authentication set.")
                            .font(.system(size: 10))
                            .foregroundStyle(.tertiary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
        }
    }

    @ViewBuilder
    private var primaryAction: some View {
        switch appState.tunnel.state {
        case .notInstalled:
            if appState.tunnel.isInstalling {
                HStack(spacing: 6) {
                    ProgressView().controlSize(.small)
                    Text("Installing…")
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                }
            } else {
                Button {
                    Task { await appState.tunnel.install() }
                } label: {
                    Label("Install Tailscale", systemImage: "arrow.down.circle.fill")
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.regular)
                .help("Downloads the latest Tailscale .pkg (~20 MB) and installs it. Requires your password once.")
            }

        case .notLoggedIn:
            Button {
                NSWorkspace.shared.open(URL(fileURLWithPath: "/Applications/Tailscale.app"))
            } label: {
                Label("Open Tailscale", systemImage: "arrow.up.forward.app")
            }
            .buttonStyle(.bordered)

        case .installed, .active:
            Toggle("Funnel", isOn: Binding(
                get: { appState.tunnel.state.isActive },
                set: { newValue in
                    Task {
                        if newValue {
                            await appState.tunnel.enable()
                        } else {
                            await appState.tunnel.disable()
                        }
                    }
                }
            ))
            .toggleStyle(.switch)
            .disabled(appState.tunnel.isBusy)

        case .unknown:
            ProgressView().controlSize(.small)
        }
    }

    private var iconName: String {
        switch appState.tunnel.state {
        case .active: return "checkmark.circle.fill"
        case .installed: return "circle.dashed"
        case .notLoggedIn: return "exclamationmark.triangle.fill"
        case .notInstalled: return "xmark.circle.fill"
        case .unknown: return "questionmark.circle"
        }
    }

    private var iconColor: Color {
        switch appState.tunnel.state {
        case .active: return .green
        case .notLoggedIn, .notInstalled: return .orange
        default: return .secondary
        }
    }

    private var title: String {
        switch appState.tunnel.state {
        case .active: return "Webhooks exposed via Tailscale Funnel"
        case .installed: return "Tailscale ready — Funnel off"
        case .notLoggedIn: return "Tailscale not logged in"
        case .notInstalled: return "Webhooks are local only"
        case .unknown: return "Checking Tailscale…"
        }
    }

    private var subtitle: String {
        switch appState.tunnel.state {
        case .active: return "Reactions are reachable from the public internet."
        case .installed: return "Enable Funnel to get a public HTTPS URL for your reactions."
        case .notLoggedIn: return "Open Tailscale to sign in with your account."
        case .notInstalled: return "Install Tailscale to expose webhooks to the internet. One click, no Terminal, no Homebrew."
        case .unknown: return "—"
        }
    }
}

// MARK: - Reaction row

private struct ReactionRow: View {
    let reaction: Reaction
    var onTap: () -> Void = {}
    @EnvironmentObject var appState: AppState
    @State private var isEnabled: Bool
    @State private var showCopied = false

    init(reaction: Reaction, onTap: @escaping () -> Void = {}) {
        self.reaction = reaction
        self.onTap = onTap
        _isEnabled = State(initialValue: reaction.enabled)
    }

    var body: some View {
        GlassCard {
            HStack(alignment: .top, spacing: Spacing.md) {
                // Icon
                ZStack {
                    RoundedRectangle(cornerRadius: 8)
                        .fill(Color.accentColor.opacity(0.15))
                        .frame(width: 36, height: 36)
                    Image(systemName: reaction.summarySymbol)
                        .foregroundStyle(Color.accentColor)
                }

                // Content
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: Spacing.sm) {
                        Text(reaction.title.isEmpty ? reaction.id : reaction.title)
                            .font(.system(size: 14, weight: .semibold))
                        if !reaction.enabled {
                            Text("disabled")
                                .font(.system(size: 9, weight: .medium))
                                .foregroundStyle(.secondary)
                                .padding(.horizontal, 6)
                                .padding(.vertical, 1)
                                .background(Color.secondary.opacity(0.15), in: RoundedRectangle(cornerRadius: 3))
                        }
                        Text(reaction.authMode.label)
                            .font(.system(size: 9, weight: .medium, design: .monospaced))
                            .foregroundStyle(.secondary)
                            .padding(.horizontal, 6)
                            .padding(.vertical, 1)
                            .background(Color.secondary.opacity(0.12), in: RoundedRectangle(cornerRadius: 3))
                    }
                    if !reaction.description.isEmpty {
                        Text(reaction.description)
                            .font(.system(size: 12))
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                    }
                    HStack(spacing: Spacing.sm) {
                        Text(reaction.actionSummary)
                            .font(.system(size: 11))
                            .foregroundStyle(.tertiary)
                        if let lastFired = reaction.lastFiredAt {
                            Text("•")
                                .font(.system(size: 11))
                                .foregroundStyle(.tertiary)
                            HStack(spacing: 3) {
                                Image(systemName: reaction.lastStatus == "error"
                                      ? "exclamationmark.triangle.fill"
                                      : "checkmark.circle.fill")
                                    .font(.system(size: 9))
                                    .foregroundStyle(reaction.lastStatus == "error" ? .orange : .green)
                                Text("Last fired \(lastFired.relativeDescription())")
                                    .font(.system(size: 11))
                                    .foregroundStyle(.secondary)
                            }
                            if reaction.fireCount > 1 {
                                Text("• \(reaction.fireCount) total")
                                    .font(.system(size: 11))
                                    .foregroundStyle(.tertiary)
                            }
                        } else {
                            Text("• Never fired")
                                .font(.system(size: 11))
                                .foregroundStyle(.tertiary)
                        }
                    }
                }

                Spacer()

                // Copy URL (includes token when authMode is .token)
                Button {
                    let tokenForURL = reaction.authMode == .token ? reaction.token : nil
                    let url = appState.tunnel.webhookURL(for: reaction.id, token: tokenForURL)
                    let pb = NSPasteboard.general
                    pb.clearContents()
                    pb.declareTypes([.string], owner: nil)
                    pb.setString(url, forType: .string)
                    showCopied = true
                    DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { showCopied = false }
                } label: {
                    Image(systemName: showCopied ? "checkmark.circle.fill" : "link")
                        .foregroundStyle(showCopied ? .green : .primary)
                        .font(.system(size: 14))
                        .padding(6)
                }
                .buttonStyle(.borderless)
                .help("Copy full webhook URL (includes token)")

                // Enabled toggle
                Toggle("", isOn: $isEnabled)
                    .toggleStyle(.switch)
                    .labelsHidden()
                    .onChange(of: isEnabled) { _, newValue in
                        var updated = reaction
                        updated.enabled = newValue
                        Task { try? await appState.saveReaction(updated) }
                    }
            }
            .contentShape(Rectangle())
            .onTapGesture { onTap() }
        }
    }
}

// MARK: - External Steps Guide

private struct ExternalStep: Identifiable {
    let id = UUID()
    let number: Int
    let symbol: String
    let text: String
}

private extension Date {
    /// Short relative description like "2m ago", "3h ago", "yesterday", "Apr 5".
    func relativeDescription() -> String {
        let interval = Date().timeIntervalSince(self)
        if interval < 60 { return "just now" }
        if interval < 3600 { return "\(Int(interval / 60))m ago" }
        if interval < 86400 { return "\(Int(interval / 3600))h ago" }
        if interval < 172_800 { return "yesterday" }
        if interval < 604_800 { return "\(Int(interval / 86400))d ago" }
        let f = DateFormatter()
        f.dateFormat = "MMM d"
        return f.string(from: self)
    }
}

private struct ExternalStepsGuide: View {
    let title: String
    let steps: [ExternalStep]

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            Text(title)
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(.secondary)
                .textCase(.uppercase)
                .tracking(0.5)

            VStack(alignment: .leading, spacing: 6) {
                ForEach(steps) { step in
                    HStack(alignment: .top, spacing: Spacing.sm) {
                        // Number badge
                        ZStack {
                            Circle()
                                .fill(Color.accentColor.opacity(0.15))
                                .frame(width: 20, height: 20)
                            Text("\(step.number)")
                                .font(.system(size: 10, weight: .bold))
                                .foregroundStyle(Color.accentColor)
                        }
                        Image(systemName: step.symbol)
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)
                            .frame(width: 16)
                        Text(step.text)
                            .font(.system(size: 11))
                            .foregroundStyle(.primary)
                            .fixedSize(horizontal: false, vertical: true)
                        Spacer(minLength: 0)
                    }
                }
            }
        }
    }
}
