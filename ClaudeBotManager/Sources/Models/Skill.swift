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
}
