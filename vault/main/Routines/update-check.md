---
title: "Update Check"
description: "Checks daily for updates to Claude Code CLI and claude-bot repo/macOS app. Summarizes changes, recommends urgency, offers install button."
type: routine
created: 2026-04-08
updated: 2026-04-14
tags: [routine, maintenance, updates]
schedule:
  days: ["*"]
  times: ["10:00"]
model: sonnet
context: minimal
effort: low
enabled: true
---

Check whether updates are available for three components. Run ALL commands below and analyze results.

## 1. Claude Code CLI

```bash
/opt/homebrew/bin/claude --version 2>/dev/null
```
```bash
/opt/homebrew/bin/brew info --cask claude-code 2>/dev/null | head -5
```
```bash
/opt/homebrew/bin/brew outdated --cask --greedy 2>/dev/null | grep claude-code
```

If `brew outdated` returns a line with `claude-code`, an update is available. Extract the NEW version from `brew info` output (first line shows `claude-code: X.Y.Z`). Extract the CURRENT version from `claude --version`.

If an update IS available, fetch the changelog to summarize what changed:
```bash
curl -sL "https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md" 2>/dev/null | head -200
```

From the changelog, find the entries between the CURRENT version and the NEW version. Summarize the most important changes (max 5-6 bullet points, focus on user-visible features and important bug fixes).

Then assess urgency:
- **Update now** — if there are security fixes, critical bug fixes, or features the user likely needs
- **Update when convenient** — if changes are minor improvements or edge-case fixes
- **Can wait** — if changes are mostly internal/cosmetic

## 2. claude-bot repo

```bash
cd ~/claude-bot && git fetch origin main --quiet 2>/dev/null && git rev-list HEAD..origin/main --count
```

If count > 0, list what changed:
```bash
cd ~/claude-bot && git log HEAD..origin/main --oneline
```

Also compare local vs remote BOT_VERSION:
```bash
cd ~/claude-bot && grep '^BOT_VERSION' claude-fallback-bot.py | head -1
```
```bash
cd ~/claude-bot && git show origin/main:claude-fallback-bot.py 2>/dev/null | grep '^BOT_VERSION' | head -1
```

## 3. macOS app version check

```bash
cd ~/claude-bot && grep -A1 'CFBundleShortVersionString' ClaudeBotManager/Sources/App/Info.plist | tail -1 | sed 's/[^0-9.]//g'
```
```bash
cd ~/claude-bot && git show origin/main:ClaudeBotManager/Sources/App/Info.plist 2>/dev/null | grep -A1 'CFBundleShortVersionString' | tail -1 | sed 's/[^0-9.]//g'
```

If the local macOS app version differs from remote, flag it as needing rebuild.

## Response rules

Read the bot token and chat ID:
```bash
grep '^TELEGRAM_BOT_TOKEN=' ~/claude-bot/.env | cut -d= -f2 | tr -d '"'"'"
```
```bash
grep '^TELEGRAM_CHAT_ID=' ~/claude-bot/.env | cut -d= -f2 | tr -d '"'"'"
```

**If ALL components are up to date:** respond exactly `NO_REPLY` (nothing else).

**If ANY component needs an update:** send a Telegram message using `urllib` with inline keyboard buttons. Build the message and buttons as follows:

### Message format (Markdown parse_mode):

```
🔄 *Updates disponíveis*

*Claude Code:* `{current}` → `{new}`
{changelog summary as bullet points}
💡 _{urgency recommendation}_

*claude-bot:* {N} commits atrás
{oneline commit list}

*macOS App:* rebuild necessário (local {local_ver} → remote {remote_ver})
```

Only include sections for components that actually need updating.

### Inline keyboard buttons:

Build a `reply_markup` JSON with buttons for each available update:

- If Claude Code needs update: `{"text": "⬆️ Atualizar Claude Code", "callback_data": "update:claude-code"}`
- If repo needs update: `{"text": "⬆️ Atualizar claude-bot", "callback_data": "update:repo"}`

Arrange buttons vertically (one per row).

### Send via urllib:

```python
import json, urllib.request

payload = {
    "chat_id": CHAT_ID,
    "text": message_text,
    "parse_mode": "Markdown",
    "reply_markup": json.dumps({"inline_keyboard": buttons})
}
data = urllib.parse.urlencode(payload).encode()
urllib.request.urlopen(
    urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data)
)
```

After sending, respond exactly `NO_REPLY`.

## Example Output

When updates are found, the Telegram message should look like:

```
🔄 *Updates disponíveis*

*Claude Code:* `2.1.89` → `2.1.92`
- Wizard interativo para setup do Bedrock
- Breakdown por modelo no /cost
- Fix subagent falhando após tmux ser fechado
- Write tool 60% mais rápido para diffs grandes
- Removidos /tag e /vim
💡 _Atualizar quando conveniente — melhorias incrementais, sem fix crítico._

*claude-bot:* 3 commits atrás
- dc3ff64 feat: dynamic shell substitution in skills
- 6d009b6 chore: add Claude Code hooks
- 12ea244 fix: z.AI proxy absorbs 429s

[⬆️ Atualizar Claude Code]  [⬆️ Atualizar claude-bot]
```

When everything is up to date:
```
NO_REPLY
```
