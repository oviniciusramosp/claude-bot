---
title: Audit Insecure Defaults
description: Detect fail-open insecure defaults (hardcoded secrets, fallback tokens, weak auth, permissive config) in the bot codebase. Use when auditing .env handling, reviewing new config paths, or hardening for distribution.
type: skill
created: 2026-04-11
updated: 2026-04-11
trigger: "when auditing security of the bot, reviewing environment variable handling, checking for hardcoded credentials, or preparing for public distribution"
tags: [skill, security, audit, secrets, config, hardening]
---

# Audit Insecure Defaults

Finds **fail-open** vulnerabilities — places where the bot runs insecurely with missing or default configuration. Distinguishes exploitable defaults from safe fail-secure patterns that crash early.

- **Fail-open (CRITICAL):** `token = os.environ.get("TELEGRAM_BOT_TOKEN") or "default"` → the bot starts with a weak/placeholder value
- **Fail-secure (SAFE):** `token = os.environ["TELEGRAM_BOT_TOKEN"]` → the bot crashes on startup if the var is missing

Per project distribution constraints, the bot is published on GitHub and every user configures their own `~/claude-bot/.env` and `vault/.env`. Insecure defaults are especially dangerous here — a forgotten fallback can ship to every downstream user.

## When to use

- Auditing any change to `claude-fallback-bot.py` that touches env vars, auth, or subprocess env
- Reviewing a new routine, pipeline step, or script that reads `vault/.env`
- Preparing a public release (bump a MINOR or MAJOR version)
- After a user reports a "worked without my env var set" symptom
- Before merging a PR that adds a new optional config flag

## When NOT to use

- Test fixtures scoped to `tests/` (sandboxed `HOME`, mocked env)
- `*.example` / `*.template` files committed for documentation
- Comments or docstrings that show example values
- Local dev conveniences that are clearly guarded (`if os.environ.get("DEV_MODE"):`)

When in doubt, trace the code path — does the bot actually start and serve traffic when the env var is missing, or does it `raise`?

## Rationalizations to reject

- **"It's just a development default"** → If it reaches `claude-fallback-bot.py` on `main`, it ships.
- **"The user's .env overrides it"** → Verify the override exists in the canonical path AND that the bot reads it before the fallback. Many users never open `~/claude-bot/.env`.
- **"This would never run without proper config"** → Prove it with a code trace. Many bots silently fail open.
- **"It's behind `AUTHORIZED_CHAT_ID`"** → Defense in depth; if the chat ID check itself has a default, the gate is useless.
- **"We'll fix it before release"** → Document now. "Later" rarely comes.

## Workflow

### 1. Discover

Map the bot's config surface:
- `~/claude-bot/.env` — operational config (Telegram token, paths)
- `vault/.env` — API keys for external services (Notion, Figma, Finnhub, etc.)
- `claude-fallback-bot.py` constants (`DEFAULT_MODEL`, `STREAM_EDIT_INTERVAL`, etc.)
- `com.claudebot.bot.plist` placeholders (`__HOME__`, `__SCRIPT_DIR__`)
- `ClaudeBotManager/Sources/Services/VaultService.swift` (if it caches env)

### 2. Search for fail-open patterns

Run targeted searches with Grep. Patterns to look for in Python:

```
# Fallback secrets
os\.environ\.get\(['"][A-Z_]+['"]\s*,\s*['"]
os\.getenv\(['"][A-Z_]+['"]\s*,\s*['"]
env\.get\([^)]*\)\s+or\s+['"]

# Hardcoded credentials
(password|api_key|token|secret|auth_key)\s*=\s*['"][^'"]{6,}['"]

# Weak defaults in flags
DEBUG\s*=\s*True
AUTH_REQUIRED\s*=\s*False
VERIFY_TLS\s*=\s*False

# Weak crypto in security contexts
md5|sha1\b|DES|RC4|ECB
```

For shell scripts:
```
: \$\{[A-Z_]+:=[^}]+\}   # ${VAR:=default}
```

Focus on production-reachable code, not `tests/` or comments.

### 3. Verify actual behaviour

For each match, trace the path:

- **When is this code executed?** Startup (`_load_env`), runtime (inside a handler), routine execution?
- **What happens if the variable is missing?** Does the bot `raise`, log and exit, or fall back?
- **Is there explicit validation?** `if not token: sys.exit("TELEGRAM_BOT_TOKEN is required")` is safe. `token = os.environ.get("TELEGRAM_BOT_TOKEN", "")` is not.

### 4. Confirm production impact

- If the bot crashes on missing config → **fail-secure**, usually safe. Still worth a clearer error message.
- If the bot continues with a weak value → **fail-open**, must fix.
- If the fallback is a hardcoded value that ships via `git` → CRITICAL — it reaches every distributed user.

### 5. Report with evidence

```
Finding: Hardcoded Telegram chat id fallback
Location: claude-fallback-bot.py:142
Pattern: AUTHORIZED_CHAT_ID = int(os.environ.get("TELEGRAM_CHAT_ID") or "-100")

Verification: The bot starts without TELEGRAM_CHAT_ID set. The chat id check at
line 1831 becomes `msg_chat == -100`, which matches no real chat — BUT any caller
that injects `-100` (e.g. a test fixture leaking to prod) becomes authorized.

Production impact: Ships to every GitHub user.
Exploitation: Low (crafted chat id), but defense-in-depth broken.
Fix: Replace with `int(os.environ["TELEGRAM_CHAT_ID"])` and fail fast on startup.
```

### 6. Apply the fix

- Replace fallback with explicit `KeyError` or early `sys.exit("VAR_NAME is required")`.
- Log the missing variable with context via `logging.error()` per the "zero silent errors" rule in `CLAUDE.md`.
- Add a test in `tests/test_bot_integration.py` or `tests/test_contracts.py` that confirms the bot refuses to start without the required variable.
- Bump `BOT_VERSION` (PATCH) in the same commit.

## Quick verification checklist

**Fallback secrets:** `SECRET = env.get(X) or Y`
→ Verify: bot starts without the var? secret used in auth / crypto / upstream API?
→ Skip: test fixtures, `*.example`

**Default credentials:** hardcoded `username`/`password` pairs
→ Verify: active in shipped code path? no runtime override?
→ Skip: disabled accounts, docs

**Fail-open flags:** `AUTH_REQUIRED = env.get(X, "false")`
→ Verify: default is insecure (false / disabled / permissive)?
→ Safe: the bot crashes, or the default is secure

**Weak crypto:** MD5 / SHA1 / DES / RC4 / ECB in security contexts
→ Verify: used for passwords, tokens, signatures?
→ Skip: non-security hashing (cache keys, checksums of public data)

**Permissive access:** shell scripts running as root, `chmod 0777`, public-by-default files under `~/.claude-bot/`
→ Verify: default allows unauthorized access?
→ Skip: explicitly justified permissive settings

**Debug features:** verbose stack traces in Telegram replies, enabled `--dangerously-skip-permissions` in a non-sandboxed path
→ Verify: enabled by default? exposed to the user?
→ Skip: internal `logging.debug()` that never hits Telegram

## Places to audit in this project

Based on the project layout in `CLAUDE.md`:

- `claude-fallback-bot.py` — `_load_env()`, `AUTHORIZED_CHAT_ID`, `CLAUDE_PATH`, `SYSTEM_PROMPT`, subprocess env construction
- `claude-bot.sh` — plist placeholders and install-time substitutions
- `com.claudebot.bot.plist` / `com.claudebot.menubar.plist` — environment keys
- `ClaudeBotManager/Sources/Services/VaultService.swift` — how env is read in Swift
- `vault/.env` loading in Claude CLI subprocess calls — make sure `vault/.env` is never echoed to Telegram or logs
- Every routine under `vault/Routines/` that calls an external API — check that missing API keys cause a loud failure, not a silent degradation

## Notes

- The project's test suite already guards against some of these via `test_contracts.py`. When you find a new class of insecure default, add a test there.
- Bumping `BOT_VERSION` for a security fix is MANDATORY — users need to see which build contains the fix.
- Keep fixes minimal — one insecure default per commit, so the security fix is easy to audit in isolation.

> Adapted from https://github.com/trailofbits/skills
