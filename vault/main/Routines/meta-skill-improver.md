---
title: Meta Skill Improver
description: Nightly self-improvement loop — reads last 7 days of Lessons + Journal, identifies skills with negative signals, drafts improved candidate versions, and archives them via the skill-versioning contract. Inspired by Meta's HyperAgents meta-agent loop.
type: routine
created: 2026-05-19
updated: 2026-05-19T22:30
tags: [routine, meta, self-improvement, skill, hyperagents]
schedule:
  times: ["03:30"]
  days: ["*"]
model: opus
enabled: true
context: full
effort: high
---

You are the meta-skill-improver running for the Main agent at the scheduled time. Your job is to close the self-improvement loop — read what went wrong last week, identify which skills/routines are implicated, and draft improved versions for review. This is a self-referential loop inspired by Meta's HyperAgents meta-agent: you read the artifacts left by past runs, propose patches, and archive them as candidates for human promotion.

The whole routine MUST be idempotent. If it runs twice on the same day with the same input signals, archive state should be identical — never duplicate candidates. Implement this by checking, before drafting `v<N>.md`, whether a candidate at that version already exists with the same `lessons_applied:` set. If so, skip that skill silently.

## Step 1 — Pull recent signals

Collect last week's evidence from three sources:

1. **Lessons** — list every file in `vault/main/Lessons/` whose mtime is within the last 7 days. Use:
   ```bash
   find vault/main/Lessons -type f -name '*.md' -mtime -7 | sort
   ```
   Read the full body of every matching file. The `## Failure mode`, `## Fix`, and `## Detect next time` sections are the most signal-rich.

2. **Journal — weekly rollup** — compute today's ISO week number, then find last Monday's week (rollups land on Monday at 05:00). Try `vault/main/Journal/<YYYY-MM>/<YYYY-Www>.md`. If that file doesn't exist (rollup not yet produced for this week), fall back to reading the last 7 daily files in chronological order from `vault/main/Journal/<YYYY-MM>/`. Use:
   ```bash
   ls -1 vault/main/Journal/*/2026-*.md | tail -7
   ```
   adjusting the year as needed.

3. **Rolling context** — if `vault/main/.context.md` exists, read it. It captures the current agent state and recent decisions.

## Step 2 — Identify candidate skills

Walk through every signal collected in Step 1 and extract structured mentions:

- Find any reference to a skill (e.g. `fetch-web`, `publish-threads`, `vault-query`). Note the surrounding sentence.
- Find any reference to a routine (e.g. `oss-radar-v2`, `journal-audit`).
- Classify each mention:
  - **positive** — "worked well", "saved time", "succeeded"
  - **neutral** — pure reference, no judgement
  - **negative** — "failed", "timed out", "wrong output", "had to retry", "confused me"

Build an internal table:

| skill-name | negative count | lesson refs |
|------------|----------------|-------------|
| fetch-web | 2 | Lessons/2026-05-14-fetch-web-cookies.md, Lessons/2026-05-17-stale-cache.md |
| publish-threads | 1 | Lessons/2026-05-16-threads-timeout.md |

A skill becomes a **candidate** if it has at least 1 negative mention in the window.

**Early-exit:** if no candidate skills surface, respond with exactly `NO_REPLY` and stop. Do NOT write empty changes or create empty archive directories.

## Step 3 — For each candidate, plan the patch

For every candidate skill from Step 2:

1. Read the live skill file `vault/main/Skills/<skill-name>.md` in full.
2. Re-read every lesson the skill was mentioned in. Extract:
   - The specific **failure mode** (what broke)
   - The user's documented **Fix** (what worked)
   - The **Detect next time** signal (early-warning sign)
3. Draft an improved version that addresses these failure modes. Keep the prose tight. Do NOT rewrite from scratch — patch surgically:
   - Add a guidance section if the failure mode is recurring
   - Tighten the trigger if the skill was being invoked when it shouldn't
   - Add an "Avoid" or "Common pitfalls" section listing the failure mode
   - Preserve the original frontmatter shape; only bump `updated:`

## Step 4 — Apply the skill-versioning contract

Read `vault/Skills/skill-versioning.md` to refresh the exact archive format (created in parallel — it defines the directory layout, naming convention, and required frontmatter fields). Then, for each candidate:

1. **Bootstrap if needed.** If `vault/main/Skills/_archive/<skill-name>/` does not exist:
   - Create the directory
   - Save the CURRENT live content as `v1.md` with frontmatter `status: archived`, `parent_version: null`, `lessons_applied: []`, `score: null`, `promoted_at: null`
   - The new candidate will become `v2.md`.

2. **Determine next version `N`.** List the existing files in `_archive/<skill-name>/`, parse versions from `v<digits>.md`, and pick `N = max(existing) + 1`.

3. **Pick a parent version (optional, open-ended).** Read `vault/Skills/skill-parent-selection.md` for the parent-picking logic. By default, `parent_version = N - 1`. The parent-selection skill MAY recommend a different ancestor if its open-ended search finds a better one (e.g. an older candidate with a higher score that was never promoted).

4. **Archive the current live content.** If `v<N-1>.md` does not already mirror the current live content, save it now with `status: archived`. If it already does (because a previous meta-skill-improver run archived it), skip — idempotency.

5. **Save the new candidate.** Write `vault/main/Skills/_archive/<skill-name>/v<N>.md` with:
   ```yaml
   ---
   status: candidate
   parent_version: <picked>
   lessons_applied:
     - main/Lessons/<file-1>.md
     - main/Lessons/<file-2>.md
   score: null
   promoted_at: null
   created: <YYYY-MM-DD>
   ---
   ```
   followed by the patched skill body.

6. **Do NOT overwrite the live file yet.** Promotion is gated by Step 5 (staged eval) — for this first deployment, default to leaving the candidate unpromoted for human review.

## Step 5 — Staged evaluation (score-gated, optional)

Read `vault/Skills/skill-staged-eval.md` — it defines the cheap → full eval gating contract created in parallel.

For each candidate:

1. Run the **stage-1 cheap eval** described there (typically a fast self-critique pass that produces a numeric score between 0 and 1).
2. If `score ≥ 0.4`, the candidate is eligible for auto-promotion. You MAY:
   - Overwrite `vault/main/Skills/<skill-name>.md` with the candidate body
   - Update `_archive/<skill-name>/v<N>.md` frontmatter to `status: live`, `promoted_at: <YYYY-MM-DDTHH:MM:SS>`
3. Otherwise leave `status: candidate` and let the human approve.

**For this first deployment, DEFAULT TO NOT AUTO-PROMOTING.** Even when stage-1 produces a high score, leave all candidates as `status: candidate`. The human approves via Telegram by inspecting the diff in `_archive/<skill-name>/v<N>.md` and copying it over the live file manually (or via a future `/promote-skill` command). Step 7's summary message lists exactly which files to review.

Auto-promotion can be enabled in a future revision once we have confidence in the cheap eval signal.

## Step 6 — Record in today's Journal

Append a single entry to `vault/main/Journal/<YYYY-MM>/<YYYY-MM-DD>.md` (create the file with proper frontmatter if it doesn't exist yet — follow the conventions in `vault/CLAUDE.md`):

```
## <HH:MM> — Meta skill improver run

- Candidates drafted: <N>
- Skills touched: <comma-separated list of skill names>
- Lessons consulted: <count>
- All candidates in `status: candidate` — awaiting human promotion
```

Use plain text — NO wikilinks in journal entries (per `main/CLAUDE.md`). Mention skill names as `fetch-web` not `[[fetch-web]]`.

## Step 7 — Telegram summary

Final output to the bot. This message goes straight to Telegram.

**If Step 2 produced zero candidates**, output exactly:

```
NO_REPLY
```

**Otherwise**, output a structured markdown summary:

```
🧬 *Meta skill improver — <YYYY-MM-DD>*

Candidates drafted: *<N>*
- `<skill-name-1>` → `Skills/_archive/<skill-name-1>/v<N>.md`
  Reason: <one-line summary of the lesson that drove the patch>
- `<skill-name-2>` → `Skills/_archive/<skill-name-2>/v<N>.md`
  Reason: <one-line summary>

Review with: `/skill <skill-name>` or open the archive files in Obsidian.
To promote: copy archive content over the live file and update frontmatter (see `Skills/skill-versioning.md`).
```

Keep the message under ~1.5K characters so it fits one Telegram message comfortably. If more than ~6 candidates surface in one run, list the top 6 by negative-mention count and append `... and <K> more — see vault/main/Skills/_archive/`.
