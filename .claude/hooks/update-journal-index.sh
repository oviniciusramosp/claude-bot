#!/bin/bash
# PostToolUse hook for Write: regenerates agent-journal.md index whenever
# a dated Journal entry (YYYY-MM-DD.md) is written inside any agent's
# Journal/ folder.
#
# vault_indexes.py walks all vault-query marker blocks and rebuilds the
# inner content in-place — manual edits outside the markers are preserved.
# Running it here keeps agent-journal.md always in sync without any manual
# /indexes step.

set -e

input=$(cat)
file_path=$(echo "$input" | jq -r '.tool_input.file_path // ""')

# Match: vault/<agent>/Journal/YYYY-MM-DD.md  (absolute or relative path)
# Excludes agent-journal.md itself to avoid redundant runs on index writes.
if echo "$file_path" | grep -E 'vault/[^/]+/Journal/[0-9]{4}-[0-9]{2}-[0-9]{2}\.md$' > /dev/null 2>&1; then
    # Resolve project root relative to this hook file's location (.claude/hooks/)
    PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
    python3 "$PROJECT_DIR/scripts/vault_indexes.py" 2>/dev/null || true
fi

exit 0
