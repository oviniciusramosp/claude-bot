---
paths:
  - "claude-fallback-bot.py"
  - "scripts/advisor.sh"
---

# Multi-provider models (Claude + z.AI GLM + ChatGPT)

The bot runs three LLM providers side-by-side. The first two share the `claude` CLI binary; the third uses OpenAI's `codex` CLI via `CodexRunner`:

## Maximum effort + maximum context (v3.70)

By default the bot runs every Anthropic turn at **maximum reasoning effort** and the **1M-token context window**. Both are resolved by pure, provider-aware helpers so they never leak into a runtime that can't honour them:

- `resolve_effort(effort, provider)` — an explicit caller value (routine/pipeline `effort:`, `/effort`) always wins. Otherwise Anthropic defaults to `DEFAULT_EFFORT` (env, default `max`; valid: `low|medium|high|xhigh|max`). **z.AI is left untouched** when no explicit value is given — the gateway may not honour the CLI's thinking-budget config. **Codex** maps the scale down via `CODEX_EFFORT_MAP` (`max`/`xhigh`→`high`) since `model_reasoning_effort` tops out at `high`.
- `resolve_model_alias(model)` — maps a bare Anthropic alias to a pinned concrete id via env (`OPUS_MODEL`/`SONNET_MODEL`/`HAIKU_MODEL`). The CLI's `opus` alias can **lag** a model release — e.g. for a while `--model opus` resolved to `claude-opus-4-7` even after `--model claude-opus-4-8` already worked, so `OPUS_MODEL=claude-opus-4-8` was needed to get the newer id. Without an env pin, built-in `MODEL_ALIAS_DEFAULT_PIN` applies: `sonnet` → `claude-sonnet-5-5` and `haiku` → `claude-haiku-5-5`, because those bare aliases lag (`haiku` → `claude-haiku-4-5` even on CLI 2.1.292; `sonnet` → `claude-sonnet-5` on 2.1.274). Opus is not pinned: `claude-opus-5-5` needs CLI 2.1.280+, and the `opus` alias reaches it from there (→ `claude-opus-5` on 2.1.274). Fable's real id is `claude-fable-5-1` (`claude-fable-5-5` does not exist). Set an env var to the bare alias to opt out of a default pin.
- `resolve_max_context_model(model)` — appends the `[1m]` variant (`opus` → `opus[1m]`) for **native Anthropic** models only (`MAX_CONTEXT` env, default on). z.AI is proxied through a sonnet alias and has its own context limits; Codex is a separate CLI — both are skipped. Already-suffixed names are never double-appended.

**A stderr warning is not a failure.** CLIs print `[claude-code:unrecognized_model] {"model":"…"}` for ids newer than their catalog even when the API answers normally. `ClaudeRunner.result_is_error` (from the `result` event) short-circuits `_looks_like_model_unavailable()`: a clean result means the variant worked, whatever stderr says.

**Model/context fail-safe (distribution-critical).** If the account/plan rejects the enhanced variant (a pinned newer id and/or `[1m]`), `ClaudeRunner.run()` retries **once** on the bare alias + base context (`_spawn_and_read` is factored out for the re-spawn). The fallback is logged (`WARNING`), never silent — so a user without 4.8 or 1M access still gets a working turn instead of a hard failure.

The detection is subtle: the CLI emits **`API Error: Usage credits required for 1M context`** in `result_text` (stdout) with a non-zero exit and an *empty* `error_text`/`stderr`. So `_failure_blob()` folds `result_text` into the failure signal **only** when it carries an explicit API-error marker (`api error`, `usage credits required`, `switch to standard context`, `model_not_found`…) — never a normal answer that merely contains a needle like "1m" or "200k" (crypto candle talk would false-positive otherwise). `_looks_like_model_unavailable()` then matches the needle set; `_failure_is_context_related()` distinguishes a 1M-window failure from a pinned-id-not-found failure.

**1M requires usage credits + kill switch.** 1M context is **not free even on subscription auth** — it needs pay-as-you-go usage credits at claude.ai/settings/usage. Without them, every `[1m]` turn fails. To avoid paying that failed-attempt tax on every turn, the first context-related rejection trips a process-wide kill switch (`_MAX_CONTEXT_RUNTIME_OFF` via `_disable_max_context_runtime()`); `resolve_max_context_model()` then stops appending `[1m]` until the process restarts. Net effect with `MAX_CONTEXT=true` but no credits: one wasted attempt per restart, then standard 200K context with zero ongoing tax. **Without the `result_text` detection the OUTER `MODEL_FALLBACK_CHAIN` would catch the credit error as a generic failure and switch the turn to GLM** — which is why this path matters.

**Auto-tracking signature.** `ClaudeRunner.captured_model` is read from the init event (the real id the CLI resolved, e.g. `claude-opus-5[1m]`). `_build_signature` prefers it for Anthropic so model upgrades surface with no code edit; `MODEL_FULL_IDS` is only a display fallback (and for z.AI, whose captured id is the meaningless proxy alias).

## The three providers

- **Anthropic models** (`sonnet`, `opus`, `haiku`) — native, default. Require logged-in Claude account.
- **z.AI GLM models** (`glm-5.1`, `glm-4.7`, `glm-4.5-air`) — routed via z.AI's **Anthropic-compatible gateway** through a local proxy. Claude CLI validates model names client-side, so `glm-*` names would be rejected before any HTTP call. Fix: `ClaudeRunner` starts a per-run local HTTP proxy that accepts any model name, rewrites the `model` field in the JSON body to the real GLM name, and forwards to z.AI. Claude CLI sees `--model claude-sonnet-4-6` (a valid alias); the proxy handles the actual routing. The gateway emits Anthropic-compatible events the bot's parser already consumes.
- **OpenAI ChatGPT models** (`gpt-5` via ChatGPT OAuth; `gpt-5-codex` requires an OpenAI API key, not ChatGPT Plus/Pro) — subprocess spawn of the official `codex` CLI (`@openai/codex`). OpenAI's wire format isn't Anthropic-compatible, so `ANTHROPIC_BASE_URL` trickery doesn't work. Instead a parallel `CodexRunner` class spawns `codex exec --json` and parses its JSONL event stream (`thread.started`, `item.started`, `item.completed`, `turn.completed`, `turn.failed`, `error`) into the same internal state `ClaudeRunner` produces. Auth for `gpt-5` is via `codex login` (OAuth with ChatGPT Plus/Pro subscription → `~/.codex/auth.json`). `gpt-5-codex` returns `400 The 'gpt-5-codex' model is not supported when using Codex with a ChatGPT account` under OAuth — the `/gpt` quick-switch and the `/model` inline keyboard therefore only expose `gpt-5` by default; `gpt-5-codex` is selectable only via `/model <name>` or vault frontmatter and assumes a separate OpenAI API key path (not yet implemented in this codebase).

**Provider is inferred from the model name prefix** — no `provider:` field in frontmatter. A pipeline step with `model: glm-4.5-air` runs on GLM; `model: gpt-5` runs on Codex; `model: sonnet` runs on Claude. Switching mid-pipeline is supported (each step spawns its own subprocess via `_make_runner_for(step.model)`).

## z.AI gateway — tested capabilities (2026-04-12)

| Feature | Status | Notes |
|---|---|---|
| Text generation | **Works** | Core feature, all GLM models |
| Prompt caching | **Works** | `cache_read_input_tokens > 0` confirmed |
| Skills, hooks, MCP, file ops, Bash | **Works** | Client-side Claude Code features, unchanged |
| WebSearch / WebFetch (native) | **Doesn't work** | z.AI returns 400 "Invalid API parameter" for tool_use blocks. Workaround: pre-fetch in a Claude step, use PintchTab, or configure a Tavily/Brave MCP server |
| Image input (vision) | **Not tested** | GLM models support vision natively; may work if z.AI forwards multimodal content blocks |
| Context window | **Varies** | GLM-4.7 = 131K, GLM-5.1 = 200K |
| Sub-agents (Task tool) | **Inherit parent model** | Spawn explicitly with `--model sonnet` in the sub-agent prompt when mixing is required |

**Design convention for mixed pipelines:** use Claude for steps that need native web fetching or image input. Use GLM for analysis, transformation, or text generation — especially over data already collected by a Claude step (usually cheaper and fast enough).

**Fail-loud behavior:** If a GLM model is requested but `ZAI_API_KEY` is not set, `ClaudeRunner` aborts before spawning the subprocess and surfaces a friendly error via Telegram — no silent failure. The `/model` inline keyboard hides the GLM row entirely when the key is missing.

## Codex CLI provider — account default model (v3.90)

The bot key **`gpt`** means "whatever model the ChatGPT account uses by default": `CodexRunner` passes no `--model` for `gpt` (nor the legacy `gpt-5`/`gpt-5-codex` keys), so no slug goes stale. Probed 2026-11-16 on codex-cli 0.169.0: `--model gpt-5` and `--model gpt-5.5` are both refused under ChatGPT OAuth ("not supported when using Codex with a ChatGPT account"); the account default (`model = "gpt-6.1-sol"` in `~/.codex/config.toml`) works. The display name is read from that config (`codex_default_model()`). `gpt` is the last entry of the default `MODEL_FALLBACK_CHAIN`; `get_fallback_model` skips it when `codex` isn't installed. Any other `gpt-*` is passed as an explicit `--model`.

## Codex CLI provider — known limitations (v3.44)

| Area | Status | Note |
|---|---|---|
| Text generation | **Works** | Core feature; `codex exec --json` streams agent messages |
| Session resume | **Works** | Uses `codex exec resume <thread_id>` subcommand (not a flag) |
| Reasoning / thinking stream | **Works** | `item.type == "reasoning"` events feed `accumulated_thinking` |
| System prompt injection | **Workaround** | Codex has no `--append-system-prompt`; `SYSTEM_PROMPT` is prepended to the user prompt body. Prefix-cache penalty per turn |
| Live `/btw` injection | **Doesn't work** | `send_btw()` returns False; BTWs queue for the next turn |
| Cost tracking | **Deferred** | `/cost` shows `openai` as `$0.00` until v3.45 (token→price mapping). Tokens come in `turn.completed.usage` but pricing lookup isn't implemented yet |
| Fallback chain cross-provider skip | **Works** | `get_fallback_model` treats `openai` like any other provider for AUTH/CREDIT/RATE_LIMIT skip |

**Fail-loud:** if `gpt-*` is requested but `codex` binary is missing, `CodexRunner` aborts before spawn with an install hint. If binary is present but `~/.codex/auth.json` is missing, aborts with `codex login` hint. `/model` keyboard hides the GPT row when binary missing; `cmd_model_switch` refuses with a friendly message.

**JSONL schema verification:** the event shapes in `CodexRunner._handle_event` are based on documented Codex event types but field names (e.g. `item.text` vs `item.content`) should be verified against real captured output at first smoke test — search for `# VERIFY` comments in the class.
