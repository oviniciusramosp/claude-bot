---
title: Tooling Preferences
description: Tool preference map by task type. Check before choosing an approach.
type: reference
created: 2026-04-07
updated: 2026-04-11
tags: [reference, tooling]
---

# Tooling Preferences

Which tool to use for each type of task. Check before choosing an approach.

## Web browsing

**Use Safari first.** Safari on this Mac holds the owner's logins (X, Threads, banks, Google…). Drive it with `scripts/safari.py` from Bash or Python — each page opens in its **own Safari window** and only that window is closed, so the owner's tabs are never touched.

```bash
python3 scripts/safari.py text <url> [--settle 3] [--scroll 3]   # page text
python3 scripts/safari.py js <url> "<JS expression>"            # JSON result
python3 scripts/safari.py html <url>                            # full HTML
python3 scripts/safari.py check                                 # is Safari scriptable?
```

From Python (routine scripts): `sys.path.insert(0, "<repo>/scripts"); import safari`, then
`with safari.open_page(url, settle=3) as page: page.js(...)`, `page.text()`, `page.scroll(passes=3)`, `page.inject_file(path)`. Errors raise `safari.SafariError` with a plain reason — report it, never skip silently.

- **Not logged in?** If the page lands on a login screen, say so plainly ("o Safari não está logado no X") — never type passwords; the owner logs in once in Safari.
- **Plain public pages** (articles, docs, RSS): WebFetch/WebSearch are fine and faster.
- **Backup:** if Safari can't do something, the owner can enable Chrome with the Claude extension — ask before relying on it.
- Guest (secondary) chats must never drive the owner's Safari.
- PinchTab was removed (2026-11-16). Don't use `pinchtab` or ports 9867/9869/9870.

## Telegram notifications from pipelines/routines

- **`scripts/telegram_notify.py`** — Send messages to the correct Telegram topic for any agent.
- **Auto-detects the agent** from `AGENT_ID` env var (injected by the bot harness) or from CWD. No `--agent` flag needed in most cases.
- Reads `chat_id`/`thread_id` from agent frontmatter — single source of truth for routing.
- `TELEGRAM_BOT_TOKEN` is read from the project `.env`.

```bash
# Inside a pipeline/routine — use $TELEGRAM_NOTIFY (injected by harness, no hardcoded path):
python3 $TELEGRAM_NOTIFY "Hello world"
python3 $TELEGRAM_NOTIFY "Hello" --parse-mode Markdown
echo "message" | python3 $TELEGRAM_NOTIFY --stdin
```

```python
# From Python code in a step:
import subprocess, os
subprocess.run(["python3", os.environ["TELEGRAM_NOTIFY"], "--text", text], check=True)
```

Three routing env vars are also injected for direct use in curl/urllib if needed:
- `AGENT_CHAT_ID` — Telegram chat_id of the owning agent
- `AGENT_THREAD_ID` — Telegram thread_id (empty string if none)
- `AGENT_ID` — agent slug (e.g. `parmeirense`)

## Triggering routines from within a session

**`scripts/run-routine.sh <name>`** — Enqueue a routine or pipeline without user intervention.

Use this whenever your task requires a follow-up routine. **Never ask the user to `/run` it manually** — call the script yourself via Bash.

```bash
bash scripts/run-routine.sh crypto-news-produce-v2
bash scripts/run-routine.sh vault-indexes-update
```

How it works: the script calls the bot's local control server (port 27182) using the session token at `~/.claude-bot/.control-token`. The routine is enqueued exactly as if the user had typed `/run <name>`. The bot must be running for this to work.

## References

External repositories and documents worth consulting when working on the bot.

- **claude-code-system-prompts** — https://github.com/Piebald-AI/claude-code-system-prompts
  - Mirror of Claude Code's internal system prompts (Plan/Explore/Task subagents, compact, security review, etc.), updated per release. Useful reference when refining the bot's `SYSTEM_PROMPT` and routine prompts.
  - Usage: read when designing new routines or auditing the bot's prompt strategy. Cross-check against `claude-fallback-bot.py` to see which pieces of Claude Code's upstream prompting are worth mirroring into the bot's own prompts.
