---
title: Pipeline Router
description: Translate a user's natural-language request to trigger a pipeline into the structured form the executor expects (pipeline name + per-step overrides JSON). Use when the user asks any agent to "run pipeline X" with optional adjustments like "with focus on ETH" or "but use depth=deep". Outputs the exact `/run --overrides` invocation or the equivalent shell command.
type: skill
created: 2026-05-02
updated: 2026-05-02
tags: [skill, pipeline, infrastructure, routing, nl-parsing]
---

## When to use this skill

Triggers (any of these in user message):
- "Roda a pipeline X com Y"
- "Dispara X focando em ETH"
- "Run pipeline X but use depth=deep"
- "Roda análise técnica com foco em ETH"
- Any phrasing that names a pipeline + optional adjustments

When the user's request is just "run pipeline X" with no adjustments, no skill needed — call `/run X` directly.

## What this skill does

Converts natural-language pipeline triggers into:

```
/run <pipeline-name> --overrides '<JSON object>'
```

…where the JSON object is `{step_id: {attribute_name: value}}`.

The agent is the natural-language → structured-data translator. The
executor handles the deterministic side (validation, env-var injection,
prompt suffixes). Pipeline v2 spec § 4 + § 9.

## Required reading before generating overrides

1. **The pipeline file** — `vault/<owning-agent>/Routines/<pipeline-name>.md`.
   Read its `pipeline` codeblock to see which steps exist and which
   declare `accepts_overrides`.

2. **Each step's `accepts_overrides` schema** — the schema declares:
   - `type` (string | integer | number | boolean | array | object)
   - `enum` (optional list of allowed values)
   - `default` (optional fallback)
   - `description` (human-readable purpose)

   ONLY attributes declared in `accepts_overrides` can receive overrides.
   Anything else WILL be rejected by `validate_overrides()` with a friendly
   error.

## Translation procedure

### Step 1 — identify the pipeline name
Match the user's mention against pipeline files. Be tolerant of casual
naming ("análise técnica" → `crypto-ta-analise`, "TA" → `crypto-ta-analise`,
"news produce" → `crypto-news-produce`). When ambiguous, ask the user.

### Step 2 — identify the adjustments
Parse natural language modifiers like:
- "com foco em ETH" → `focus_asset = "ETH"` (string)
- "depth profundo" → `depth = "deep"` (string)
- "max 5 retries" → `max_retries = 5` (integer)
- "modo silencioso" → `silent = true` (boolean)
- "para os ativos BTC e ETH" → `assets = ["BTC", "ETH"]` (array)

### Step 3 — match adjustments to steps
For each adjustment, find which step(s) in the pipeline declare that
attribute name. The override goes UNDER that step's id.

CRITICAL — Q2 isolation: if `analyst` and `writer` BOTH declare
`focus_asset`, the user's "com foco em ETH" usually means ALL steps
focused on ETH — write the override under BOTH step ids. Don't assume
cross-step inheritance: each step is isolated, declared defaults stay
local to their step.

### Step 4 — emit the structured form
Use one of:

**Option A — Telegram slash command (preferred for interactive use):**
```
/run <pipeline-name> --overrides '{"step_id": {"attr": "value"}}'
```

**Option B — Shell call (for non-Telegram contexts, e.g. cron, agent
shell tool, web hook):**
```
python3 scripts/run_pipeline.py <pipeline-name> --overrides '{"step_id": {"attr": "value"}}'
```

When the agent is responding to a Telegram message, prefer Option A
(the user sees what was triggered).

## Example translations

### Example 1 — TA pipeline with asset focus

**User:** "Crypto Bro, roda a análise técnica focando em ETH hoje"

**Skill output:**

```
/run crypto-ta-analise --overrides '{"analyst": {"focus_asset": "ETH"}, "writer": {"focus_asset": "ETH"}}'
```

Reasoning: `analyst` and `writer` both declare `focus_asset` in their
`accepts_overrides`. The user's "focando em ETH" applies to both because
the analysis AND the writeup should align on the same asset.

### Example 2 — News pipeline with depth adjustment

**User:** "Roda crypto-news mas faz uma análise mais profunda do que normalmente"

**Skill output:**

```
/run crypto-news --overrides '{"analyst": {"depth": "deep"}}'
```

Reasoning: only `analyst` declares `depth`. The writer step doesn't —
it just writes whatever the analyst produced.

### Example 3 — Multiple adjustments

**User:** "TA com foco em SOL e modo silencioso (sem notificação no Telegram)"

**Skill output:**

```
/run crypto-ta-analise --overrides '{"analyst": {"focus_asset": "SOL"}, "writer": {"focus_asset": "SOL"}, "publisher": {"silent": true}}'
```

Reasoning: focus applies to analyst+writer; silent applies to publisher
(the only step with a `silent` override declared).

### Example 4 — Adjustment NOT in any schema

**User:** "Roda crypto-news mas usa o modelo opus"

**Skill response:** Don't generate overrides — the user wants to change
the LLM model, which is NOT in any step's `accepts_overrides` schema
(model is a step-level config, not a runtime override). Reply:

> O modelo é configurado no arquivo da pipeline (campo `model:` em cada
> step), não é um override de runtime. Quer que eu edite a pipeline pra
> usar opus permanentemente, ou só rodar essa vez? Se for só essa vez,
> precisa abrir o arquivo e mudar manual antes do `/run`.

### Example 5 — Ambiguous pipeline name

**User:** "Dispara o pipeline de crypto"

**Skill response:** Ask which one:

> Qual pipeline de crypto?
> - `crypto-ta-analise` — Análise técnica diária
> - `crypto-news` — Coleta de notícias
> - `crypto-news-produce` — Produção de post a partir de uma notícia
> - `crypto-news-scout` — Scout de manchetes

## Validation safety net

If the user's adjustment matches an `enum` constraint:

```yaml
focus_asset:
  type: string
  enum: [BTC, ETH, SOL, BNB, XRP, ADA, DOGE, AVAX, LINK]
```

…and the user says "foco em DOGEBONK" (not in enum), the skill should
catch it BEFORE emitting the slash command:

> O override `focus_asset` aceita só os ativos: BTC, ETH, SOL, BNB,
> XRP, ADA, DOGE, AVAX, LINK. DOGEBONK não está na lista. Quer
> escolher um deles ou pular o foco?

## Common mistakes to avoid

1. **Don't override attributes the schema doesn't declare.** They'll
   be rejected and the user gets an error instead of their pipeline.

2. **Don't assume cross-step inheritance.** If `analyst` and `writer`
   both have `focus_asset`, you must put it under BOTH ids if it
   applies to both.

3. **Don't put the override at pipeline level.** Overrides are ALWAYS
   per-step: `{"step_id": {"attr": "val"}}`. Never `{"attr": "val"}`.

4. **Don't generate overrides for v1 pipelines.** Check the pipeline's
   frontmatter for `pipeline_version: 2`. If absent, the pipeline
   doesn't support overrides — degrade gracefully:
   > "Esta pipeline ainda não foi migrada pro v2 — overrides não são
   > suportados ainda. Quer que eu rode sem ajustes ou ajude a migrar?"

5. **Don't quote bare strings as JSON values when they contain quotes
   or special chars.** Use `json.dumps()` mentally — strings need
   double quotes, escape internal quotes.

## Checklist before emitting the slash command

- [ ] Pipeline name resolves to a real file under `<agent>/Routines/`
- [ ] Pipeline declares `pipeline_version: 2` in frontmatter
- [ ] Every override step_id exists in the pipeline's steps list
- [ ] Every override attr name is in that step's `accepts_overrides`
- [ ] Override values match the declared types (and enums if any)
- [ ] JSON is valid (use mental json.dumps — proper quoting)
- [ ] Same adjustment applied to all relevant steps (Q2 isolation)
