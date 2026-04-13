#!/usr/bin/env bash
# advisor.sh — Strategic advisor for Claude bot executor models.
#
# Usage: bash advisor.sh "Your question with full context"
#
# The executor model (Sonnet/Haiku/GLM) calls this via Bash when stuck,
# confused, or looping. It spawns a fresh Claude CLI session with the
# ADVISOR_MODEL (default: opus) for pure reasoning — no tools, no vault
# access, no side-effects. The advice is returned as plain text so the
# executor can continue informed by it.
#
# Design:
#   - Clears GLM proxy env vars so the advisor always hits real Anthropic auth
#   - Enforces a per-session call limit (default: 5) via a counter file
#   - Hard timeout of 120s and $1.00 cost cap per invocation
#   - Advisor runs with --allowedTools "" to prevent recursive calls and
#     unintended file/network side-effects

set -euo pipefail

QUESTION="${1:-}"
if [[ -z "$QUESTION" ]]; then
    echo "Usage: advisor.sh \"Your question with full context\"" >&2
    exit 1
fi

# --- Clear GLM proxy env vars ---
# When the executor is a GLM session, ANTHROPIC_BASE_URL and
# ANTHROPIC_AUTH_TOKEN point to the local z.AI proxy. Unset them so
# the advisor uses the native Claude CLI authentication (macOS keychain).
unset ANTHROPIC_BASE_URL
unset ANTHROPIC_AUTH_TOKEN
unset ANTHROPIC_API_KEY

# --- Call limit (per session) ---
MAX_CALLS=5
SESSION_ID="${ADVISOR_SESSION_ID:-default}"
COUNTER_FILE="/tmp/advisor-${SESSION_ID}.count"

count=0
if [[ -f "$COUNTER_FILE" ]]; then
    count=$(cat "$COUNTER_FILE" 2>/dev/null || echo 0)
fi

if (( count >= MAX_CALLS )); then
    echo "⚠️ Advisor limit reached ($MAX_CALLS calls for this session). Continuing without advice." >&2
    exit 1
fi

echo $(( count + 1 )) > "$COUNTER_FILE"

# --- Model ---
ADVISOR_MODEL="${ADVISOR_MODEL:-opus}"

# --- Locate claude CLI ---
CLAUDE_PATH="${CLAUDE_PATH:-/opt/homebrew/bin/claude}"
if [[ ! -x "$CLAUDE_PATH" ]]; then
    for candidate in /usr/local/bin/claude ~/.local/bin/claude; do
        if [[ -x "$candidate" ]]; then
            CLAUDE_PATH="$candidate"
            break
        fi
    done
fi

if [[ ! -x "$CLAUDE_PATH" ]]; then
    echo "❌ Claude CLI not found. Set CLAUDE_PATH env var." >&2
    exit 1
fi

# --- Run advisor ---
# --allowedTools "" disables all tools: advisor is pure reasoning only.
# Timeout wrapper ensures the parent session isn't held hostage.
timeout 120 "$CLAUDE_PATH" \
    --print \
    --model "$ADVISOR_MODEL" \
    --output-format text \
    --allowedTools "" \
    --max-budget-usd 1.00 \
    --dangerously-skip-permissions \
    -p "$QUESTION"
