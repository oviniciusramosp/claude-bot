#!/bin/bash
# SessionStart hook: log session info to a local file for traceability.
#
# Appends one line per session start to ~/.claude-bot/session-starts.log.
# Useful when bot sessions and interactive sessions get tangled — you can
# correlate a session ID to wall-clock time, model, and cwd.
#
# No output to Claude — purely observational.

set -e

input=$(cat)
session_id=$(echo "$input" | jq -r '.session_id // "?"')
cwd=$(echo "$input" | jq -r '.cwd // "?"')
model=$(echo "$input" | jq -r '.model // "?"')
source=$(echo "$input" | jq -r '.source // "?"')
agent=${AGENT_ID:-interactive}

log_file="$HOME/.claude-bot/session-starts.log"
mkdir -p "$(dirname "$log_file")"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] session=$session_id source=$source agent=$agent model=$model cwd=$cwd" >> "$log_file"

exit 0
