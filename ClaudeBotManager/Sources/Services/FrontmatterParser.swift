import Foundation

/// Reads and writes YAML frontmatter in Obsidian-style markdown files.
/// Output is byte-compatible with the Python bot's hand-rolled parser:
/// - Flow-style lists:  tags: [a, b, c]
/// - Lowercase bools:  enabled: true
/// - Quoted emoji:     icon: "💸"
/// - Nested block:     schedule:\n  times: [...]
/// - Bare date strings: created: 2026-04-07
struct FrontmatterParser {

    // MARK: - Parse

    /// Returns (frontmatter dict, body text after closing ---)
    static func parse(_ content: String) -> ([String: Any], String) {
        let lines = content.components(separatedBy: "\n")
        guard lines.first?.trimmingCharacters(in: .whitespaces) == "---" else {
            return ([:], content)
        }

        var frontmatter: [String: Any] = [:]
        var bodyStart = lines.count
        var i = 1
        var currentBlock: String? = nil
        var blockLines: [String] = []

        while i < lines.count {
            let line = lines[i]
            if line.trimmingCharacters(in: .whitespaces) == "---" {
                if let block = currentBlock {
                    frontmatter[block] = parseBlock(blockLines)
                    currentBlock = nil
                    blockLines = []
                }
                bodyStart = i + 1
                break
            }

            // Detect nested block (line ends with ":" and no value)
            if currentBlock == nil, let key = blockKey(line) {
                currentBlock = key
                i += 1
                continue
            }

            if currentBlock != nil {
                // If indented, it belongs to the block
                if line.hasPrefix("  ") || line.hasPrefix("\t") {
                    blockLines.append(line)
                    i += 1
                    continue
                } else {
                    // Block ended
                    frontmatter[currentBlock!] = parseBlock(blockLines)
                    currentBlock = nil
                    blockLines = []
                    // Don't increment — reparse this line as top-level
                    continue
                }
            }

            if let (k, v) = parseKeyValue(line) {
                frontmatter[k] = v
            }
            i += 1
        }

        // Flush any remaining block
        if let block = currentBlock {
            frontmatter[block] = parseBlock(blockLines)
        }

        let body = lines[bodyStart...].joined(separator: "\n")
        return (frontmatter, body)
    }

    // MARK: - Serialize

    /// Serializes frontmatter dict + body back to a complete markdown file.
    /// Key order is preserved via orderedKeys parameter.
    static func serialize(_ frontmatter: [String: Any], orderedKeys: [String], body: String) -> String {
        var lines = ["---"]
        for key in orderedKeys {
            guard let value = frontmatter[key] else { continue }
            lines.append(serializeKeyValue(key: key, value: value))
        }
        // Any keys not in orderedKeys
        for key in frontmatter.keys.sorted() where !orderedKeys.contains(key) {
            lines.append(serializeKeyValue(key: key, value: frontmatter[key]!))
        }
        lines.append("---")
        lines.append(body)
        return lines.joined(separator: "\n")
    }

    // MARK: - Private helpers

    private static func blockKey(_ line: String) -> String? {
        let trimmed = line.trimmingCharacters(in: .whitespaces)
        // A block header looks like "schedule:" with nothing after the colon
        if trimmed.hasSuffix(":") && !trimmed.hasPrefix("#") {
            return String(trimmed.dropLast())
        }
        return nil
    }

    private static func parseBlock(_ lines: [String]) -> [String: Any] {
        var result: [String: Any] = [:]
        var i = 0
        while i < lines.count {
            let line = lines[i]
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            // Detect block scalar: `key: |` or `key: >` with nothing else after
            if let colon = trimmed.firstIndex(of: ":") {
                let rest = String(trimmed[trimmed.index(after: colon)...]).trimmingCharacters(in: .whitespaces)
                if rest == "|" || rest == ">" || rest == "|-" || rest == ">-" {
                    let key = String(trimmed[..<colon]).trimmingCharacters(in: .whitespaces)
                    let parentIndent = leadingSpaces(line)
                    var collected: [String] = []
                    var j = i + 1
                    while j < lines.count {
                        let ln = lines[j]
                        if ln.trimmingCharacters(in: .whitespaces).isEmpty {
                            collected.append("")
                            j += 1
                            continue
                        }
                        if leadingSpaces(ln) <= parentIndent { break }
                        collected.append(ln)
                        j += 1
                    }
                    // Dedent by the minimum indent of non-empty lines
                    let minIndent = collected
                        .filter { !$0.trimmingCharacters(in: .whitespaces).isEmpty }
                        .map { leadingSpaces($0) }
                        .min() ?? 0
                    var dedented = collected.map { ln -> String in
                        if ln.count >= minIndent {
                            return String(ln.dropFirst(minIndent))
                        }
                        return ln
                    }
                    while dedented.last == "" { dedented.removeLast() }
                    let joined = dedented.joined(separator: "\n")
                    result[key] = rest.hasPrefix("|") ? joined : joined.replacingOccurrences(of: "\n", with: " ")
                    i = j
                    continue
                }
            }
            if let (k, v) = parseKeyValue(line) {
                result[k] = v
            }
            i += 1
        }
        return result
    }

    private static func leadingSpaces(_ line: String) -> Int {
        var n = 0
        for ch in line {
            if ch == " " { n += 1 }
            else if ch == "\t" { n += 4 }
            else { break }
        }
        return n
    }

    private static func parseKeyValue(_ line: String) -> (String, Any)? {
        let trimmed = line.trimmingCharacters(in: .whitespaces)
        guard let colonIdx = trimmed.firstIndex(of: ":") else { return nil }
        let key = String(trimmed[..<colonIdx]).trimmingCharacters(in: .whitespaces)
        let rest = String(trimmed[trimmed.index(after: colonIdx)...]).trimmingCharacters(in: .whitespaces)
        guard !key.isEmpty else { return nil }
        return (key, parseValue(rest))
    }

    private static func parseValue(_ s: String) -> Any {
        if s.isEmpty { return s }
        // Flow list: [a, b, c]
        if s.hasPrefix("[") && s.hasSuffix("]") {
            let inner = String(s.dropFirst().dropLast())
            if inner.trimmingCharacters(in: .whitespaces).isEmpty { return [String]() }
            return inner.components(separatedBy: ",").map {
                parseStringValue($0.trimmingCharacters(in: .whitespaces))
            }
        }
        // Bool
        if s == "true" || s == "yes" { return true }
        if s == "false" || s == "no" { return false }
        // Number
        if let i = Int(s) { return i }
        if let d = Double(s) { return d }
        return parseStringValue(s)
    }

    private static func parseStringValue(_ s: String) -> String {
        // Remove surrounding quotes
        if (s.hasPrefix("\"") && s.hasSuffix("\"")) ||
           (s.hasPrefix("'") && s.hasSuffix("'")) {
            return String(s.dropFirst().dropLast())
        }
        return s
    }

    private static func serializeKeyValue(key: String, value: Any) -> String {
        if let dict = value as? [String: Any] {
            // Nested block
            var lines = ["\(key):"]
            for (k, v) in dict.sorted(by: { $0.key < $1.key }) {
                lines.append(serializeScalar(key: k, value: v, indent: 2))
            }
            return lines.joined(separator: "\n")
        }
        return serializeScalar(key: key, value: value, indent: 0)
    }

    private static func serializeScalar(key: String, value: Any, indent: Int = 0) -> String {
        let pad = String(repeating: " ", count: indent)
        switch value {
        case let b as Bool:
            return "\(pad)\(key): \(b ? "true" : "false")"
        case let arr as [String]:
            let items = arr.map { quoteIfNeeded($0) }.joined(separator: ", ")
            return "\(pad)\(key): [\(items)]"
        case let arr as [Any]:
            let items = arr.map { "\($0)" }.joined(separator: ", ")
            return "\(pad)\(key): [\(items)]"
        case let s as String:
            // Multi-line strings are emitted as YAML block scalars (`|`) so that
            // newlines survive a round-trip through both our hand-rolled Python
            // and Swift parsers. Single-line strings use the existing quoting rules.
            if s.contains("\n") {
                let childPad = String(repeating: " ", count: indent + 2)
                let body = s.components(separatedBy: "\n")
                    .map { "\(childPad)\($0)" }
                    .joined(separator: "\n")
                return "\(pad)\(key): |\n\(body)"
            }
            if needsQuoting(s) {
                let escaped = s.replacingOccurrences(of: "\"", with: "\\\"")
                return "\(pad)\(key): \"\(escaped)\""
            }
            return "\(pad)\(key): \(s)"
        default:
            return "\(pad)\(key): \(value)"
        }
    }

    private static func quoteIfNeeded(_ s: String) -> String {
        if needsQuoting(s) { return "\"\(s.replacingOccurrences(of: "\"", with: "\\\""))\"" }
        return s
    }

    private static func needsQuoting(_ s: String) -> Bool {
        for scalar in s.unicodeScalars {
            if scalar.value > 127 { return true }    // non-ASCII (emoji, etc.)
        }
        let special: Set<Character> = [":", "{", "}", "[", "]", ",", "#", "&", "*", "?", "|", "-", "<", ">", "=", "!", "%", "@", "`"]
        return s.first.map { special.contains($0) } ?? false
    }
}
