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

- **PinchTab** — Web browsing CLI with logged-in sessions (X, Threads). Prefer over urllib to avoid bot fingerprinting.
- Repo/docs: https://github.com/pinchtab/pinchtab
- Default port: `9867`
- Requires `PINCHTAB_ALLOW_EVALUATE=1` for JavaScript form submission (X and other sites)

Commands:
```
pinchtab nav <url> --port 9867       # navigate
pinchtab text --port 9867            # extract text
pinchtab snap -i -c --port 9867      # interactive snapshot
pinchtab click <ref> --port 9867     # click element
pinchtab fill <ref> "text" --port 9867  # fill form field
```

### Tab cleanup rule

**Every routine/pipeline that uses PinchTab MUST close its tabs after finishing.** Unclosed tabs accumulate, exhaust Chrome resources, and cause `context deadline exceeded` errors that block all subsequent PinchTab operations.

Add at the end of every routine prompt that uses PinchTab:
```
**Cleanup:** After extracting all needed content, close the current tab:
```bash
pinchtab tabs close --port 9867
```
```

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

## References

External repositories and documents worth consulting when working on the bot.

- **claude-code-system-prompts** — https://github.com/Piebald-AI/claude-code-system-prompts
  - Mirror of Claude Code's internal system prompts (Plan/Explore/Task subagents, compact, security review, etc.), updated per release. Useful reference when refining the bot's `SYSTEM_PROMPT` and routine prompts.
  - Usage: read when designing new routines or auditing the bot's prompt strategy. Cross-check against `claude-fallback-bot.py` to see which pieces of Claude Code's upstream prompting are worth mirroring into the bot's own prompts.
