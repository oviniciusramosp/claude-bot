#!/bin/bash
# PreToolUse hook for Bash: warn on destructive commands.
#
# Behavior:
# - In interactive sessions (no AGENT_ID env var): returns permissionDecision=ask
#   so the user gets a confirmation prompt.
# - In bot sessions (AGENT_ID set, meaning claude-fallback-bot.py spawned us):
#   logs to ~/.claude-bot/destructive-bash.log but does NOT block — the bot runs
#   with --dangerously-skip-permissions so blocking would halt legitimate work.
#
# Patterns match common destructive operations. Intentionally conservative —
# false negatives are acceptable, false positives in interactive sessions
# just cost one extra confirmation click.

set -e

input=$(cat)
cmd=$(echo "$input" | jq -r '.tool_input.command // ""')

# Regex: destructive patterns. Anchored to word boundaries where possible.
# - rm -rf / rm -fr with any path
# - git reset --hard, git clean -fd, git checkout --, git push --force / -f
# - launchctl remove / unload
# - dropdb, drop database, drop table
# - kill -9 on pid 1
# - >/dev/sdX or mkfs
# - brew uninstall, npm uninstall -g
destructive_regex='(\brm\s+(-[rf]+\s+|--(recursive|force))+)|(git\s+reset\s+--hard)|(git\s+clean\s+-[a-z]*f)|(git\s+checkout\s+--)|(git\s+push\s+(--force|-f\b))|(launchctl\s+(remove|unload))|(drop\s+(database|table))|(\bdropdb\b)|(kill\s+-9\s+1\b)|(>\s*/dev/sd[a-z])|(\bmkfs\b)|(brew\s+uninstall)|(npm\s+uninstall\s+-g)'

if echo "$cmd" | grep -iE "$destructive_regex" > /dev/null 2>&1; then
    if [ -n "$AGENT_ID" ]; then
        # Bot session: log only, don't block.
        log_file="$HOME/.claude-bot/destructive-bash.log"
        mkdir -p "$(dirname "$log_file")"
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] agent=$AGENT_ID cmd=$cmd" >> "$log_file"
        exit 0
    fi

    # Interactive session: ask for confirmation.
    jq -n --arg cmd "$cmd" '{
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "ask",
        permissionDecisionReason: ("Destructive command detected: " + $cmd + " — confirm before proceeding.")
      }
    }'
    exit 0
fi

exit 0
