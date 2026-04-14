#!/bin/bash
# PreToolUse hook for Write|Edit: protect journal files from overwrites.
#
# Journal files (vault/<agent>/Journal/*.md and legacy vault/Journal/*.md)
# must only be mutated via:
#   1. MCP tool vault_append_journal (from Claude subprocess sessions)
#   2. Python _snapshot_session_to_journal / journal-audit.py (direct fs)
#
# The Write and Edit tools would let Claude rewrite the whole file, which
# defeats the append-only contract that /important and session consolidation
# rely on. This hook converts the soft "append-only" instruction in those
# prompts into a hard invariant.
#
# Behavior:
# - Bot sessions (AGENT_ID set): hard deny via permissionDecision=deny,
#   with a reason that redirects Claude to vault_append_journal.
# - Interactive sessions (no AGENT_ID): permissionDecision=ask so the
#   dev can still hand-edit a journal for debugging after confirming.
#
# Unaffected paths:
# - MCP tool writes via direct filesystem (not through Write/Edit tools)
# - journal-audit.py uses Python write_text() (not through Claude tools)
# - _snapshot_session_to_journal() uses open("a") in-process

set -e

input=$(cat)
tool_name=$(echo "$input" | jq -r '.tool_name // ""')
file_path=$(echo "$input" | jq -r '.tool_input.file_path // ""')

# Defensive filter — matcher already restricts to Write|Edit.
case "$tool_name" in
    Write|Edit) ;;
    *) exit 0 ;;
esac

[ -z "$file_path" ] && exit 0

# Match both absolute and relative paths. Accepts:
#   vault/Journal/2026-04-14.md                (legacy v3.0)
#   vault/main/Journal/2026-04-14.md           (v3.1 flat per-agent)
#   /abs/.../vault/crypto-bro/Journal/foo.md   (absolute variant)
# Rejects:
#   vault/main/Notes/anything.md               (not a journal)
#   vault/main/Journal/subdir/foo.md           (nested — not a real journal)
journal_regex='(^|/)vault/([^/]+/)?Journal/[^/]+\.md$'

if ! echo "$file_path" | grep -E "$journal_regex" > /dev/null; then
    exit 0
fi

reason="Direct Write/Edit of journal files is blocked to preserve the append-only contract. Use the MCP tool 'vault_append_journal' instead (args: text required, agent_id optional — defaults to \"main\"). It handles file creation, frontmatter, and timestamping."

if [ -n "$AGENT_ID" ]; then
    # Bot session: hard deny.
    jq -n --arg reason "$reason" '{
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: $reason
      }
    }'
    exit 0
fi

# Interactive dev session: ask so the dev can override if really needed.
jq -n --arg reason "$reason" --arg file "$file_path" '{
  hookSpecificOutput: {
    hookEventName: "PreToolUse",
    permissionDecision: "ask",
    permissionDecisionReason: ("Journal file " + $file + " — " + $reason + " Confirm if this is an intentional manual edit.")
  }
}'
exit 0
