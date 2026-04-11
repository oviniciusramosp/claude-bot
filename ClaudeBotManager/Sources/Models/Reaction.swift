import Foundation

/// A Reaction is a webhook-triggered configuration. When a webhook POST arrives
/// at `/webhook/{id}` on the bot's webhook server (port 27183), the reaction
/// authenticates the request and then performs one or both of:
///   - forwarding the payload to Telegram (with `{{field}}` template substitution)
///   - executing a routine or pipeline with the raw payload injected as context
///
/// Secrets (token / hmac_secret) are stored in `~/.claude-bot/reaction-secrets.json`
/// and never written to the vault.
struct Reaction: Identifiable, Hashable, Sendable {
    var id: String                  // filename without .md
    var title: String
    var description: String
    var enabled: Bool
    var created: String
    var updated: String
    var tags: [String]

    // Auth
    var authMode: AuthMode          // .token | .hmac
    var hmacHeader: String          // header name when mode=hmac, default "X-Signature"
    var hmacAlgo: String            // "sha256" etc.

    // Action
    var routineName: String?        // nil = no routine action
    var forward: Bool
    var forwardTemplate: String     // may contain {{key}} or {{raw}}
    var agentId: String?            // overrides routine's agent for forward target

    /// Owning agent id (v3.0 per-agent vault layout). Defaults to "main".
    /// Distinct from `agentId` (which is the forward/action target agent).
    var ownerAgentId: String = "main"

    // Body (free-form notes)
    var body: String

    // Secrets — loaded from ~/.claude-bot/reaction-secrets.json, not serialized to .md
    var token: String?
    var hmacSecret: String?

    // Stats — loaded from ~/.claude-bot/reaction-stats.json, not serialized to .md
    var lastFiredAt: Date?
    var fireCount: Int = 0
    var lastStatus: String?         // "ok" | "error"
    var lastForwarded: Bool = false
    var lastRoutineEnqueued: Bool = false

    enum AuthMode: String, Hashable, Sendable, CaseIterable {
        case token
        case hmac

        var label: String {
            switch self {
            case .token: return "Token"
            case .hmac:  return "HMAC"
            }
        }
    }

    /// True when there is at least one action configured (routine or forward).
    var hasAction: Bool {
        forward || (routineName?.isEmpty == false)
    }

    /// Icon that summarizes the reaction's actions.
    var summarySymbol: String {
        if forward && routineName?.isEmpty == false { return "arrow.triangle.branch" }
        if forward { return "paperplane" }
        if routineName?.isEmpty == false { return "clock.arrow.2.circlepath" }
        return "circle.dashed"
    }

    /// Human-readable summary of what this reaction does.
    var actionSummary: String {
        var parts: [String] = []
        if forward { parts.append("Forward to Telegram") }
        if let r = routineName, !r.isEmpty { parts.append("Run \(r)") }
        if parts.isEmpty { return "No action configured" }
        return parts.joined(separator: " + ")
    }

    static func newTemplate(id: String = "", ownerAgentId: String = "main") -> Reaction {
        let today = {
            let f = DateFormatter()
            f.dateFormat = "yyyy-MM-dd"
            return f.string(from: Date())
        }()
        return Reaction(
            id: id,
            title: "",
            description: "",
            enabled: true,
            created: today,
            updated: today,
            tags: ["reaction"],
            authMode: .token,
            hmacHeader: "X-Signature",
            hmacAlgo: "sha256",
            routineName: nil,
            forward: true,
            forwardTemplate: "{{raw}}",
            agentId: nil,
            ownerAgentId: ownerAgentId,
            body: "",
            token: nil,
            hmacSecret: nil
        )
    }
}
