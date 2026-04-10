import SwiftUI

struct ReactionDetailView: View {
    @EnvironmentObject var appState: AppState
    @Environment(\.dismiss) private var dismiss

    @State private var reaction: Reaction
    let isNew: Bool
    @State private var showDeleteConfirm = false
    @State private var showCopied = false
    @State private var errorMessage: String? = nil

    init(reaction: Reaction, isNew: Bool = false) {
        _reaction = State(initialValue: reaction)
        self.isNew = isNew
    }

    private var canSave: Bool {
        !reaction.id.isEmpty && !reaction.title.isEmpty && reaction.hasAction
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: Spacing.xl) {
                    generalSection
                    authSection
                    actionSection
                    webhookURLSection
                    notesSection
                    if let err = errorMessage {
                        Text(err)
                            .font(.system(size: 12))
                            .foregroundStyle(.red)
                    }
                }
                .padding(Spacing.xl)
            }
            .frame(minWidth: 640, minHeight: 520)
            .navigationTitle(isNew ? "New Reaction" : reaction.title)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .primaryAction) {
                    Button("Save") { save() }
                        .disabled(!canSave)
                }
                if !isNew {
                    ToolbarItem(placement: .destructiveAction) {
                        Button(role: .destructive) {
                            showDeleteConfirm = true
                        } label: {
                            Image(systemName: "trash")
                        }
                    }
                }
            }
            .confirmationDialog(
                "Delete reaction \(reaction.title)?",
                isPresented: $showDeleteConfirm,
                titleVisibility: .visible
            ) {
                Button("Delete", role: .destructive) { delete() }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("The reaction file will be moved to Trash. Secrets will be removed from ~/.claude-bot/reaction-secrets.json.")
            }
        }
    }

    // MARK: - Sections

    private func slugify(_ text: String) -> String {
        text.lowercased()
            .replacingOccurrences(of: " ", with: "-")
            .filter { $0.isLetter || $0.isNumber || $0 == "-" || $0 == "_" }
    }

    private var generalSection: some View {
        SectionCard(title: "General", symbol: "info.circle") {
            VStack(alignment: .leading, spacing: Spacing.md) {
                labeledField("Title") {
                    TextField("TradingView BTC Buy Signal", text: $reaction.title)
                        .textFieldStyle(.roundedBorder)
                        .onChange(of: reaction.title) { oldValue, newValue in
                            // Auto-derive ID from title for new reactions, as long as the user
                            // hasn't manually edited the ID (id still matches the previous slug).
                            if isNew {
                                let previousSlug = slugify(oldValue)
                                if reaction.id.isEmpty || reaction.id == previousSlug {
                                    reaction.id = slugify(newValue)
                                }
                            }
                        }
                }
                if isNew {
                    labeledField("ID (auto-generated from title)") {
                        TextField("tradingview-btc-buy", text: $reaction.id)
                            .textFieldStyle(.roundedBorder)
                            .font(.system(.callout, design: .monospaced))
                            .onChange(of: reaction.id) { _, newValue in
                                reaction.id = slugify(newValue)
                            }
                    }
                } else {
                    SettingRow("ID") {
                        Text(reaction.id).font(.system(.callout, design: .monospaced)).foregroundStyle(.secondary)
                    }
                }
                labeledField("Description") {
                    TextField("Processa alertas de compra do TradingView", text: $reaction.description)
                        .textFieldStyle(.roundedBorder)
                }
                SettingRow("Enabled") {
                    Toggle("", isOn: $reaction.enabled).labelsHidden()
                }
            }
        }
    }

    private var authSection: some View {
        SectionCard(title: "Authentication", symbol: "lock.shield") {
            VStack(alignment: .leading, spacing: Spacing.md) {
                SettingRow("Method") {
                    Picker("", selection: $reaction.authMode) {
                        ForEach(Reaction.AuthMode.allCases, id: \.self) { mode in
                            Text(mode.label).tag(mode)
                        }
                    }
                    .pickerStyle(.segmented)
                    .labelsHidden()
                    .frame(width: 160)
                }

                if reaction.authMode == .token {
                    labeledField("Token") {
                        HStack {
                            TextField("rxn_...", text: Binding(
                                get: { reaction.token ?? "" },
                                set: { reaction.token = $0.isEmpty ? nil : $0 }
                            ))
                            .textFieldStyle(.roundedBorder)
                            .font(.system(.callout, design: .monospaced))
                            Button {
                                reaction.token = appState.generateReactionToken()
                            } label: {
                                Image(systemName: "arrow.clockwise")
                            }
                            .buttonStyle(.borderless)
                            .help("Generate new token")
                            Button {
                                if let t = reaction.token {
                                    NSPasteboard.general.clearContents()
                                    NSPasteboard.general.setString(t, forType: .string)
                                }
                            } label: {
                                Image(systemName: "doc.on.doc")
                            }
                            .buttonStyle(.borderless)
                            .help("Copy token")
                        }
                    }
                    Text("Send via `X-Reaction-Token` header, or `?token=...` query param.")
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                } else {
                    labeledField("HMAC Secret") {
                        HStack {
                            TextField("hex secret", text: Binding(
                                get: { reaction.hmacSecret ?? "" },
                                set: { reaction.hmacSecret = $0.isEmpty ? nil : $0 }
                            ))
                            .textFieldStyle(.roundedBorder)
                            .font(.system(.callout, design: .monospaced))
                            Button {
                                reaction.hmacSecret = appState.generateHmacSecret()
                            } label: {
                                Image(systemName: "arrow.clockwise")
                            }
                            .buttonStyle(.borderless)
                            .help("Generate new secret")
                        }
                    }
                    labeledField("Signature Header") {
                        TextField("X-Signature", text: $reaction.hmacHeader)
                            .textFieldStyle(.roundedBorder)
                    }
                    labeledField("Algorithm") {
                        Picker("", selection: $reaction.hmacAlgo) {
                            Text("sha256").tag("sha256")
                            Text("sha1").tag("sha1")
                            Text("sha512").tag("sha512")
                        }
                        .labelsHidden()
                        .frame(width: 140)
                    }
                    Text("Compute: hex(HMAC-\(reaction.hmacAlgo.uppercased())(body, secret)). Optional `\(reaction.hmacAlgo)=` prefix accepted.")
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                }
            }
        }
    }

    private var actionSection: some View {
        SectionCard(title: "Action", symbol: "bolt.horizontal.circle") {
            VStack(alignment: .leading, spacing: Spacing.md) {
                // Routine picker
                SettingRow("Routine") {
                    Picker("", selection: Binding(
                        get: { reaction.routineName ?? "" },
                        set: { reaction.routineName = $0.isEmpty ? nil : $0 }
                    )) {
                        Text("None").tag("")
                        ForEach(appState.routines, id: \.id) { routine in
                            Text(routine.title).tag(routine.id)
                        }
                    }
                    .labelsHidden()
                    .frame(width: 260)
                }

                // Forward toggle
                SettingRow("Forward to Telegram") {
                    Toggle("", isOn: $reaction.forward).labelsHidden()
                }

                // Agent picker
                SettingRow("Target Agent") {
                    Picker("", selection: Binding(
                        get: { reaction.agentId ?? "" },
                        set: { reaction.agentId = $0.isEmpty ? nil : $0 }
                    )) {
                        Text("Main (default chat)").tag("")
                        ForEach(appState.agents, id: \.id) { agent in
                            Text("\(agent.icon) \(agent.name)").tag(agent.id)
                        }
                    }
                    .labelsHidden()
                    .frame(width: 260)
                }

                if reaction.forward {
                    labeledField("Forward Template") {
                        TextEditor(text: $reaction.forwardTemplate)
                            .font(.system(.callout, design: .monospaced))
                            .frame(minHeight: 80)
                            .padding(6)
                            .background(Color(.textBackgroundColor))
                            .overlay(
                                RoundedRectangle(cornerRadius: 6)
                                    .stroke(Color.primary.opacity(0.1), lineWidth: 0.5)
                            )
                    }
                    Text("Use `{{field}}` to interpolate JSON keys, `{{nested.field}}` for paths, `{{raw}}` for the full body.")
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                }
            }
        }
    }

    private var currentWebhookURL: String {
        let id = reaction.id.isEmpty ? "<id>" : reaction.id
        // Include token in URL only when mode is token (HMAC secrets never go in URLs)
        let tokenForURL = reaction.authMode == .token ? reaction.token : nil
        return appState.tunnel.webhookURL(for: id, token: tokenForURL)
    }

    private var webhookURLSection: some View {
        SectionCard(title: "Webhook URL", symbol: "link") {
            VStack(alignment: .leading, spacing: Spacing.sm) {
                // Full URL displayed in a selectable text box
                Text(currentWebhookURL)
                    .font(.system(.callout, design: .monospaced))
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(Spacing.sm)
                    .background(Color(.textBackgroundColor))
                    .overlay(
                        RoundedRectangle(cornerRadius: 6)
                            .stroke(Color.primary.opacity(0.1), lineWidth: 0.5)
                    )

                // Copy button — full-width, prominent, clearly a button
                HStack {
                    Button {
                        let url = currentWebhookURL
                        let pb = NSPasteboard.general
                        pb.clearContents()
                        pb.declareTypes([.string], owner: nil)
                        pb.setString(url, forType: .string)
                        showCopied = true
                        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { showCopied = false }
                    } label: {
                        Label(
                            showCopied ? "Copied!" : "Copy URL",
                            systemImage: showCopied ? "checkmark.circle.fill" : "doc.on.doc"
                        )
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.regular)
                    .disabled(reaction.id.isEmpty)
                    .help("Copy the full webhook URL (ready to paste into TradingView, Notion, etc.)")
                    Spacer()
                }
                if reaction.authMode == .token && (reaction.token ?? "").isEmpty {
                    Label("No token set — generate one in the Authentication section above, or Save to auto-generate.",
                          systemImage: "exclamationmark.triangle.fill")
                        .font(.system(size: 11))
                        .foregroundStyle(.orange)
                }
                if reaction.authMode == .hmac {
                    Label("HMAC mode: the signature is sent via the \(reaction.hmacHeader) header, not in the URL.",
                          systemImage: "info.circle")
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                }
                if appState.tunnel.isLocalOnly {
                    Label("Local only — enable Tailscale Funnel in the Reactions page to make this reachable from the internet.",
                          systemImage: "wifi.slash")
                        .font(.system(size: 11))
                        .foregroundStyle(.orange)
                } else {
                    Label("Public — reachable from the internet via Tailscale Funnel.",
                          systemImage: "globe")
                        .font(.system(size: 11))
                        .foregroundStyle(.green)
                }
            }
        }
    }

    private var notesSection: some View {
        SectionCard(title: "Notes", symbol: "note.text") {
            TextEditor(text: $reaction.body)
                .font(.system(.callout))
                .frame(minHeight: 80)
                .padding(6)
                .background(Color(.textBackgroundColor))
                .overlay(
                    RoundedRectangle(cornerRadius: 6)
                        .stroke(Color.primary.opacity(0.1), lineWidth: 0.5)
                )
        }
    }

    @ViewBuilder
    private func labeledField<Content: View>(_ label: String, @ViewBuilder _ content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label)
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(.secondary)
            content()
        }
    }

    // MARK: - Actions

    private func save() {
        // Ensure an action is configured
        guard reaction.hasAction else {
            errorMessage = "Reaction must have at least one action (forward or routine)."
            return
        }
        // Ensure required secret is present
        if reaction.authMode == .token && (reaction.token ?? "").isEmpty {
            reaction.token = appState.generateReactionToken()
        }
        if reaction.authMode == .hmac && (reaction.hmacSecret ?? "").isEmpty {
            reaction.hmacSecret = appState.generateHmacSecret()
        }
        Task {
            do {
                try await appState.saveReaction(reaction)
                dismiss()
            } catch {
                errorMessage = "Failed to save: \(error.localizedDescription)"
            }
        }
    }

    private func delete() {
        Task {
            do {
                try await appState.deleteReaction(id: reaction.id)
                dismiss()
            } catch {
                errorMessage = "Failed to delete: \(error.localizedDescription)"
            }
        }
    }
}
