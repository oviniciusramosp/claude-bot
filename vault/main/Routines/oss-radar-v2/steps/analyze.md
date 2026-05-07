You are analyzing recent open-source activity from two projects to find ideas and patterns relevant to **claude-bot** — a Telegram bot that wraps Claude Code CLI with session management, routines/pipelines, a vault-based knowledge graph, agents, voice, active memory, and a macOS companion app.

Read the collected data from the previous step. The collector script writes a structured markdown file to the pipeline's data directory; the path is exposed via the `PIPELINE_DATA_DIR` env var, with the file named `collect-github.md`. Use the Read tool on `$PIPELINE_DATA_DIR/collect-github.md` (or, if that env var is not surfaced to you, look in the workspace `data/oss-radar-v2/collect-github.md`).

The file has these sections:

- `## collection_status` — `sources_ok` and `sources_failed` lists. Note any failed sources so you can caveat your analysis when data is partial.
- `## openclaw_repos_overview` — JSON list of OpenClaw repos with `pushed_at` and `stars`.
- `## <sanitized_full_name>_activity` — one section per active OpenClaw repo (and Hermes Agent), each containing JSON arrays of recent commits, releases, and (for Hermes) open PRs.

## Your product context

claude-bot key capabilities for comparison:
- Multi-agent architecture with isolated vaults per agent
- Routine/pipeline scheduler (cron-like, with multi-step DAG pipelines)
- Active Memory (FTS5 index + graph-based context injection)
- Session management with auto-compact and auto-rotate
- Advisor pattern (executor escalates to Opus for strategic decisions)
- Voice input/output (whisper + TTS)
- macOS menu bar companion app (SwiftUI)
- Telegram inline keyboards for interactive commands
- Vault as Obsidian-compatible knowledge graph
- Skills system (reusable prompt templates)
- Lessons system (compound engineering from past failures)

## Analysis instructions

For each repo with activity, analyze:

1. **What changed** — summarize the key commits/releases/PRs in 2-3 sentences
2. **Relevance to claude-bot** — is there anything we could adopt, adapt, or learn from?
3. **Actionable suggestions** — concrete ideas for our product, if any

Focus on:
- Architecture patterns (agent systems, memory, tool use)
- UX ideas (commands, interactions, notifications)
- Infrastructure (deployment, monitoring, testing)
- Novel features we don't have yet

Be honest. If nothing is relevant, say so. Don't force connections.

## Check the watchlist

Read `../../Notes/oss-watchlist.md` if it exists. For each item under `Active watches`, scan the collected data (commits, releases, PRs) for state changes — merged, closed, re-opened, new commits on the PR, or a major update. If any watched item changed, surface it prominently in the report under a `⚠️ *Watchlist update*` header **above** the normal repo summaries. Include the item name, what changed, and a one-line actionable nudge (e.g., "re-read diff and assess our auto-compact").

If nothing changed on the watchlist, do not mention the watchlist at all — silence is the default.

## Output format

If there ARE relevant insights, format the report as:

```
🔭 *OSS Radar — {date}*

*OpenClaw*
{2-3 sentence summary of activity}

{if relevant:}
💡 *Sugestoes:*
- {concrete actionable suggestion}
- {another suggestion}

*Hermes Agent*
{2-3 sentence summary of activity}

{if relevant:}
💡 *Sugestoes:*
- {concrete actionable suggestion}

---
_{overall assessment: "Nada urgente" | "Vale investigar" | "Prioridade alta"}_
```

If NOTHING is relevant to our product (just routine maintenance, docs, etc.), respond with exactly `NO_REPLY`.

Only report genuine insights. Quality over quantity — one good suggestion beats five weak ones.
