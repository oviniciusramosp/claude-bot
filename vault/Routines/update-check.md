---
title: "Update Check"
description: "Checks daily for updates to the Claude Code CLI or the claude-bot repo. Notifies only when there is something to update."
type: routine
created: 2026-04-08
updated: 2026-04-08
tags: [routine, maintenance, updates]
schedule:
  days: ["*"]
  times: ["10:00"]
model: haiku
context: minimal
enabled: true
---

[[Routines]]

Check whether updates are available for two components. Run the commands below and analyze the results:

**1. Claude Code CLI:**
```
/opt/homebrew/bin/claude --version
```
```
/opt/homebrew/bin/brew outdated --cask --greedy 2>/dev/null | grep claude-code
```

If `brew outdated` returns a line with `claude-code`, an update is available. If it returns nothing, it is up to date.

**2. claude-bot repo:**
```
cd ~/claude-bot && git fetch origin main --quiet 2>/dev/null && git rev-list HEAD..origin/main --count
```

If the count is > 0, there are new commits on the remote. Use `git log HEAD..origin/main --oneline` to list what changed.

**Response rules:**

- If BOTH are up to date: respond exactly `NO_REPLY` (nothing else)
- If ANY needs an update: send a message via Telegram (chat_id: 6948798151) using the bot token (read TELEGRAM_BOT_TOKEN from ~/claude-bot/.env) with the format:

🔄 *Updates available*

{for each item with an update, include a line:}
- *Claude Code:* X.Y.Z → A.B.C (`brew upgrade claude-code`)
- *claude-bot:* N commits behind (`cd ~/claude-bot && git pull`)

Send via urllib (no pip). After sending, respond `NO_REPLY`.
