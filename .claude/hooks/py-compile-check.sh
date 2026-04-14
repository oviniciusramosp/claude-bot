#!/bin/bash
# PostToolUse hook for Write|Edit: verify Python files compile after edits.
#
# Catches syntax errors immediately instead of waiting for the next test run
# or manual `python3 -m py_compile`. Uses exit code 2 to signal the error back
# to Claude so it can fix it in the same turn.

set -e

input=$(cat)
file_path=$(echo "$input" | jq -r '.tool_input.file_path // ""')

# Only check .py files
if ! echo "$file_path" | grep -E '\.py$' > /dev/null; then
    exit 0
fi

# Skip if file doesn't exist (deleted, or path resolution issue)
if [ ! -f "$file_path" ]; then
    exit 0
fi

# Try to compile
if ! err=$(python3 -m py_compile "$file_path" 2>&1); then
    echo "Python syntax error in $file_path:" >&2
    echo "$err" >&2
    exit 2
fi

exit 0
