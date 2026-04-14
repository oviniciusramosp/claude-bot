---
paths:
  - "claude-fallback-bot.py"
  - "claude-bot-menubar.py"
  - "scripts/advisor.sh"
  - "scripts/vault_query.py"
  - "scripts/vault-graph-builder.py"
  - "scripts/vault_lint.py"
  - "scripts/journal-audit.py"
  - "vault/**/Routines/*.md"
  - "vault/**/Skills/*.md"
---

# Vault runtime features — claude-bot

Context for the Python implementation of the bot's runtime features: routines, voice, active memory, skill hints, advisor, lessons, auto-compact, watchdog. Loads when touching `claude-fallback-bot.py` or related scripts.

## Routines

### Frontmatter fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `type` | string | `routine` | `routine` or `pipeline` |
| `schedule.times` | list | — | Times HH:MM (24h) — required unless `interval` is set |
| `schedule.interval` | string | — | Run every N units: `30m`, `4h`, `3d`, `2w` — replaces `times` |
| `schedule.days` | list | `["*"]` | Weekdays or `["*"]` for all (works with `times` and `interval`) |
| `schedule.monthdays` | list | — | Days of month e.g. `[1, 15]` — filter for both clock and interval modes |
| `schedule.until` | string | — | End date YYYY-MM-DD (optional) |
| `model` | string | `sonnet` | Model to use |
| `agent` | string | — | **Legacy in v3.0.** Folder location is the source of truth: `<id>/Routines/foo.md` implies `agent=id`. The `agent:` frontmatter field is still accepted for backcompat and logged with a warning if it disagrees with the folder. |
| `enabled` | bool | `true` | Enable/disable the routine |
| `context` | string | `full` | `minimal` = skip vault system prompt, use only CLAUDE.md |
| `effort` | string | — | Reasoning effort: `low`, `medium`, or `high` (CLI default if omitted) |
| `voice` | bool | `false` | Also send response as audio (TTS) |
| `notify` | string | `final` | Pipeline only: `final\|all\|summary\|none` |

### Minimal vs full context

- **`full`** (default): Claude receives the `SYSTEM_PROMPT` that instructs it to read Journal, Tooling, vault. Good for routines that need vault context.
- **`minimal`**: The `--append-system-prompt` is omitted. Claude runs only with the CLAUDE.md files from the directory hierarchy (automatic by CLI). Saves tokens and is faster for one-off tasks.

### Pipeline notifications

Pipelines notify via `_notify_success` / `_notify_failure`. The step marked with `output: telegram` has its output (content of the `data/{id}.md` file) sent to Telegram. If the step already sends to Telegram via its own API (e.g., publisher), use `output: none` to avoid duplication. The `notify` field controls:
- `final` — sends output of the marked step (or last step) on completion
- `all` — sends progress on each step completion
- `summary` — sends compact summary (X/Y steps in Nm Ns)
- `none` — silent (failures always notify)

### `NO_REPLY` routine

If the output of a routine (not pipeline) is exactly `NO_REPLY`, the bot sends nothing to Telegram. Used for routines that send messages manually or that should run silently.

### Built-in routines (committed to repo)

| Routine | Description |
|---------|-------------|
| `update-check` | Checks daily for Claude Code CLI (brew) or repo (git) updates. Notifies only when there's something to update. |
| `vault-graph-update` | Regenerates the vault's lightweight knowledge graph (`vault/.graphs/graph.json`) from frontmatter and wikilinks. No LLM cost. Runs daily at 4am. Active Memory depends on this graph. |
| `vault-indexes-update` | Auto-regenerates the marker blocks inside `Routines.md`, `Skills.md`, and `Agents.md` so index files stay in sync with actual vault content. |
| `vault-lint` | Daily vault hygiene check — frontmatter completeness, broken wikilinks, schedule sanity, orphan notes, stale routines. Runs `scripts/vault_lint.py`. |
| `journal-audit` | Nightly audit (23:59) that checks all agents' journals for completeness, fixes frontmatter, and fills gaps from the activity log. |

## Voice / TTS

The bot supports voice responses (Text-to-Speech) via macOS `say` + ffmpeg (OGG Opus):

- **`/voice on`** — enables TTS for all subsequent session messages (text + audio)
- **`/voice off`** — disables TTS
- **`#voice` in message** — one-shot TTS (audio only, no text)
- **`voice: true` in frontmatter** — routines/pipelines deliver response as audio

Voice follows the `HEAR_LOCALE` (default `pt-BR` → Luciana voice). The TTS prompt instructs Claude to respond in the configured language, without emojis, short and conversational. Emojis are removed from audio via `_strip_markdown()`.

## Active Memory (v2.34.0+, isolated per-agent in v3.0)

Active Memory is a deterministic pre-reply hook inspired by OpenClaw v2026.4.10. Before each interactive Claude turn, the bot scores non-skill nodes from `vault/.graphs/graph.json` against the user's prompt and appends a compact `## Active Memory` block — with short (≤400 char) file excerpts — to the system prompt. No LLM call, ~50 ms typical, 200 ms hard budget, fail-open.

- **Isolamento total (v3.0):** only nodes whose `source_file` lives under `<current-agent>/` qualify. A session on `crypto-bro` never sees Main's or `parmeirense`'s notes.
- **Scope:** interactive chat only. Routines and pipelines with `context: minimal` automatically skip it because they pass `system_prompt=None`.
- **Excluded node types:** `skill` (covered by the skill hint helper) and `history` (churn-y logs).
- **Per-session toggle:** `/active-memory [on|off|status]` — persists to `sessions.json` via the `Session.active_memory` field.
- **Global toggle:** `ACTIVE_MEMORY_ENABLED = True` constant at the top of `claude-fallback-bot.py`.
- **Cache:** `_active_memory_graph_cache` dict keyed by absolute graph path, mtime-invalidated so the daily `vault-graph-update` routine transparently refreshes it.
- **Tests:** `tests/test_active_memory.py` + `tests/test_agent_isolation.py`.

## Graph-based skill hints (isolated per-agent in v3.0)

Separate from Active Memory but complementary: `_select_relevant_skills(agent_id)` reads the same `vault/.graphs/graph.json` and injects a short `<hint>Relevant skills for this task: …</hint>` prefix into the user prompt on every interactive message. Filters to nodes whose `source_file` starts with `<agent_id>/Skills/`. Controlled by `SKILL_HINTS_ENABLED = True`. Tests in `tests/test_skill_hints.py` + `tests/test_agent_isolation.py`.

The two helpers run in sequence inside `_run_claude_prompt()`:
1. `_find_relevant_skills()` (via `vault_query`) — appends "## Available Skills" block to the system prompt
2. `_active_memory_lookup()` — appends "## Active Memory" block to the system prompt
3. `_select_relevant_skills()` (via graph.json) — prepends `<hint>` to the user prompt

## Advisor (v3.8.0+)

Executor models (Sonnet, Haiku, GLM) can escalate to a strategic advisor (default: Opus) mid-task via `scripts/advisor.sh`. The flow mirrors the Claude API's native `advisor_20260301` tool, implemented at the CLI/Bash level:

1. Executor encounters difficulty (stuck, looping, uncertain about architecture)
2. Executor calls `bash scripts/advisor.sh "question with full context"` — Bash blocks while the script runs
3. Script spawns a fresh Claude CLI with `ADVISOR_MODEL` (pure reasoning, `--allowedTools ""`), clearing any GLM proxy env vars first
4. Advisor returns plain-text guidance as Bash stdout
5. Executor resumes, informed by the advice

**Key design choices:**
- `--allowedTools ""` on the advisor: prevents recursive calls and unintended side-effects
- GLM proxy env cleanup (`unset ANTHROPIC_BASE_URL ANTHROPIC_AUTH_TOKEN ANTHROPIC_API_KEY`): ensures advisor always uses native Anthropic auth even when the executor is a GLM session
- Per-session call limit: 5 (counter file at `/tmp/advisor-<SESSION_ID>.count`)
- Hard cost cap: `--max-budget-usd 1.00` per invocation; hard timeout: 120s
- Advisor instructions are only injected into `effective_sp` when `session.model != ADVISOR_MODEL` (no self-loop)
- Bot detects `advisor.sh` in Bash tool hints and sets `activity_type = "consulting_advisor"` → shows 🧠 reaction on Telegram

**Configuration:** `ADVISOR_MODEL` in `~/claude-bot/.env` (default: `opus`).

## Lessons (compound engineering)

Each agent owns its own `Lessons/` folder (`<id>/Lessons/`) so lessons stay scoped to the context that produced them. Two entry points:

- **Automatic:** the session consolidator records lessons when the session detects a resolved bug or clear learning
- **Manual:** `/lesson <text>` writes `<current-agent>/Lessons/manual-YYYY-MM-DD-HHMM.md` with structured frontmatter (`type: lesson`, `status: recorded`)

The SYSTEM_PROMPT instructs Claude to scan `Lessons/` before similar tasks. Tests in `tests/test_lessons.py`.

## Auto-compact and session rotation

- **Auto-compact**: every `AUTO_COMPACT_INTERVAL` (25) turns, runs `/compact` in background
- **Auto-rotate**: after `AUTO_ROTATE_THRESHOLD` (80) turns, resets session_id (next message starts a new session)
- Applies only to interactive sessions (routines use session_id=None)

## Watchdog

`bot-watchdog.sh` runs via launchd every 60s (`com.claudebot.bot-watchdog.plist`):
- If the bot is not running: restarts via `launchctl start` and notifies on Telegram
- If the bot came back: sends recovery message
- Uses flag file (`~/.claude-bot/.watchdog-notified`) to notify only once per downtime

## Knowledge Graph (Graphify)

The vault has a knowledge graph at `vault/.graphs/graph.json`, generated by the `scripts/vault-graph-builder.py` script (no LLM). For deep on-demand analysis, use `/graphify vault/` which triggers the full Graphify with semantic extraction.

- The `vault-graph-update` routine regenerates the lightweight graph daily at 4am
- The graph maps nodes (files) and edges (wikilinks + related) with confidence labels
- Query the graph before extensive globbing in the vault to find relationships
