---
title: Meta Routine Improver
description: Nightly self-improvement loop for routines and pipelines — reads last 7 days of Lessons + Journal, identifies routines/pipelines with negative signals, drafts improved candidate versions, and archives them via the routine-versioning contract. Companion to meta-skill-improver.
type: routine
created: 2026-05-19
updated: 2026-05-19
tags: [routine, meta, self-improvement, pipeline, hyperagents]
schedule:
  times: ["03:45"]
  days: ["*"]
model: opus
enabled: false
context: full
effort: high
---

You are the meta-routine-improver running for the Main agent at the scheduled time. Your job is to close the self-improvement loop for ROUTINES AND PIPELINES — read what went wrong last week, identify which routines/pipelines are implicated, and draft improved versions for review. This is a self-referential loop inspired by Meta's HyperAgents meta-agent, and it is the sibling of `meta-skill-improver` (which targets skills). The two run staggered — skills at 03:30, routines at 03:45 — so they never fight over git or LLM resources.

The whole routine MUST be idempotent. If it runs twice on the same day with the same input signals, archive state should be identical — never duplicate candidates. Implement this by checking, before drafting `v<N>.md`, whether a candidate at that version already exists with the same `lessons_applied:` set. If so, skip that routine/pipeline silently.

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
   adjusting the year as needed. Pay special attention to entries that mention routine/pipeline run outputs — both the `## HH:MM — <routine-name> run` headers and the `## HH:MM — Pipeline …` blocks emitted by the harness.

3. **Rolling context** — if `vault/main/.context.md` exists, read it. It captures the current agent state and recent decisions.

## Step 2 — Identify candidate routines and pipelines

Walk through every signal collected in Step 1 and extract structured mentions:

- Find any reference to a routine (e.g. `vault-health`, `vault-rebuild`, `vault-lint`, `journal-audit`, `journal-weekly-rollup`, `journal-monthly-rollup`, `update-check`, `oss-radar-v2`, `agent-routines`, `skill-audit`, `meta-skill-improver`). Note the surrounding sentence.
- Find any reference to a pipeline (e.g. `oss-radar-v2` is a v2 pipeline). If the mention names a specific STEP (e.g. "the analyze step of oss-radar-v2 timed out"), record the step id alongside the pipeline name.
- Classify each mention:
  - **positive** — "worked well", "saved time", "succeeded"
  - **neutral** — pure reference, no judgement
  - **negative** — "failed", "timed out", "wrong output", "had to retry", "confused me", "ran too late", "missed the window", "spurious notification", "wrong format"

Build an internal table:

| name | kind | negative count | step id (pipelines only) | lesson refs |
|------|------|----------------|--------------------------|-------------|
| vault-lint | routine | 2 | — | Lessons/2026-05-14-lint-false-positive.md, Lessons/2026-05-17-lint-frontmatter.md |
| oss-radar-v2 | pipeline | 1 | analyze | Lessons/2026-05-16-radar-format.md |
| journal-audit | routine | 1 | — | Lessons/2026-05-18-audit-gap.md |

A routine becomes a **candidate** if:
- It has ≥1 negative mention in the window, OR
- Its last run failed twice in a row (check `vault/main/Routines/.history/` if present, plus the routine-run blocks in the daily Journal entries).

A pipeline becomes a **candidate** if it has ≥1 negative mention in the window, OR:
- A specific step is mentioned as failing repeatedly (the step id surfaces in the table above), OR
- The Telegram output format was wrong / the user reacted negatively (check `vault/main/Reactions/` for negative reactions tied to pipeline messages).

**Early-exit:** if no candidate routines or pipelines surface, respond with exactly `NO_REPLY` and stop. Do NOT write empty changes or create empty archive directories.

## Step 3 — For each candidate, plan the patch

For every candidate from Step 2:

1. Read the live file `vault/main/Routines/<name>.md` in full.
2. For pipelines, also list `vault/main/Routines/<name>/steps/` and read every step prompt file mentioned in the candidate row (i.e. the step ids that surfaced as failing).
3. Re-read every lesson the routine/pipeline was mentioned in. Extract:
   - The specific **failure mode** (what broke)
   - The user's documented **Fix** (what worked)
   - The **Detect next time** signal (early-warning sign)
4. Draft an improved version that addresses these failure modes. Keep the prose tight. Do NOT rewrite from scratch — patch surgically:
   - **Routines:** tighten the prompt, add fallback instructions for the failure mode, fix the output format the user complained about, add an "Avoid" or "Common pitfalls" section, preserve the original frontmatter shape, only bump `updated:`.
   - **Pipelines — STEP-level patches are the default.** Most failures live in a single `steps/<step-id>.md` prompt file (wrong output shape, missing fallback, ambiguous instructions). Prefer patching that single step file over rewriting the pipeline YAML. A step-file edit is small, isolated, and easy to revert; a YAML edit changes orchestration and can cascade.
   - **Pipelines — YAML patches only when orchestration is wrong.** Touch the YAML inside `Routines/<name>.md` only if the failure is genuinely about depends_on, output sinks, retry behavior, or notify mode. Document explicitly in the candidate's body which step files (if any) and which YAML lines (if any) were changed.

## Step 4 — Apply the routine-versioning contract

Read `vault/Skills/routine-versioning.md` to refresh the exact archive format (created in parallel — it defines the directory layout, naming convention, and required frontmatter fields for routines and pipelines, including the snapshot rule for the `steps/` subdirectory in v2 pipelines). Then, for each candidate:

1. **Bootstrap if needed.** If `vault/main/Routines/_archive/<name>/` does not exist:
   - Create the directory
   - Save the CURRENT live content as `v1.md` with frontmatter `status: archived`, `parent_version: null`, `lessons_applied: []`, `score: null`, `promoted_at: null`
   - For v2 pipelines: ALSO snapshot the entire `vault/main/Routines/<name>/steps/` subdirectory as `vault/main/Routines/_archive/<name>/v1-steps/`. Without this, restoring v1 later would lose the step prompts.
   - The new candidate will become `v2.md` (and `v2-steps/` for pipelines if any step files were modified).

2. **Determine next version `N`.** List the existing files in `_archive/<name>/`, parse versions from `v<digits>.md`, and pick `N = max(existing) + 1`.

3. **Pick a parent version (optional, open-ended).** Read `vault/Skills/skill-parent-selection.md` for the parent-picking logic — the skill is artifact-agnostic, substitute "routine" or "pipeline" for "skill" mentally. By default, `parent_version = N - 1`. The parent-selection logic MAY recommend a different ancestor if its open-ended search finds a better one (e.g. an older candidate with a higher score that was never promoted).

4. **Archive the current live content.** If `v<N-1>.md` does not already mirror the current live content, save it now with `status: archived` (and for v2 pipelines, also snapshot `steps/` as `v<N-1>-steps/`). If it already does (because a previous meta-routine-improver run archived it), skip — idempotency.

5. **Save the new candidate.** Write `vault/main/Routines/_archive/<name>/v<N>.md` with:
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
   followed by the patched body. For v2 pipelines, also write `vault/main/Routines/_archive/<name>/v<N>-steps/` containing every step file (changed or unchanged — full snapshot, so a rollback is a single directory copy). Use the routine-versioning skill as the source of truth for the exact procedure — do NOT inline the layout details here.

6. **Do NOT overwrite the live file yet.** Promotion is gated by Step 5 (staged eval) and Step 5.5 (schedule-change safeguard). For this first deployment, default to leaving the candidate unpromoted for human review.

## Step 5 — Staged evaluation (score-gated, optional)

Read `vault/Skills/skill-staged-eval.md` — the staged-eval contract applies to routines too. Substitute "routine" for "skill" mentally; the staged-eval scoring is artifact-agnostic and the cheap → full gating works identically. The only thing that changes is the EVALUATION INPUTS:

- **Routines:** the staged-eval skill scores against "past invocations". For routines, that means scoring the routine's prompt against actual past Journal entries that show its output (look for `## HH:MM — <routine-name> run` blocks in the last 7 daily files). Use those historical outputs as the reference for whether the patched prompt would produce equally good or better answers.
- **Pipelines:** score per-step against the historical step-output files in `vault/main/.workspace/data/<pipeline-name>/`. Each step writes its output to `data/<step-id>.md`; the latest few runs there are the ground truth. Score the patched step prompt against the most recent successful run plus the most recent failed run.

For each candidate:

1. Run the **stage-1 cheap eval** described in the skill (typically a fast self-critique pass that produces a numeric score between 0 and 1).
2. If `score ≥ 0.65`, the candidate is eligible for auto-promotion (subject to Step 5.5). You MAY:
   - Overwrite `vault/main/Routines/<name>.md` with the candidate body (and for v2 pipelines, copy `v<N>-steps/` over `vault/main/Routines/<name>/steps/`)
   - Update `_archive/<name>/v<N>.md` frontmatter to `status: live`, `promoted_at: <YYYY-MM-DDTHH:MM:SS>`
3. Otherwise leave `status: candidate` and let the human approve.

**For this first deployment, DEFAULT TO NOT AUTO-PROMOTING.** Even when stage-1 produces a high score, leave all candidates as `status: candidate`. The human approves via Telegram by inspecting the diff in `_archive/<name>/v<N>.md` (and `v<N>-steps/` for pipelines) and copying it over the live file manually. Step 7's summary message lists exactly which files to review.

Auto-promotion can be enabled in a future revision once we have confidence in the cheap eval signal AND in the schedule-change safeguard (Step 5.5).

## Step 5.5 — Schedule change safeguard

This step is unique to meta-routine-improver and has no equivalent in meta-skill-improver. Skills don't have schedules; routines do, and a wrong schedule is a blast-radius event (a routine that runs every minute can DDoS the bot; a routine that moves from 04:00 to 14:00 can collide with the user's working session).

For every candidate:

1. Diff the candidate's `schedule:` block against the live file's `schedule:` block — compare `times`, `days`, `interval`, `monthdays`, and `until` exactly.
2. If ANY schedule field differs, mark the candidate `schedule_changed: true` in your internal table.
3. **A candidate with `schedule_changed: true` MUST NOT be auto-promoted, regardless of the staged-eval score from Step 5.** Even a 0.95 score does not override this — leave `status: candidate` and require a human to approve. The reasoning: a prompt patch that ships with a schedule change is two independent decisions wearing one frontmatter, and the schedule decision deserves its own conscious review.
4. Surface the schedule diff explicitly in the Step 7 Telegram summary with a clear `⚠️ Schedule change` line.

Pipelines also have schedules (the top-level frontmatter), so this rule applies to them too. Step-only patches that leave the YAML schedule untouched are exempt from this safeguard — only changes to the top-level `schedule:` trigger it.

## Step 6 — Record in today's Journal

Append a single entry to `vault/main/Journal/<YYYY-MM>/<YYYY-MM-DD>.md` (create the file with proper frontmatter if it doesn't exist yet — follow the conventions in `vault/CLAUDE.md`):

```
## <HH:MM> — Meta routine improver run

- Candidates drafted: <N>
- Routines touched: <comma-separated list of routine/pipeline names>
- Lessons consulted: <count>
- Schedule changes flagged: <count>
- All candidates in `status: candidate` — awaiting human promotion
```

Use plain text — NO wikilinks in journal entries (per `main/CLAUDE.md`). Mention routine names as `vault-lint` not `[[vault-lint]]`.

## Step 7 — Telegram summary

Final output to the bot. This message goes straight to Telegram.

**If Step 2 produced zero candidates**, output exactly:

```
NO_REPLY
```

**Otherwise**, output a structured markdown summary:

```
🔁 *Meta routine improver — <YYYY-MM-DD>*

Candidates drafted: *<N>*
- `<routine-name-1>` → `Routines/_archive/<routine-name-1>/v<N>.md`
  Reason: <one-line summary of the lesson that drove the patch>
  ⚠️ Schedule change: <times: ["03:00"] → ["03:30"]>   (only if schedule_changed)
- `<routine-name-2>` → `Routines/_archive/<routine-name-2>/v<N>.md`
  Reason: <one-line summary>

Review with: open the archive files in Obsidian.
To promote: copy archive content over the live file and update frontmatter (see `Skills/routine-versioning.md`).
```

Keep the message under ~1.5K characters so it fits one Telegram message comfortably. If more than ~6 candidates surface in one run, list the top 6 by negative-mention count and append `... and <K> more — see vault/main/Routines/_archive/`.
