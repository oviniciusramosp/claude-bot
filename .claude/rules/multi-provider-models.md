---
paths:
  - "claude-fallback-bot.py"
  - "scripts/advisor.sh"
---

# Multi-provider models (Claude + z.AI GLM + ChatGPT)

The bot runs three LLM providers side-by-side. The first two share the `claude` CLI binary; the third uses OpenAI's `codex` CLI via `CodexRunner`:

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
