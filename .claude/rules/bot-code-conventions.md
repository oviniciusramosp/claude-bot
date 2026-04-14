---
paths:
  - "claude-fallback-bot.py"
  - "claude-bot-menubar.py"
---

# Bot code conventions

Loaded when editing `claude-fallback-bot.py` or `claude-bot-menubar.py`.

## Error handling — zero silent errors

When encountering an error, **never treat it as a one-off**. Follow this mandatory flow:

1. **Investigate the root cause** — don't fix just the symptom. Trace the error path to the real origin (invalid data, inconsistent state, race condition, etc.)
2. **Fix the root cause** — the fix must eliminate the class of error, not just the observed instance
3. **Add structural protection** — implement validation, guard clause, or check to prevent recurrence. If the error can return due to external factors (API down, missing file, etc.), add resilient handling
4. **Ensure visibility** — every error that cannot be prevented MUST notify the user (via Telegram, log, or both). No `except: pass`, no `try/except` that swallows errors silently. If catching an exception, at minimum log with `logging.error()` and notify on Telegram when possible

**Principle:** The user must know when something went wrong — even if the bot recovers automatically. Silent errors accumulate and create bigger problems later.

## Common Tasks

### Adding a new command

1. Add a `cmd_<name>` method to the `ClaudeTelegramBot` class
2. Register it in the `handler_map` dict inside `_handle_text()` (search `handler_map = {`)
3. Add it to `HELP_TEXT` so `cmd_help()` surfaces it
4. Add a dispatch test in `tests/test_bot_integration.py` and, if the command mutates state, a round-trip test

### Changing default model/timeouts

Edit the constants at the top of `claude-fallback-bot.py`:
- `DEFAULT_MODEL` — default model for new sessions
- `config["timeout"]` — default timeout in seconds
- `STREAM_EDIT_INTERVAL` — seconds between Telegram message edits
- `TYPING_INTERVAL` — seconds between typing indicators
