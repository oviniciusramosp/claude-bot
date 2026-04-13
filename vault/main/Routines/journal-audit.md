---
title: Journal Audit
description: Nightly audit that checks all agents' journals for completeness, fixes frontmatter issues, and fills gaps from the activity log.
type: routine
created: 2026-04-10
updated: 2026-04-13
tags: [routine, journal, maintenance, daily]
schedule:
  days: ["*"]
  times: [23:59]
model: sonnet
enabled: true
context: minimal
---

You are running the nightly Journal audit. Your task is to ensure that all agents' journals are complete, well-formatted, and cover every important session of the day.

## Step 1: Structural fixes (deterministic)

Run the audit script with `--fix` to create missing journal files and repair broken frontmatter. This is done by Python — no guessing needed:

```bash
python3 scripts/journal-audit.py --fix
```

This guarantees every agent has a valid journal file with correct frontmatter before you write any content.

## Step 2: Read the gap report

The script also outputs a report showing uncovered sessions. Each uncovered session includes:
- **Full user messages** (what was asked — not truncated)
- **Claude response summaries** (what was done — up to 500 chars each)
- Timestamps and session names

Read this report carefully. The conversation data is your source of truth.

## Step 3: Write journal entries for uncovered sessions

For each uncovered session in the report, write a journal entry to the correct file:

- Use the FULL conversation data (user messages + Claude responses) to write meaningful entries
- Format: `## HH:MM — Topic summary` followed by bullet points and `---`
- Be concise — 3-5 bullets per entry
- DO NOT invent details — only record what the data shows
- If a session had multiple topics, group them under one entry with sub-bullets
- Append to the journal file — never overwrite existing content

For pipeline completions (shown under "Pipeline activity"), add a brief entry only if significant and not already covered.

Skip routine housekeeping (vault-graph-update, update-check, etc.).

## Step 4: Update description

After writing entries, update each journal file's `description` field in the frontmatter to summarize the day's actual content. Example: `description: Bot activity logging feature, crypto pipeline published, palmeiras-feed migration.`

Also update the `updated` field to today's date.

## Step 5: Self-check

Run the audit script again (without --fix) to verify your changes:

```bash
python3 scripts/journal-audit.py
```

The report should show "All sessions covered ✓" for every agent. If not, fix remaining gaps.

## Step 6: Respond NO_REPLY when done.
