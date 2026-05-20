---
title: Skill Staged Eval
description: Defines a two-stage evaluation procedure (cheap sample-of-3 → expensive sample-of-15) for scoring candidate skill versions before promotion. Mirrors HyperAgents' test_more_threshold gating to avoid burning tokens on bad candidates.
type: skill
created: 2026-05-19
updated: 2026-05-19
trigger: "when a routine or agent needs to score a candidate skill version against historical inputs before promoting it"
tags: [skill, meta, self-improvement, evaluation, hyperagents]
---

## 1. When to invoke

This skill is consumed by [[meta-skill-improver]] (or any future routine that needs to evaluate a candidate skill). The caller MUST provide three arguments:

- `candidate_path` — path to the candidate skill file (e.g. `vault/<agent>/Skills/_archive/<skill-name>/v<N>.md`)
- `live_path` — path to the current live skill (e.g. `vault/<agent>/Skills/<skill-name>.md`)
- `agent_id` — the owning agent (used to locate Journal, Lessons, Reactions)

This skill ONLY scores. It does not promote, deprecate, or move files. The caller decides what to do with the score.

## 2. Pick historical inputs

"Inputs" = past situations where the LIVE skill was invoked. Source them in this priority order and stop once you have enough to fill stages 1 + 2 (up to 18 total):

1. **Journal entries from the last 30 days that name the skill in plain text**
   - `grep -rn "<skill-name>" vault/<agent>/Journal/` (limit to the last 30 daily files)
   - Each matching line + a 3-line surrounding window counts as one input
2. **Lesson files that name the skill**
   - `vault/<agent>/Lessons/` — anything where the skill appears in the body or frontmatter `applies_to`
3. **Reaction files** — `vault/<agent>/Reactions/` where the user reacted (👍 / 👎 / 🤔) to a message produced by a routine that invoked the skill. The reaction polarity is the natural label for that input.

Each "input" is a tuple `{situation, expected_outcome_or_label, source_path}`. Keep the source path so the eval log is auditable.

**If fewer than 3 historical inputs are available across all three sources, output `INSUFFICIENT_HISTORY` and skip evaluation.** The candidate stays `status: candidate` with no score; the caller decides whether to promote without one.

## 3. Stage 1 — cheap eval (sample of 3)

Pick 3 representative inputs. Prefer diversity over randomness:

- If reactions exist, prefer one positive (👍), one negative (👎), one neutral/ambiguous
- Otherwise, prefer one input that matches the failure mode the candidate claims to fix, one that the live skill handled correctly, one drawn at random from the remainder
- If history is too thin to satisfy diversity, fall back to random 3

For each of the 3 inputs:

1. **Simulate the LIVE skill** — read the live skill body, mentally execute it against the input situation, produce a hypothetical output
2. **Simulate the CANDIDATE skill** — same exercise with the candidate body
3. **Score on three axes** (each `0.0` to `1.0`, float):
   - **Faithfulness** — does the candidate still produce the same *shape* of output (same fields, same intent, same downstream contract)? Changing an intent silently breaks callers, so weight this heavily when in doubt.
   - **Improvement** — does the candidate fix the specific failure mode the lesson/journal/reaction called out? A candidate that doesn't actually address its motivating failure scores low here.
   - **No regression** — does the candidate avoid breaking cases the live skill handled correctly?
4. **Per-input score** = unweighted mean of the three axes
5. **Stage-1 score** = unweighted mean of the 3 per-input scores

**Gate: if stage-1 score < 0.4, STOP.**

Write `score: <stage-1-value>` and `eval_notes: "stopped at stage-1 below threshold"` to the candidate's frontmatter, append the Eval log section (see §5), and return — do NOT run stage 2.

## 4. Stage 2 — full eval (sample of 15)

Only runs if stage-1 ≥ 0.4. Pick up to 15 additional historical inputs (distinct from the 3 used in stage 1). If history yields fewer than 15, use what's available; do not duplicate stage-1 inputs to pad.

Repeat the same per-axis scoring as stage 1.

**Final score** = weighted average:
```
final = (0.3 × stage_1_score) + (0.7 × stage_2_score)
```
The weights reflect that stage-2 is larger and more reliable, but stage-1 still acts as a sanity floor.

If stage 2 ran on fewer than 5 inputs, set `eval_notes` to flag `"stage-2 thin (<5 inputs)"` so the caller knows the signal is weak.

## 5. Write the result

Update the candidate file's YAML frontmatter in place (preserve every other field):

- `score: <final-float-2dp>` (e.g. `0.62`)
- `eval_notes: "stage-1=<v>, stage-2=<v>, inputs=<n>"`

Append a section at the bottom of the candidate file body:

```
## Eval log — <YYYY-MM-DD HH:MM>

- Stage 1: <stage_1_score>, <n1> inputs
- Stage 2: <stage_2_score>, <n2> inputs
- Final: <final_score>
- Strongest improvement axis: <faithfulness|improvement|no_regression>
- Weakest axis: <faithfulness|improvement|no_regression>
- Sources sampled: <comma-separated source paths>
```

If stage 2 did not run, write `- Stage 2: skipped (gated)` and omit the `n2` figure.

## 6. Promotion thresholds (advisory)

This skill only scores. The caller decides. Recommended thresholds — the caller may override:

- `score >= 0.65` → safe to auto-promote
- `0.40 <= score < 0.65` → leave as `status: candidate`, surface for human review
- `score < 0.40` → caller should mark `status: deprecated`; don't iterate further on this lineage

## 7. Output to caller

Print exactly one JSON object to stdout (the calling routine parses it). No prose around it.

```json
{
  "candidate_path": "vault/<agent>/Skills/_archive/<skill-name>/v<N>.md",
  "score": 0.62,
  "stage_1_score": 0.55,
  "stage_2_score": 0.65,
  "input_count": 14,
  "recommendation": "promote|review|deprecate",
  "notes": "<short string, ≤ 120 chars>"
}
```

`recommendation` maps the advisory thresholds in §6: `promote` (≥0.65), `review` (0.40–0.65), `deprecate` (<0.40). When stage-1 gating fires, `stage_2_score` is `null` and `recommendation` is `deprecate`.

## 8. Failure modes

Handle each by emitting a single stdout token (and aborting cleanly):

- **No history** → output `INSUFFICIENT_HISTORY` and return without writing a score
- **Live skill missing** → output `MISSING_LIVE` and abort
- **Candidate file unreadable** → output `UNREADABLE_CANDIDATE` and abort
- **Any uncaught error** → append to today's `vault/<agent>/Journal/YYYY-MM/YYYY-MM-DD.md` under a `## <HH:MM> — Staged eval error` heading with a one-paragraph explanation, then abort gracefully (do not corrupt the candidate file)

In every failure case, leave the candidate's frontmatter untouched — partial scores are worse than no score.

## 9. Why this design

Mirror HyperAgents' core insight: most candidate mutations are bad, and running a full evaluation on every one of them wastes tokens. Stage 1 is a 3-input gate, cheap enough to run on every candidate. Stage 2 is the costly confirmation that only the survivors earn. The `0.4` threshold matches their `test_more_threshold` constant in `generate_loop.py` — empirically a gate that is loose enough to admit borderline-promising candidates but tight enough to reject the obvious losers. Keeping the same constant makes future cross-validation against their published results trivial.
