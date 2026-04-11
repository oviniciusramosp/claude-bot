---
title: Extract Knowledge
description: Extracts durable concepts from pipeline outputs or conversations and creates/updates notes in Notes/. Automates knowledge base population.
type: skill
trigger: "at the end of a pipeline or when the user asks to record learned knowledge"
created: 2026-04-09
updated: 2026-04-09
tags: [skill, knowledge, extraction, notes]
---

## Objective

Transform raw outputs (from pipelines, conversations, or analyses) into durable notes in the `Notes/` folder. Each note captures an atomic concept with complete frontmatter, correct links, and a `related` field for semantic relationships.

## When to use

- At the end of pipelines that generate analyses (e.g., `crypto-ta-analise`)
- When the user mentions something that should become durable knowledge
- When a pattern or insight recurs across multiple conversations
- Manually via `/extract` or "extract knowledge from X"

## Steps

1. **Identify extractable concepts** — Read the source material (pipeline output in `/tmp/claude-pipeline-*/data/`, user message, or indicated file). Identify concepts that are:
   - Durable (not ephemeral — valid beyond today)
   - Atomic (one concept per note)
   - Non-redundant (check if a similar note already exists in `Notes/`)

2. **Check for duplicates** — Glob `Notes/*.md`, read frontmatters. If a note about the same concept already exists, UPDATE it instead of creating a new one. Add a `## Update YYYY-MM-DD` section at the end.

3. **Create note** — For each new concept:

   ```yaml
   ---
   title: Concept Name
   description: Sentence explaining the concept and when it is relevant to consult it.
   type: note
   created: YYYY-MM-DD
   updated: YYYY-MM-DD
   tags: [domain, subtopic]
   source: "pipeline:crypto-ta-analise" | "conversation" | "manual"
   confidence: extracted | inferred
   related:
     - file: "related-file"
       type: extracted | inferred
       reason: "reason for the relationship"
   ---

   [[Notes]]

   ## Content

   [Concise explanation of the concept — maximum 3 paragraphs]

   ## Context

   - Source: [where this knowledge came from]
   - Date of observation: YYYY-MM-DD
   - Conditions: [in what context this is true]
   ```

4. **Update index** — Add `- [[note-name]] — description` to `Notes/Notes.md`

5. **Record in Journal** — Entry: `Note created/updated: note-name (source: X)`

## Quality criteria

- `description` must be sufficient to decide whether the note is worth reading without opening it
- Tags must allow efficient filtering (domain + subtopic)
- `related` field connects semantically without polluting the Graph View
- `confidence: extracted` = fact directly from the source; `inferred` = derived conclusion
- Notes MUST NOT contain ephemeral data (today's prices, one-off values)

## Extraction examples

**From crypto-ta-analise pipeline:**
- ✅ "BTC historically respects the 200w EMA as support in bear markets" → durable note
- ✅ "Prolonged negative funding rate precedes bullish reversals in 70% of cases" → durable note
- ❌ "BTC is at $84,500 today" → ephemeral, do not extract
- ❌ "Fear & Greed is at 45" → ephemeral, do not extract

**From conversation:**
- ✅ "The user prefers analyses with embedded charts" → note about preferences
- ✅ "The Binance API has a rate limit of 1200 req/min" → technical reference note
- ❌ "The user asked about the ETH price" → not durable

## Notes

- Prioritize quality over quantity — 1 good note > 5 weak notes
- If there is no durable concept to extract, don't force it. Return "No durable concept identified."
- The `source` field allows tracing the provenance of the knowledge
- When updating an existing note, increment `updated` and add an update section at the end
