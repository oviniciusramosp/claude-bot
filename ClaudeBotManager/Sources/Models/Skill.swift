import Foundation

struct Skill: Identifiable, Hashable, Sendable {
    var id: String          // filename without .md (kebab-case)
    var title: String
    var description: String
    var trigger: String     // when/how the skill activates
    var tags: [String]
    var created: String
    var updated: String
    var body: String        // full markdown body (instructions)
    /// Owning agent id (v3.0 per-agent vault layout). Defaults to "main".
    var ownerAgentId: String = "main"

    /// System skills shipped with the repo — can be viewed but not deleted
    static let builtInIds: Set<String> = ["create-routine", "create-agent", "create-pipeline", "import-agent"]
    var isBuiltIn: Bool { Self.builtInIds.contains(id) }
}
