---
title: "pgrep-excludes-caller-ancestors"
description: "macOS pgrep hides the caller's whole ancestor chain, so any bot liveness check run from inside a bot-spawned Claude session reports the bot as down; use pgrep -a or ps"
type: note
created: 2026-10-16
updated: 2026-10-16
tags: [note, main, macos, pgrep, watchdog, diagnostics]
---

[[main/Notes/agent-notes|Notes]]

`pgrep -f "claude-fallback-bot.py"` returns **empty** when run from a Claude
session that the bot itself spawned — even though the bot is running. From
`man pgrep`:

> **-a** Include process ancestors in the match list. By default, the current
> pgrep or pkill process and all of its ancestors are excluded (unless -v is used).

A bot-spawned session's ancestry is `zsh → claude → claude-fallback-bot.py`, so
the bot is an ancestor of whatever `pgrep` the session runs, and pgrep silently
drops it. Observed 2026-10-16: the only PIDs invisible to `pgrep -f .` were
PID 1, the bot, the session's own `claude` process, and its own shell — exactly
the ancestor chain.

**Consequence for diagnostics.** Any agent asking "is the bot running?" from
inside a bot session gets a false negative. `claude-bot.sh status` is affected
too — it uses bare `pgrep -f` in three places. Use one of these instead:

```bash
pgrep -a -f "claude-fallback-bot.py"      # -a includes ancestors
ps -ax -o pid,command | grep fallback-bot  # or just ps
launchctl list | grep com.claudebot        # PID + last exit status per job
```

**The watchdog and `/restart` are NOT affected**, which is why this went
unnoticed for months:

- `bot-watchdog.sh` runs as its own launchd job (`com.claudebot.watchdog`), so
  the bot is never its ancestor and its `pgrep` gate works normally.
- `scripts/bot-self-restart.sh` is spawned by the bot, so its initial
  `OLD_PID=$(pgrep ...)` wrongly yields `0` — harmless, because the only use is
  the `"$NEW_PID" != "$OLD_PID"` comparison, and after `kickstart -k` the new
  bot process is a fresh sibling (not an ancestor) and so IS visible.

**Running the restart script from a bot session needs detaching.** `kickstart -k`
kills the launchd job, which takes the session's own process tree with it, so the
script dies before it can poll and confirm. Spawn it in a new session
(`subprocess.Popen(..., start_new_session=True)`) with a delay, so the current
turn's reply is delivered first and the confirmation still fires.
