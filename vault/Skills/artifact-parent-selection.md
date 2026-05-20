---
title: Artifact Parent Selection
description: Picks a parent version from an artifact's archive (skill, routine, or pipeline) to seed the next mutation — biased toward latest but occasionally backtracks to a non-latest ancestor to maintain open-ended search. Mirrors HyperAgents' select_next_parent.py. Renamed from skill-parent-selection on 2026-05-19 to reflect artifact-agnostic scope.
type: skill
created: 2026-05-19
updated: 2026-05-19
trigger: "when a routine needs to pick which historical artifact version to mutate next — usually invoked by meta-skill-improver or meta-routine-improver before drafting a candidate"
tags: [skill, meta, self-improvement, search, hyperagents, artifact]
---

## 1. Why this exists

Mutating only from the latest version creates a greedy hill-climber that gets stuck in local optima. HyperAgents' `select_next_parent.py` uses pure random selection from the valid archive to keep the search space open. We adopt the same idea with a mild bias toward recency — random pure exploration is wasteful when latest is usually better, but we don't want to ignore exploration entirely.

The fundamental insight: every "improvement" step is also a commitment. If you always mutate from the latest, you implicitly assume the last mutation was strictly better than every ancestor. That assumption is wrong often enough — especially when the fitness signal is noisy (LLM-judged scores) — that you want to keep a door open to backtracking. This skill is that door.

The logic works identically whether the artifact is a skill, a routine, or a pipeline — the only thing that changes is the archive directory we glob (`Skills/_archive/<name>/` vs `Routines/_archive/<name>/`). Throughout the rest of this document "skill" reads as a stand-in for "the artifact being mutated"; the procedure does not branch by artifact kind.

## 2. Inputs

The caller provides:

- `agent` — the agent id (e.g. `main`)
- `name` — the artifact's name (e.g. `fetch-web` for a skill, `oss-radar-v2` for a pipeline)
- `kind` — one of `skill | routine | pipeline`. Used only to pick the archive directory: `skill` → `Skills/_archive/<name>/`, `routine`/`pipeline` → `Routines/_archive/<name>/`.
- `strategy` (optional) — one of `latest | recency-weighted | random | best`. Defaults to `recency-weighted`.

## 3. Read the archive

1. Glob `vault/<agent>/Skills/_archive/<skill>/v*.md` (e.g. `v1.md`, `v2.md`, `v3.md`).
2. Read only the frontmatter of each (first ~15 lines is enough — stop at the second `---`).
3. Build a list of candidates, **filtering out** any with `status: deprecated`.
4. Each candidate carries: `path`, `version` (int parsed from filename), `score` (float from frontmatter, may be missing), `status`.

If the archive is empty — either the `_archive/<skill>/` directory doesn't exist yet, or every version found has `status: deprecated` and was filtered out — see Edge cases (§6).

## 4. Strategies

Document four strategies the caller can request. The default is `recency-weighted`.

### latest

Trivial — pick the version with the highest `version:` number whose `status != deprecated`. Use this when you explicitly want greedy hill-climbing (e.g. during a "stabilize current branch" phase).

### recency-weighted (default)

Bias toward newer versions but allow exploration. Roll a single random number `r` in `[0, 1)`:

- `r < 0.70` → **latest**: pick the highest-version valid candidate.
- `0.70 ≤ r < 0.90` → **non-latest exploration**: pick uniformly at random from the set of valid candidates *excluding* the latest one.
- `0.90 ≤ r < 1.00` → **best-score backtrack**: pick the candidate with the highest `score:` value. Tie-break by recency (higher `version` wins).

Fallback rules within recency-weighted:

- If the "non-latest exploration" bucket fires but there is only one valid candidate (so the non-latest set is empty), fall back to **latest**.
- If the "best-score backtrack" bucket fires but **no candidate has a `score:` field**, fall back to **latest**.
- If every candidate has the same score, "best-score" reduces to "latest" via the tie-break rule, which is fine.

### random

Uniform random over all non-deprecated versions. Matches HyperAgents' default behavior literally. Use this when you want maximum exploration — e.g. during a "we're clearly stuck, shake it up" intervention.

### best

Pick the version with the highest `score:` value. Tie-break by recency (higher `version` wins). Use this when you want to consolidate gains — typical at the end of an iteration cycle, or before showing the result to a human.

## 5. Output

Return the chosen version as a JSON object printed to stdout (single line or pretty-printed — caller will parse either):

```json
{
  "agent": "main",
  "skill": "fetch-web",
  "strategy_used": "recency-weighted",
  "rolled": 0.83,
  "chosen_path": "vault/main/Skills/_archive/fetch-web/v3.md",
  "chosen_version": 3,
  "chosen_score": 0.62,
  "reason": "non-latest exploration (rolled into 0.7–0.9 bucket)"
}
```

Field notes:

- `strategy_used` — the strategy that actually produced the choice. Differs from the requested strategy when an edge case forced a fallback (e.g. `"bootstrap"`, `"single-candidate"`).
- `rolled` — the random number drawn, when applicable. Omit (or set `null`) for deterministic strategies (`latest`, `best`).
- `chosen_score` — may be `null` if the chosen version has no `score:` frontmatter field yet.
- `reason` — one short human-readable phrase explaining which bucket/path was taken. This is what shows up in telemetry (§8).

The caller (meta-skill-improver) reads the JSON, opens `chosen_path`, and treats that file's BODY content as the seed for the next candidate's draft. The new candidate's frontmatter gets `parent_version: <chosen_version>`.

## 6. Edge cases

- **Empty archive** (no `_archive/<skill>/` directory, or it exists but is empty) → return the **live file path** as parent: `vault/<agent>/Skills/<skill>.md`. The caller treats this as `v1` and bootstraps the archive on first promotion. `strategy_used: "bootstrap"`, `reason: "no archive yet — seeding from live file"`. If the live file also doesn't exist, return `{"error": "NO_SKILL_FOUND", "skill": "..."}`.
- **Only one valid version** → return it regardless of requested strategy. `strategy_used: "single-candidate"`, `reason: "only one valid version in archive"`.
- **All versions deprecated** → flag a hard error to the caller: `{"error": "ALL_DEPRECATED", "skill": "..."}`. The caller (meta-skill-improver) must escalate to a human via Telegram — this means every past mutation was judged worse than its parent, which is a signal that needs human review.
- **Score field missing on all versions** → recency-weighted's best-score bucket cannot fire; collapse it into latest. Effective distribution becomes 80/20 latest vs random non-latest. Note this in `reason` so telemetry shows what happened.
- **Score field missing on some but not all** → best-score bucket only considers candidates that have a score. If the requested strategy is `best` and *zero* candidates have a score, fall back to `latest` and set `reason: "best requested but no scores yet — fell back to latest"`.

## 7. Why these specific weights (one paragraph)

We deliberately keep the explore-exploit balance modest (30% exploration total). HyperAgents' published code uses pure random (100% exploration) because their archive is huge and benchmarks are objective — broad exploration is cheap relative to compute and noise-tolerant. Our archive will be small (one per skill, growing slowly) and our "score" is LLM-judged (noisy), so we lean toward the latest most of the time. The 20% non-latest / 10% best-score split exists so we always test *some* alternative hypothesis on each run: 20% says "maybe an older branch was better, let's mutate from there"; 10% says "let's specifically revisit the historically-best branch even if it's not the latest". Tune the weights only if real-world behavior shows the system is stuck (raise exploration) or thrashing (lower it).

## 8. Telemetry

Each invocation appends one line to `vault/<agent>/Journal/<YYYY-MM>/<YYYY-MM-DD>.md` under a `## <HH:MM> — Parent selection` heading (create the heading if today's journal doesn't have one yet):

```
- <skill-name>: chose v<N> via <strategy_used> (rolled <r>, score <s>)
```

If `rolled` or `score` is null/missing, render it as `n/a`. Example:

```
## 14:22 — Parent selection
- fetch-web: chose v3 via recency-weighted (rolled 0.83, score 0.62)
- summarize-thread: chose v1 via bootstrap (rolled n/a, score n/a)
```

This makes the search behavior auditable over time — if every line shows "latest", the system is greedy and getting stuck; if too many show "random", the system is noisy and not committing to a branch. The meta-skill-improver routine can also tail this telemetry to self-diagnose.
