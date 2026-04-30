---
title: OpenClaw Session Warmth Investigation
description: Research notes on OpenClaw PR #69679 (keep Claude CLI sessions warm) — persistent stdio process per session, 10-min idle cleanup, resume via session id. Assess applicability to claude-bot.
type: note
created: 2026-04-23
updated: 2026-04-23
tags: [oss, radar, openclaw, performance, architecture, claude-cli, research]
---

[[main/Notes/agent-notes|Notes]]
## The PR

- **Repo:** openclaw/openclaw
- **PR #69679** — "Keep Claude CLI sessions warm"
- **Commit:** 81ca7bc40b09 (merged, v2026.4.21)
- **Scale:** 18 files changed, +2172 / -27 lines
- **Key new file:** `src/agents/cli-runner/claude-live-session.ts` (913 lines)

## What OpenClaw actually did

From the PR summary:

> - Keep one Claude stdio process warm per OpenClaw session.
> - Close idle Claude processes after 10 minutes, then resume with the stored Claude session id.
> - Add config/schema/docs plus regression coverage for reuse and idle cleanup.

### Architecture change

OpenClaw moved from **one-shot `claude --print`** spawns per turn to a **persistent stdio process** that stays alive across turns within the same OpenClaw session. The live session handles:

1. Spawn Claude CLI once in interactive/stdio mode (no `--print`)
2. Pipe each new user prompt into stdin
3. Read streaming responses from stdout as they come
4. Keep the process alive until 10 min of idleness, then SIGTERM
5. On resume after cleanup: reuse the stored `claude session id` via `--resume` so conversation context is preserved

Supporting changes span config schema, agent defaults, MCP bundle serialization, fingerprinting to detect when a warm process is still compatible with the next turn's args, and extensive regression tests (996-line spawn test file).

### Gains claimed

- Skip cold start of Claude CLI every turn (Node startup + config load + MCP negotiation)
- Reuse in-process state (already-negotiated MCP servers, warmed caches)
- Still safe for long idle gaps — closes and resumes transparently

## Comparison to claude-bot

### Current state

Our `ClaudeRunner` (claude-fallback-bot.py:3970+) spawns a **fresh `subprocess.Popen`** per message:
- Command: `claude --print --dangerously-skip-permissions --output-format stream-json ...`
- One-shot: stdin closes right after the prompt is sent, Claude processes and exits
- Session continuity is preserved by passing `session_id` via `--resume <id>` on the next call — Claude CLI loads the persisted session file from disk

So **every message pays**:
- OS process spawn
- Node.js startup (~150ms)
- Claude CLI config load
- MCP server handshake (if MCP configured)
- Session file read (disk I/O)

### What's already warm in our code

- `ThreadContext` reuses the same `ClaudeRunner` **object** (claude-fallback-bot.py:4479) — but the subprocess itself dies after each turn, so this only reuses Python-side state (message buffers, Telegram throttles).
- `session_id` is warm — Claude's internal conversation history survives via its session file.

### What's cold

- The Claude CLI **process**: fresh spawn every turn.
- MCP servers: re-negotiated every turn.
- Node.js runtime: fresh every turn.

## Decision: PASS (for now)

**Not worth implementing yet.** Three reasons:

1. **Scope mismatch.** The OpenClaw PR is 2172 lines across 18 files with a 913-line `claude-live-session.ts` module. Porting that faithfully would be a major rewrite of `ClaudeRunner`. We shouldn't guess at a subset — the PR includes fingerprinting, serialized session creates, dead-session detection, and resume bounds that all exist for reasons we'd need to rediscover.

2. **Our use case is different.** OpenClaw runs as a service handling concurrent user sessions; keeping a process per user warm makes sense there. claude-bot is single-user Telegram — the cost of spawn latency is paid at most once every ~10-30s of human thinking time. The absolute latency saved per message (~200-500ms) is imperceptible in our UX; Telegram already shows a typing indicator during spawn.

3. **We don't have MCP fat.** OpenClaw's bundle-mcp module suggests their warm boot included MCP handshake cost. Our Claude CLI runs with stock MCP config; the warm gain per turn for us is just Node startup — small.

### When to revisit

Re-open this investigation if:
- We add heavy MCP servers (e.g. Jira, Notion, custom SDK) where each handshake costs >1s
- We notice user-visible latency complaints on first-turn-after-idle
- We move toward multi-user simultaneous sessions
- OpenClaw publishes perf numbers quantifying the gain

### What we DID adopt from OSS Radar

See [claude-fallback-bot.py](../../../claude-fallback-bot.py) v3.42.0 — stale detection for `/delegate` (inspired by Hermes #13770, not OpenClaw). The Hermes pattern was smaller in scope and applicable to a concrete gap in our code.
