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
| `effort` | string | — | Reasoning effort: `low`, `medium`, `high`, `xhigh`, or `max`. If omitted, Anthropic steps default to `DEFAULT_EFFORT` (env, default `max`); z.AI is not forced. See `.claude/rules/multi-provider-models.md` |
| `voice` | bool | `false` | Also send response as audio (TTS) |
| `notify` | string | `final` | Pipeline only: `final\|all\|summary\|none` |
| `script` | string | — | Routine only (v3.82): shell command run instead of a model turn — see "Script routines" |
| `timeout` | int | `300` | Seconds for a `script:` routine (max 3600) |
| `context_from` | string/list | — | Routine only (v3.82): `self` and/or routine names of the same agent whose previous outputs are injected into the prompt |
| `context_runs` | int | `1` | How many past runs per `context_from` source (max 20) |
| `failure_deliver` | string | `notify` | Routine only (v3.82): `notify` posts failures to Telegram; `silent` only logs/records them |
| `fallback` | string | `off` | Routine only (v3.93): `auto` = when the model fails, run again on the next model without asking (Fable limit → Opus, account limit → GPT), that run only |

### Routine task construction

Every trigger (scheduler interval/clock, `/run`, resume after restart, control API `/routine/run`, Reactions) builds its `RoutineTask` through `routine_task_from_frontmatter()`. Add new routine fields there — before v3.82 each trigger parsed its own subset, and the control API silently dropped `voice`.

### Script routines (v3.82)

`script:` makes `_execute_routine_task` delegate to `_execute_script_routine`: `/bin/bash -c <script>` with cwd = repo root, `AGENT_ID`/`AGENT_WORKSPACE`/`VAULT_DIR`/`ROUTINE_NAME` exported, stdin closed. Exit 0 + empty stdout (or bare `NO_REPLY`) = silence; other stdout is sent verbatim (`parse_mode=""`, capped at `ROUTINE_SCRIPT_MAX_OUTPUT`). Non-zero exit / timeout = failure with the stderr tail. No progress message and no vault checkpoint (deterministic, and a rollback would hide what the script did). The routine body may be empty when `script:` is set — the empty-body guards at every routine entry point accept it.

**Security:** refused for any agent that is a default or topic agent of a secondary chat (`_agent_serves_secondary_chat`). Those agents run under `--permission-mode dontAsk` but can write their own `Routines/`, so `script:` would be a shell escape out of the allowlist.

### Run history and `context_from` (v3.82)

Every routine run (model or script) appends `{ts, time_slot, status, output, error}` to `~/.claude-bot/routine-history/<agent>/<routine>.jsonl` (`record_routine_run`, last `ROUTINE_HISTORY_KEEP`=20 kept). With `context_from`, `build_routine_context_block` renders the last `context_runs` runs of each source (truncated to `ROUTINE_HISTORY_INJECT_CHARS` each, oldest first) as an "Execuções anteriores" block placed before the task. Sources resolve within the routine's own agent only (isolamento total). Routines still run with `session_id=None` — continuity comes from the recorded outputs, not from resuming a transcript that would grow forever.

`failure_deliver: silent` suppresses the FAILED message and the lesson-draft notice for routine failures (they are still logged at ERROR, recorded in state/history/execution report). A bot-level crash of the routine thread is always notified.

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

**Voice notes in (v3.94).** `_handle_voice` transcribes with Apple's on-device **SpeechAnalyzer** first: `scripts/transcribe.swift`, compiled by the bot itself (`_ensure_transcriber` → `build_transcriber()`, Command Line Tools `swiftc`, background thread at startup, rebuilt when the source is newer) into `~/.claude-bot/bin/transcribe`; it reads the Telegram OGG directly, punctuates, and runs offline (macOS 26+; the language model downloads on first use). `hear` (SFSpeechRecognizer, via ffmpeg → WAV) is only the fallback: on 2026-11-23 it returned "Bom dia obrigado" for a three-sentence note. Tests skip the build (`CLAUDE_BOT_SKIP_TRANSCRIBER_BUILD`). Tests: `tests/test_v394_ux.py`.

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
- Bot detects `advisor.sh` in Bash tool hints and sets `activity_type = "consulting_advisor"` → shows 🤓 reaction on Telegram (🧠 is not an allowed reaction)

**Configuration:** `ADVISOR_MODEL` in `~/claude-bot/.env` (default: `opus`).

## Lessons (compound engineering)

Each agent owns its own `Lessons/` folder (`<id>/Lessons/`) so lessons stay scoped to the context that produced them. Two entry points:

- **Automatic:** the session consolidator records lessons when the session detects a resolved bug or clear learning
- **Manual:** `/lesson <text>` writes `<current-agent>/Lessons/manual-YYYY-MM-DD-HHMM.md` with structured frontmatter (`type: lesson`, `status: recorded`)

The SYSTEM_PROMPT instructs Claude to scan `Lessons/` before similar tasks. Tests in `tests/test_lessons.py`.

## Auto-compact and session rotation

- **Native auto-compact (v3.82)**: context size is the Claude CLI's job. `ClaudeRunner.run` sets `CLAUDE_CODE_AUTO_COMPACT_WINDOW=AUTO_COMPACT_WINDOW` (env `AUTO_COMPACT_WINDOW`, default 400000; `0`/`off` = CLI default = full model window) for native Anthropic runs, unless the bot's own environment already sets it. The CLI clamps it to the model window and floors it at 100k, and compacts on real token count. Verified in `--print --resume` mode on CLI 2.1.292: it emits `{"type":"system","subtype":"compact_boundary","compact_metadata":{"trigger":"auto","pre_tokens":…,"post_tokens":…}}`, which `_handle_event` logs and stores in `runner.native_compact`.
- **Memory snapshot**: every `MEMORY_SNAPSHOT_INTERVAL` (20) turns, `_auto_compact(session, compact=False)` snapshots the session to the journal and refreshes the agent hot cache — silently, without `/compact`. (Before v3.82 this rode on our own every-N-turns `/compact`.)
- **Idle compact** (`IDLE_COMPACT_HOURS`) still runs our `/compact`: the CLI's idle compaction is gated by a server-side flag that is off by default.
- **Auto-rotate**: after `AUTO_ROTATE_THRESHOLD` (80) turns, resets session_id (next message starts a new session)
- Applies only to interactive sessions (routines use session_id=None)

## Watchdog

`bot-watchdog.sh` runs via launchd every 60s (`com.claudebot.watchdog.plist`). Two flag files in `~/.claude-bot/`:
- `.watchdog-notified` — set when bot is down and alert was sent; cleared on recovery
- `.watchdog-disabled` — if exists, watchdog exits silently (maintenance mode)

Restart order: `launchctl kickstart gui/<uid>/com.claudebot.bot` first; fallback to `launchctl bootstrap` if service not registered. **Do not use `launchctl start`** — deprecated on Darwin 24+.

Disable/enable via Telegram: `/watchdog off` / `/watchdog on`. Or via shell: `touch`/`rm` the disable flag.

## Restart mechanism

`scripts/bot-self-restart.sh` is called by `/restart`. Uses `launchctl kickstart -k` (atomic kill+restart, Darwin 24+ idiom). Falls back to `bootout`/`bootstrap`. **Do not use `launchctl load/unload`** — deprecated and unreliable with `set -e` (caused restarts to silently fail on Darwin 25.x). Polls for a new PID (max 40s) before confirming.

## Knowledge Graph (Graphify)

The vault has a knowledge graph at `vault/.graphs/graph.json`, generated by the `scripts/vault-graph-builder.py` script (no LLM). For deep on-demand analysis, use `/graphify vault/` which triggers the full Graphify with semantic extraction.

- The `vault-graph-update` routine regenerates the lightweight graph daily at 4am
- The graph maps nodes (files) and edges (wikilinks + related) with confidence labels
- Query the graph before extensive globbing in the vault to find relationships

## FTS5 vault index (v3.18+)

The bot ships a stdlib SQLite FTS5 full-text index over each agent's journals, lessons, notes, and weekly rollups. It powers Active Memory v2 (FTS primary path, graph fallback), SessionStart auto-recall, the three MCP tools `vault_search_text` / `vault_timeline` / `vault_get_excerpt`, and the write-through path from every Python journal writer.

**Location:** `~/.claude-bot/vault-index.sqlite`. Treated as a regenerable cache — deleting the file is safe, the next daily rebuild repopulates.

**Schema (version 1):** `entries(id, agent, kind, rel_path, section_path, date, title, tags, body, private, mtime, ingested_at)` + `entries_fts` (FTS5 virtual table with Porter stemming + unicode61) + `index_meta(key, value)` for the schema version. Every query includes `WHERE entries.agent = ?` — enforced inside the library helper, not by the caller.

**Library:** `scripts/vault_index.py`. Public API: `connect`, `rebuild`, `rebuild_agent`, `upsert_agent`, `upsert_file`, `upsert_journal_section`, `search`, `timeline`, `get_excerpt`, `strip_private`, `discover_agents`.

**Daily rebuild:** `vault/main/Routines/vault-index-update.md` — runs at 04:05 (staggered 5 min after `vault-graph-update` to avoid disk contention). Calls `python3 scripts/vault-index-update.py` which does a full DROP+INSERT rebuild and prints `N rows, K agents (…), Tms`.

**Weekly rollup:** `vault/main/Routines/journal-weekly-rollup.md` — runs Mondays at 05:00. Calls `python3 scripts/journal-weekly-rollup.py`, which iterates every agent via `discover_agents()` (contract C7) and produces `vault/<agent>/Journal/weekly/YYYY-Www.md` summaries. The driver upserts each new rollup into the FTS index inline.

### Future-proof contracts — C1 to C8

These contracts MUST stay true for every existing agent (`main`, `crypto-bro`, `digests`, `parmeirense`) AND every agent created in the future. Every test in `tests/test_vault_index.py` and `tests/test_session_start_recall.py` exists to keep one of them honest.

- **C1 — Agent discovery via `iter_agent_ids()`.** The index library never enumerates agents any other way. `rebuild(agent_ids=None)` falls back to `discover_agents()` in the library; callers inside the bot process should pass the bot's own `iter_agent_ids()` result. When a new agent is created, the next rebuild picks it up with ZERO code changes.
- **C2 — `agent_id` is a required positional parameter on every helper.** `search`, `timeline`, `get_excerpt`, `upsert_file`, `upsert_agent`, `rebuild_agent`, `upsert_journal_section` all raise `ValueError` on empty agent. No "default to main" convenience overload — `main` is a normal agent, not a fallback.
- **C3 — `WHERE entries.agent = ?` is built inside the library helper.** Callers never write SQL. Covered by `test_search_respects_agent_isolation`.
- **C4 — Full rebuild is the authority; write-through is best-effort.** The daily routine does DROP+INSERT so deleted/renamed agents vanish automatically, renamed agents get the new id, and legacy `vault/Journal/*.md` (pre-v3.1) is assigned to `agent="main"` to match `guard-journal-write.sh`. Write-through only inserts.
- **C5 — Schema migrations are additive-only, version-gated.** `index_meta.schema_version = 1` today. Future versions use `ALTER TABLE ADD COLUMN` gated on the stored version. If migration fails, the DB file is renamed to `vault-index.sqlite.broken-v{n}` and a fresh one is created — the bot logs a WARNING and keeps running.
- **C6 — New-agent immediate bootstrap.** `_run_agent_create_skill` detects a newly created agent via its existing `before/after = set(iter_agent_ids())` diff and calls `_vault_index_bootstrap_agent(new_id)` synchronously. Without it the user would wait until 04:05 next day before auto-recall surfaces the new agent.
- **C7 — Global routines iterate via `discover_agents()` / `iter_agent_ids()`.** Both `vault-index-update` and `journal-weekly-rollup` walk the agent list internally, mirroring `journal-audit`. Adding an agent requires no edit to any routine file.
- **C8 — Every new MCP tool and bot helper that touches the vault takes `agent_id` explicitly.** This rule is enforced by convention (code review) and by the `test_helpers_raise_on_empty_agent` test.

### Active Memory v2 — FTS first, graph fallback

Since v3.18, `_active_memory_lookup()` tries the FTS5 index first via `_active_memory_fts_lookup()`. If the index doesn't exist yet (fresh install, pre-rebuild), returns nothing, or errors, the function falls back to the pre-existing graph-based scoring against `vault/.graphs/graph.json`. Existing installs that haven't built the index yet keep working without regression until their first 04:05 run.

### SessionStart auto-recall

`_session_start_recall(prompt, session)` fires only on the very first turn of a new session (`message_count == 0 AND session_id is None`). It runs an FTS search over journals, weekly rollups, and lessons for the current agent and injects a compact `## Recent Context` block into the user prompt so the user picks up where the last session left off. Fail-open: missing index, empty result, or any error returns None and the prompt proceeds unchanged. `include_private=False` — rows from files with any `<private>` marker are hidden here for extra caution, even though their private TEXT is already stripped from the index.

### Write-through helpers

`_vault_index_upsert(agent, rel_path, journal_section=None)` is the single Python write-through helper. Every Python writer that touches vault content calls it:

- `_snapshot_session_to_journal` (line ~6537) — auto-compact snapshot
- `record_manual_lesson` (line ~2684) — `/lesson <text>` command
- `_run_agent_create_skill` (line ~7447) — via `_vault_index_bootstrap_agent`

The MCP server at `mcp-server/vault_mcp_server.py` uses its own `_vault_index_write_through()` helper (lazy connection, cached across tool calls) for `vault_append_journal` and `vault_create_note`. Both paths import the SAME `scripts/vault_index.py` library — there is exactly one implementation of the upsert logic.

### Private markers

`<private>...</private>` blocks (case-insensitive, DOTALL) are stripped from the body BEFORE it goes into FTS, and rows from files that had any private marker are flagged `private=1`. The raw markdown file is never modified. Default `search()` returns private-flagged rows (their public content is fair game); `include_private=False` hides them entirely, used by SessionStart auto-recall. See `vault/CLAUDE.md` "Private journal content" for the user-facing explanation.

**Tests:** `tests/test_vault_index.py` (19 tests), `tests/test_session_start_recall.py` (13 tests), `tests/test_journal_weekly_rollup.py` (3 tests).
