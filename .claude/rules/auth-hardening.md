# Auth hardening — Anthropic credential (v3.76+)

Loads when touching the auth code in `claude-fallback-bot.py`. Covers why the bot keeps its own Anthropic credential and how `/auth` diagnoses/recovers it remotely.

## The failure mode this eliminates

The bot spawns the Claude CLI, which by default authenticates with the **shared macOS keychain login** (`Claude Code-credentials`). The Claude **desktop app** and the CLI share that one OAuth identity. When the desktop app refreshes its token, the refresh token **rotates**, silently revoking the CLI's stored copy. Every Anthropic turn then fails with `401 Invalid authentication credentials`; the fallback chain falls through to z.AI (often out of balance → 429) and the user sees a 401 on Telegram with no way to fix it remotely.

## Prevention — bot-owned credential injected via `CLAUDE_CODE_OAUTH_TOKEN`

The CLI honors `CLAUDE_CODE_OAUTH_TOKEN` **over** the keychain (confirmed in the binary: *"… is set in your environment and will override …"*). So the bot keeps its OWN credential and injects it into the subprocess env for **native Anthropic runs only** (popped for z.AI, which is proxied with its own auth). When no bot credential exists, injection is a **no-op** → the CLI uses the keychain (fully backward-compatible).

**Store:** `~/.claude-bot/claude-auth.json` (0600, written atomically). Two shapes:
- `{"method": "setup_token", "token": "sk-ant-oat…"}` — long-lived token from `claude setup-token` (~1y, immune to desktop rotation). Static; no refresh needed.
- `{"method": "oauth", "access_token", "refresh_token", "expires_at"}` — minted by the in-Telegram `/auth login` PKCE flow. The bot refreshes it itself before expiry, so it's also independent of the keychain/desktop rotation.

**Resolution precedence** (`resolve_oauth_bearer()`, fail-open → None = keychain):
1. `claude-auth.json` (bot-managed) — for `oauth`, auto-refreshes when within `_OAUTH_REFRESH_SKEW` (300s) of expiry.
2. `CLAUDE_CODE_OAUTH_TOKEN` from env/`.env` (`_env_oauth_token()`) — simplest manual path for distribution users.
3. None → CLI keychain login.

Injection point: `ClaudeRunner.run()`, just before the z.AI branch — `clean_env.pop("CLAUDE_CODE_OAUTH_TOKEN")` then re-add for `provider == "anthropic"`.

## OAuth endpoints (extracted from the 2.1.x CLI binary)

- client_id `9d1c250a-e61b-44d9-88ed-5944d1962f5e` (public, ships in the CLI)
- authorize `https://claude.com/cai/oauth/authorize` (params: `code=true`, PKCE `code_challenge`/`S256`, `state`, redirect to the callback below)
- token `https://platform.claude.com/v1/oauth/token` (grants: `authorization_code`, `refresh_token`)
- redirect/callback `https://platform.claude.com/oauth/code/callback` (success page shows a `<code>#<state>` string to paste)

**Cloudflare gotcha:** a bare urllib request to the token endpoint is blocked (HTTP 403, error 1010). Every request MUST send a CLI-like `User-Agent` (`_oauth_user_agent()`) + `anthropic-beta: oauth-2025-04-20`. The success page returns the code as `<code>#<state>`; `_oauth_exchange_code()` strips the suffix.

## `/auth` command (primary chat only — `_block_if_secondary`)

- `/auth` / `/auth status` — source (bot token vs keychain), method, oauth expiry, keychain expiry, **live haiku probe** through the real injection path (`_auth_probe`).
- `/auth login` — generates a PKCE pair + authorize URL, stores `_pending_oauth[chat]` (15-min TTL), sends the URL as plain text (auto-linked). The user authorizes on any device.
- `/auth code <código>` — exchanges the code for tokens; a **bare paste** of a code-like token (no spaces, ≥20 chars) is also intercepted in `_handle_text` while a login is pending.
- `/auth set <token>` — installs a long-lived `sk-ant-…` token (`method: setup_token`).
- `/auth logout` — clears `claude-auth.json` → reverts to keychain.

## Proactive alert

When a turn fails and `classify_error → AUTH` on a native Anthropic model, `_alert_auth_failure()` notifies all primary chats (throttled to once / 10 min via `_last_auth_alert`) with the remote-fix steps — instead of silently falling through. The friendly 401 message (`_translate_error`) also points to `/auth`.

## Tests

`tests/test_auth_hardening.py` (29 tests): PKCE/S256, authorize URL, store round-trip + 0600, bearer resolution (setup_token / oauth fresh / oauth refresh / refresh-failure-returns-stale / env fallback / file>env precedence), code exchange (mock network), `/auth` dispatch, bare-code interceptor (and that a normal sentence is NOT hijacked), proactive-alert throttle. Network is always mocked via `_oauth_token_request`; the live probe is patched in dispatch tests.

## Maintenance notes

- The OAuth endpoints/scopes are reverse-engineered from the CLI binary — if Anthropic changes them, re-extract with `strings <cli-binary> | grep -E 'oauth|claude.com'`. The `/auth set` paste path (long-lived token) is the resilient fallback if the PKCE flow ever breaks.
- A long-lived `setup_token` is the most robust (no refresh machinery). `/auth login` (oauth) is the zero-terminal recovery path.
