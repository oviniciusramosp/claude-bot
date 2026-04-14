#!/bin/bash
# PostToolUse hook for Write|Edit: reminds about BOT_VERSION bump
# when claude-fallback-bot.py is modified.
#
# The rule in CLAUDE.md: any change to claude-fallback-bot.py requires
# bumping BOT_VERSION in the same commit, AND CFBundleShortVersionString
# in ClaudeBotManager/Sources/App/Info.plist must match.
#
# This hook injects a reminder into the conversation context. It doesn't
# block — it just makes the rule harder to forget.

set -e

input=$(cat)
file_path=$(echo "$input" | jq -r '.tool_input.file_path // ""')

# Match both absolute and relative paths to claude-fallback-bot.py
if echo "$file_path" | grep -E '(^|/)claude-fallback-bot\.py$' > /dev/null; then
    jq -n '{
      hookSpecificOutput: {
        hookEventName: "PostToolUse",
        additionalContext: "REMINDER: Changes to claude-fallback-bot.py require a version bump. Update BOT_VERSION in claude-fallback-bot.py AND CFBundleShortVersionString in ClaudeBotManager/Sources/App/Info.plist — both in the same commit. See CLAUDE.md \"Versioning and Commits\" for the PATCH/MINOR/MAJOR rules."
      }
    }'
fi

exit 0
