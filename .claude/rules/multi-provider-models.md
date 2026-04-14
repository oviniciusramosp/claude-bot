---
paths:
  - "claude-fallback-bot.py"
  - "scripts/advisor.sh"
---

# Multi-provider models (Claude + z.AI GLM)

The bot runs two LLM providers side-by-side, reusing the same `claude` CLI binary:

- **Anthropic models** (`sonnet`, `opus`, `haiku`) — native, default. Require logged-in Claude account.
- **z.AI GLM models** (`glm-5.1`, `glm-4.7`, `glm-4.5-air`) — routed via z.AI's **Anthropic-compatible gateway** through a local proxy. Claude CLI validates model names client-side, so `glm-*` names would be rejected before any HTTP call. Fix: `ClaudeRunner` starts a per-run local HTTP proxy that accepts any model name, rewrites the `model` field in the JSON body to the real GLM name, and forwards to z.AI. Claude CLI sees `--model claude-sonnet-4-6` (a valid alias); the proxy handles the actual routing. The gateway emits Anthropic-compatible events the bot's parser already consumes.

**Provider is inferred from the model name prefix** — no `provider:` field in frontmatter. A pipeline step with `model: glm-4.5-air` runs on GLM; a step with `model: sonnet` runs on Claude. Switching mid-pipeline is supported (each step spawns its own subprocess).

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
