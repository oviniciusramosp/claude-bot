# Troubleshooting Guide

Diagnosis and resolution for common issues with the claude-bot.

## Bot Won't Start

**Check the `.env` file exists and has required variables:**

```bash
cat ~/claude-bot/.env
```

Required variables:
- `TELEGRAM_BOT_TOKEN` -- must be set (get from @BotFather)
- `TELEGRAM_CHAT_ID` -- must be set (your Telegram numeric chat ID)

**Check launchd service status:**

```bash
./claude-bot.sh status
```

If the service is not loaded:
```bash
./claude-bot.sh install
./claude-bot.sh start
```

**Check logs for startup errors:**

```bash
tail -50 ~/.claude-bot/bot.log
tail -20 ~/.claude-bot/launchd-stderr.log
```

**Common startup errors:**

| Error | Cause | Fix |
|-------|-------|-----|
| `TELEGRAM_BOT_TOKEN is empty` | Missing `.env` or variable not set | Create/edit `~/claude-bot/.env` |
| `ModuleNotFoundError` | Running wrong Python version | Use `python3` (macOS system or Homebrew) |
| `Address already in use` (port 27182) | Another bot instance running | `./claude-bot.sh stop` then `./claude-bot.sh start` |

## Messages Not Received

**Check TELEGRAM_CHAT_ID is correct:**

The bot silently ignores messages from unauthorized chat IDs. Verify your chat ID matches what's in `.env`. The bot supports comma-separated IDs for multiple chats:

```env
TELEGRAM_CHAT_ID=123456789,-1001234567890
```

**Check the bot is polling:**

Look for `getUpdates` entries in the log:
```bash
tail -100 ~/.claude-bot/bot.log | grep -i "updates\|polling"
```

**Check Telegram API connectivity:**

```bash
curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe"
```

If this fails, the bot token may be invalid or network connectivity is broken.

**Group chats:**

For group/supergroup chats, the bot must be added as a member. The group's chat ID (negative number) must be in `TELEGRAM_CHAT_ID`.

## Claude Not Responding

**Check CLAUDE_PATH exists:**

```bash
ls -la /opt/homebrew/bin/claude
# or whatever CLAUDE_PATH is set to
which claude
```

If the Claude CLI is not installed, follow [Claude Code installation docs](https://docs.anthropic.com/en/docs/claude-code).

**Check model availability:**

The bot defaults to `sonnet`. If you get API errors, try switching models:
- Send `/sonnet`, `/haiku`, or `/opus` in Telegram
- Or use `/model` for the picker

**Check timeout:**

Default timeout is 600 seconds (10 minutes). If Claude is working on a long task:
- Use `/timeout 1200` to increase
- Check if the task is still running with `/status`

**Check for API errors in logs:**

```bash
tail -50 ~/.claude-bot/bot.log | grep -i "error\|failed\|stderr"
```

Common API errors the bot translates:

| Error Pattern | Meaning |
|--------------|---------|
| `overloaded` | Anthropic servers under heavy load -- wait and retry |
| `rate limit` / `429` | Too many requests -- wait 1-2 minutes |
| `authentication` / `401` | Invalid API key -- check `console.anthropic.com` |
| `permission` / `403` | Account lacks access to the requested model |
| `context length` / `too many tokens` | Session context too large -- use `/compact` or `/clear` |
| `credit` / `billing` / `quota` | Account out of credits |

## Session Issues

**"No active session" or unexpected context:**

Sessions are automatically created per chat/topic. If state becomes inconsistent:
1. Use `/sessions` to list all sessions.
2. Use `/switch <name>` to switch to the correct one.
3. Use `/new <name>` to create a fresh session.
4. Use `/clear` to reset the current session (clears Claude's context).

**Session context mismatch (Claude forgot previous conversation):**

The bot uses `--resume` with Claude Code's session IDs. If Claude seems to have lost context:
- The session may have been auto-compacted. Use `/status` to check message count.
- Try `/compact` to explicitly compact (Claude summarizes and continues).
- If the issue persists, start a fresh session with `/new`.

**Sessions file corruption:**

Sessions are stored in `~/.claude-bot/sessions.json`. If it becomes corrupted:
```bash
# Back up the file
cp ~/.claude-bot/sessions.json ~/.claude-bot/sessions.json.bak
# Delete to reset
rm ~/.claude-bot/sessions.json
# Restart the bot
./claude-bot.sh restart
```

## Audio Not Working

**Check tool installation:**

```bash
./claude-bot.sh install-deps
```

This checks and installs both `ffmpeg` and `hear`.

**Verify ffmpeg:**

```bash
/opt/homebrew/bin/ffmpeg -version
# or
which ffmpeg
```

If not found: `brew install ffmpeg`

**Verify hear:**

```bash
~/.claude-bot/bin/hear --version
```

If not found, install manually:
```bash
./claude-bot.sh install-deps
```

Or download from [github.com/sveinbjornt/hear](https://github.com/sveinbjornt/hear/releases).

**Check macOS Dictation is enabled:**

`hear` uses Apple's SFSpeechRecognizer, which requires Dictation:
- Go to **System Settings > Keyboard > Dictation**
- Enable Dictation
- Download the language pack for your `HEAR_LOCALE`

**Check HEAR_LOCALE:**

The default locale is `pt-BR`. To change:
```env
HEAR_LOCALE=en-US
```

After changing, restart the bot.

**Audio conversion fails (ffmpeg error):**

- Check that the audio file isn't corrupted.
- ffmpeg has a 30-second timeout for conversion -- very long audio may need manual conversion.

**Transcription returns empty:**

- Ensure Dictation is enabled in macOS settings.
- The audio might be too short, too quiet, or in an unsupported language.
- `hear` has a 120-second timeout.

## Routines Not Running

**Check the routine file has all required fields:**

Required frontmatter fields:
```yaml
title: ...
type: routine
schedule:
  times: ["09:00"]
  days: [mon, tue, wed]
model: sonnet
enabled: true
```

Missing any of these causes the routine to be silently skipped (check logs for warnings).

**Check `enabled: true`:**

Routines with `enabled: false` are ignored by the scheduler.

**Check schedule format:**

- `times` must be a list of `"HH:MM"` strings in 24-hour format.
- `days` must be a list of lowercase day abbreviations (`mon`, `tue`, `wed`, `thu`, `fri`, `sat`, `sun`) or `["*"]` for every day.
- `until` date must not be in the past.

**Check the scheduler is running:**

```bash
tail -50 ~/.claude-bot/bot.log | grep -i "routine\|scheduler"
```

The scheduler checks routines every 60 seconds.

**Check the state file:**

```bash
cat ~/.claude-bot/routines-state/$(date +%Y-%m-%d).json
```

If a routine shows status `"running"` from a previous crashed run, it won't re-execute. Restart the bot -- it auto-cleans stale `running` entries on startup.

## Pipeline Failures

**Check pipeline structure:**

A pipeline needs:
1. A `.md` file in `Routines/` with `type: pipeline` in frontmatter.
2. A fenced ` ```pipeline ` block in the body defining steps.
3. Step prompt files at `Routines/{pipeline-name}/steps/{step-id}.md`.

**Check step dependencies form a valid DAG:**

Circular dependencies are detected and rejected at parse time. Check logs:
```bash
grep "dependency cycle" ~/.claude-bot/bot.log
```

**Check step prompt files exist:**

```bash
ls vault/Routines/{pipeline-name}/steps/
```

Missing prompt files cause step warnings in logs.

**Check timeout settings:**

- Default step timeout: 1200 seconds (20 min)
- Default inactivity timeout: 300 seconds (5 min)
- Steps that produce no output for `inactivity_timeout` seconds are killed.

**Check /tmp space:**

Pipeline workspaces live in `/tmp/claude-pipeline-{name}-{timestamp}/`. If `/tmp` is full, pipelines fail. Stale workspaces older than 24 hours are auto-cleaned on bot startup.

**Inspect a failed pipeline workspace:**

Failed pipeline workspaces are intentionally kept (not deleted) for debugging:
```bash
ls /tmp/claude-pipeline-*/data/
```

## Manager App Issues

**Build failures:**

```bash
cd ClaudeBotManager
swift build
```

Common issues:
- Missing Xcode Command Line Tools: `xcode-select --install`
- Wrong Swift version: the app targets macOS with SwiftUI

**Stale status:**

The manager app communicates with the bot via a control HTTP server on port 27182. If status appears stale:
1. Check the bot is running: `./claude-bot.sh status`
2. Check the control token file exists: `ls ~/.claude-bot/.control-token`
3. Restart the bot to regenerate the token.

**Config not saving:**

The manager edits `~/claude-bot/.env`. Check file permissions:
```bash
ls -la ~/claude-bot/.env
```

## Logs

### Log Locations

| Log File | Content |
|----------|---------|
| `~/.claude-bot/bot.log` | Main application log (rotating: 5 MB x 3 backups) |
| `~/.claude-bot/launchd-stdout.log` | Process stdout when running via launchd |
| `~/.claude-bot/launchd-stderr.log` | Process stderr when running via launchd |
| `~/.claude-bot/routines-state/YYYY-MM-DD.json` | Daily routine execution state |

### Tailing Logs

```bash
# Application log (most useful)
./claude-bot.sh logs

# Error logs only
./claude-bot.sh errors

# Manual tail with filtering
tail -f ~/.claude-bot/bot.log | grep -i "error\|warning"
```

## Common Error Messages

| Error Message | Cause | Solution |
|--------------|-------|----------|
| `Claude CLI not found at /opt/homebrew/bin/claude` | Claude Code not installed or wrong path | Install Claude Code CLI or set `CLAUDE_PATH` in `.env` |
| `API overloaded` | Anthropic servers busy | Wait a few minutes and retry |
| `Rate limit (429)` | Too many requests | Wait 1-2 minutes |
| `Authentication error (401)` | Invalid API key | Check key at console.anthropic.com |
| `Context too long` | Session accumulated too many tokens | `/compact` to compress or `/clear` to reset |
| `Transcription disabled` | Missing ffmpeg or hear | Run `./claude-bot.sh install-deps` |
| `ffmpeg conversion failed` | Audio format issue or ffmpeg problem | Check ffmpeg installation, retry |
| `hear transcription failed` | Dictation not enabled or language mismatch | Enable Dictation in System Settings, check `HEAR_LOCALE` |
| `getFile failed` | Telegram file download issue | Retry sending the file |
| `Routine skipped -- missing required fields` | Routine frontmatter incomplete | Add missing fields (title, type, schedule, model, enabled) |
| `Pipeline has dependency cycle` | Circular step dependencies | Fix `depends_on` references in pipeline definition |
| `Workspace not found` | `CLAUDE_WORKSPACE` path doesn't exist | Check path in `.env` or create the directory |
