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
- Default port: `9870`
- Requires `PINCHTAB_ALLOW_EVALUATE=1` for JavaScript form submission (X and other sites)

Commands:
```
pinchtab nav <url> --port 9870       # navigate
pinchtab text --port 9870            # extract text
pinchtab snap -i -c --port 9870      # interactive snapshot
pinchtab click <ref> --port 9870     # click element
pinchtab fill <ref> "text" --port 9870  # fill form field
```

## References

External repositories and documents worth consulting when working on the bot.

- **claude-code-system-prompts** — https://github.com/Piebald-AI/claude-code-system-prompts
  - Mirror of Claude Code's internal system prompts (Plan/Explore/Task subagents, compact, security review, etc.), updated per release. Useful reference when refining the bot's `SYSTEM_PROMPT` and routine prompts.
  - Usage: read when designing new routines or auditing the bot's prompt strategy. Cross-check against `claude-fallback-bot.py` to see which pieces of Claude Code's upstream prompting are worth mirroring into the bot's own prompts.
