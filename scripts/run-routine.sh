#!/usr/bin/env bash
# Usage: run-routine.sh <routine-name>
#
# Triggers a bot routine or pipeline without user intervention.
# Call this from within a Claude session whenever your task requires
# a follow-up routine to run — do NOT ask the user to /run it manually.
#
# Example:
#   bash scripts/run-routine.sh crypto-news-produce
#
# Exit codes: 0 = enqueued, 1 = error (token missing, routine not found, server down).

set -euo pipefail

ROUTINE="${1:-}"
if [[ -z "$ROUTINE" ]]; then
    echo "Usage: run-routine.sh <routine-name>" >&2
    exit 1
fi

TOKEN_FILE="${HOME}/.claude-bot/.control-token"
if [[ ! -f "$TOKEN_FILE" ]]; then
    echo "Error: control token not found at $TOKEN_FILE — is the bot running?" >&2
    exit 1
fi

TOKEN=$(cat "$TOKEN_FILE")
PORT=27182

response=$(curl -sf -w "\n%{http_code}" \
    -X POST "http://127.0.0.1:${PORT}/routine/run" \
    -H "X-Bot-Token: ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"name\": \"${ROUTINE}\"}" 2>&1 || true)

body=$(printf '%s' "$response" | head -n -1)
code=$(printf '%s' "$response" | tail -n 1)

if [[ "$code" == "200" ]]; then
    echo "Routine '${ROUTINE}' enqueued."
else
    echo "Failed to trigger '${ROUTINE}' (HTTP ${code}): ${body}" >&2
    exit 1
fi
