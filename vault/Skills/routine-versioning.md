---
title: Routine Versioning
description: Defines the archive layout, frontmatter schema, and rollback/branching mechanics for versioned routines and pipelines — the substrate the meta-routine-improver routine writes into. Mirrors Skills/skill-versioning.md for routines.
type: skill
created: 2026-05-19
updated: 2026-05-19
trigger: "when a routine or agent needs to archive an old routine/pipeline version, promote a new one, roll back, or select a parent for the next mutation"
tags: [skill, meta, self-improvement, versioning, archive, routine, pipeline]
---

# Routine Versioning

## 1. Why this exists

The `meta-routine-improver` routine writes new versions of an agent's routines and pipelines as it learns from lessons, evals, and failures. This file is the **contract** for HOW those versions are stored on disk — so every version is rollback-able, branchable, and auditable, and so the parent-selection logic can pick non-latest ancestors without ambiguity.

If the layout described below is not honored, rollback breaks, parent selection breaks, and the open-ended search loop becomes a glorified linear overwrite.

---

## 2. Directory layout

For each routine (or pipeline) that is under meta-improver management:

- **Live routine — single-file (v1 routine, single-step pipeline):** `vault/<agent>/Routines/<routine-name>.md`
- **Live routine — multi-file (Pipeline v2 with `steps/` subdirectory):** `vault/<agent>/Routines/<routine-name>/<routine-name>.md` (the parent file) plus `vault/<agent>/Routines/<routine-name>/steps/<step-id>.md` (raw prompt files, no frontmatter)
- **Archive root:** `vault/<agent>/Routines/_archive/<routine-name>/`
- **Archived routine file:** `vault/<agent>/Routines/_archive/<routine-name>/v<N>.md`
- **Archived steps snapshot (Pipeline v2 only, when step prompts changed):** `vault/<agent>/Routines/_archive/<routine-name>/v<N>-steps/<step-id>.md`

`N` is a positive integer starting at `1`. `v1` is always the **initial** version — the live routine content captured **before** the meta-improver touched it for the first time. There are no gaps in the integer sequence and there is no `v0`.

The `_archive` directory uses a leading underscore so Obsidian sorts it to the top of the Routines folder and so a casual reader instantly recognizes it as system-managed scaffolding rather than a normal routine. The directory MUST contain exactly one subdirectory per managed routine, named identically to the live routine name (without `.md` for single-file routines, identical to the parent folder name for v2 pipelines). Example tree for a Main-agent pipeline:

```
vault/main/Routines/
├── oss-radar-v2/                      ← live multi-file pipeline
│   ├── oss-radar-v2.md                ← parent (frontmatter + steps list)
│   └── steps/
│       ├── collect.md                 ← raw prompt, no frontmatter
│       └── publish.md
├── skill-audit.md                     ← live single-file routine
├── _archive/
│   ├── oss-radar-v2/
│   │   ├── v1.md                      ← bootstrap (mirror of original parent)
│   │   ├── v1-steps/                  ← bootstrap step snapshot
│   │   │   ├── collect.md
│   │   │   └── publish.md
│   │   ├── v2.md                      ← first mutation (e.g. parent prompt change only)
│   │   ├── v3.md                      ← mutated step prompts
│   │   └── v3-steps/
│   │       ├── collect.md
│   │       └── publish.md
│   └── skill-audit/
│       ├── v1.md
│       └── v2.md
```

Every archived `v<N>.md` file is itself a normal markdown file with its own YAML frontmatter and a body. It is NOT a graph node in the Obsidian sense — archived routines carry `type: history` and the graph builder ignores history nodes (see `vault/CLAUDE.md`).

The archived step files inside `v<N>-steps/` preserve the no-frontmatter contract of live step prompts (per `vault/CLAUDE.md`: pipeline step prompts under `Routines/{pipeline}/steps/*.md` are raw text with no frontmatter and no wikilinks). They are stored verbatim — content only, no header added.

---

## 3. Frontmatter for archived versions

Every `_archive/<routine-name>/v<N>.md` MUST have this frontmatter shape:

```yaml
---
title: <Routine Title> — v<N>
description: Snapshot of <routine-name> at version N. Branched from v<P>. <one-sentence rationale for what changed>.
type: history
created: <YYYY-MM-DD when this version was written>
updated: <YYYY-MM-DD>
tags: [routine, history, archive, <routine-name>]
version: <int>                       # e.g. 3 — same as the N in the filename
parent_version: <int|null>           # version this was branched from; null only for v1
live_routine: <agent>/Routines/<routine-name>.md
lineage: "v<P> → v<N>"               # human-readable single-hop chain; v1 has "v0 → v1"
score: <float|null>                  # populated by artifact-staged-eval (artifact-agnostic); null = not yet evaluated
lessons_applied: ["<agent>/Lessons/<file>.md", ...]   # paths that motivated this version; [] for v1 bootstrap
promoted_at: <YYYY-MM-DDTHH:MM>|null  # null until/unless promoted to live
status: candidate|live|archived|deprecated
---
```

Field notes:

- **`version`** — MUST equal the `N` in the filename (`v3.md` → `version: 3`). The filename is canonical; the field is a convenience for tools that read frontmatter without re-parsing the path.
- **`parent_version`** — for `v1` this is always `null`. For any later version it is the integer of the ancestor this version was mutated from. The parent is **not necessarily** `N - 1`; see §7.
- **`live_routine`** — vault-relative path to the live routine file. For multi-file pipelines this points at the parent file inside the routine's folder (e.g. `main/Routines/oss-radar-v2/oss-radar-v2.md`), not the folder itself. Lets a tool find "the canonical home" of an archive without inferring it from directory structure.
- **`lineage`** — single-hop human-readable string; long chains are reconstructed by walking `parent_version` repeatedly, not by stuffing them into one field.
- **`score`** — populated by the evaluation skill (`Skills/artifact-staged-eval.md` is artifact-agnostic and applies to routines too) after evaluation. `null` means "not yet evaluated" — the parent-selection skill treats `null` distinctly from a low score.
- **`lessons_applied`** — paths to lesson files (`<agent>/Lessons/*.md`) that motivated the mutation. Empty array `[]` for the `v1` bootstrap. The meta-improver uses this both for auditability and to avoid re-applying the same lesson twice in a row.
- **`promoted_at`** — ISO-ish `YYYY-MM-DDTHH:MM` local time when this version was written to the live file. `null` while the version is still a candidate or was never promoted.
- **`status`** — see §4.

---

## 4. State machine

A version sits in exactly one of four states:

| Status        | Meaning                                                                                                  |
| ------------- | -------------------------------------------------------------------------------------------------------- |
| `candidate`   | Just written by the meta-improver. Live routine is still the **previous** version. Not yet promoted.     |
| `live`        | This version is currently mirrored into the live routine file. At most one version is `live`.            |
| `archived`    | Was `live` once, has been superseded by a newer promoted version. Eligible as parent for future mutations. |
| `deprecated`  | Failed in production or was rolled back from. **NEVER** picked as parent. Kept on disk for audit only.   |

Allowed transitions:

```
candidate ──promote──▶ live ──supersede──▶ archived
                         │                     │
                         └────rollback────────▶│
                                               ▼
                                          deprecated
candidate ──reject (eval failed)───────▶ deprecated
```

A version that is `live` MUST also have `promoted_at` set. A version that is `archived` or `deprecated` MUST have been `live` (and thus also has `promoted_at`) at some prior point, unless it is the `v1` bootstrap (which is born `archived` with `promoted_at` set to the bootstrap timestamp — see §9).

---

## 5. Promotion (writing a new live version)

When the meta-improver decides to promote candidate `v<N>`:

1. **Capture current live.** Read the body of the live routine file and its frontmatter, especially its `version` field — call this `M` (the version currently live, where `M = N - 1` in the linear case but can be any prior version if `v<N>` was branched). For a Pipeline v2, also enumerate `steps/*.md` so the snapshot can be compared step-by-step.
2. **Demote the prior live mirror to `archived`.** Locate `vault/<agent>/Routines/_archive/<routine-name>/v<M>.md` and rewrite its frontmatter `status: live` → `status: archived`. (If the archive file does not yet exist because of a bootstrap edge case, write it from the captured live content — see §9.) Do not touch its body. If a `v<M>-steps/` snapshot exists, leave it untouched — archived snapshots are immutable.
3. **Overwrite the live file.** Write the candidate's full body to the live routine file. Also update the live file's frontmatter to set `version: N`, `updated: <today>`, and refresh `description` if the mutation changed scope. **Do not** add the other version metadata (`parent_version`, `lineage`, `score`, `lessons_applied`, `promoted_at`, `status`) to the live file — those live only in the archive copy. The live file mirrors body + identity, not state-machine bookkeeping.
4. **For Pipeline v2 only — sync step prompts.** If the candidate changed any `steps/<step-id>.md` content compared to the prior live, overwrite those step files with the candidate's versions and DELETE any step files the candidate removed. The harness reads step files lazily; partial states between steps 3 and 4 are tolerated for a single transaction, but step 4 MUST complete before the next scheduled fire of the pipeline.
5. **Write the new archive copy.** Create `vault/<agent>/Routines/_archive/<routine-name>/v<N>.md` containing the candidate's full body PLUS the version-frontmatter (per §3) with `status: live`, `promoted_at: <now>`, and `version: N`. The archive copy is the source of truth for state; the live file is a body mirror plus `version: N`.
6. **For Pipeline v2 only — write the step snapshot if step prompts changed.** If step 4 wrote any file, also create `vault/<agent>/Routines/_archive/<routine-name>/v<N>-steps/<step-id>.md` for every step in the candidate (the full set, not just the diff — restore needs the complete state). Step files are stored raw, with no frontmatter, mirroring the live step file contract. If NO step file changed between `v<M>` and `v<N>`, skip this step entirely — the absence of `v<N>-steps/` means "step state identical to nearest ancestor that has a snapshot".
7. **Verify integers.** After the writes, the archive directory MUST contain exactly one file with `status: live`, and its `version` MUST equal the `version` in the live file's frontmatter. If this invariant fails, the meta-improver MUST roll back its own writes and abort.

The live file's frontmatter is intentionally minimal — `version: N` is the only piece of state it carries. The rest is owned by `_archive/<routine-name>/v<N>.md`.

**IMPORTANT — disable during candidate authoring.** When the meta-routine-improver writes a candidate `v<N>.md` to the archive, it MUST NOT touch the live file's `enabled:` field. Candidates live in the archive only; the live file's schedule and enabled flag belong to whatever version is currently promoted. If the candidate is later promoted via the procedure above, the human takes responsibility for whether to keep `enabled: true` (cut over immediately on the next scheduled fire) or temporarily flip the live file to `enabled: false` during the cut-over to avoid a partially-deployed routine running once before being observed.

---

## 6. Rollback

A live version can become bad in two ways:

- **Manual rollback** — the user (or a routine reviewer) requests it explicitly.
- **Automatic rollback** — the evaluation skill re-evaluates the live version on a subsequent run and the score drops below the previous live's score by more than the eval's regression tolerance.

Procedure when rolling back live `v<N>`:

1. **Find the rollback target.** Scan `vault/<agent>/Routines/_archive/<routine-name>/v*.md`, filter to entries with `status: archived` (NEVER `deprecated`) and `score` not null, then pick the one with the **highest score** that is also strictly greater than `v<N>`'s score. If no such version exists (e.g. nothing was scored yet, or `v<N>` was the highest-scoring), abort the rollback and notify the user — silent rollback to an unscored or worse version is forbidden.
2. **Copy body into the live file.** Take the body of the target `v<M>.md` and write it to the live routine file. Update the live file's frontmatter: `version: M`, `updated: <today>`. Refresh `description` if the chosen ancestor's description is meaningfully different.
3. **For Pipeline v2 only — restore step snapshot.** Find the nearest ancestor of `v<M>` (walking via `parent_version`, or `v<M>` itself) that has a `v<K>-steps/` directory. Overwrite every file in the live `steps/` directory with the contents of `v<K>-steps/`, and DELETE any live step files not present in the snapshot. If no ancestor in `v<M>`'s lineage has a step snapshot, the rollback target predates any step change — in that case the current live `steps/` is already correct and no work is needed.
4. **Mark the bad version `deprecated`.** Rewrite `vault/<agent>/Routines/_archive/<routine-name>/v<N>.md`'s frontmatter `status: live` → `status: deprecated`. Append a brief `## Rollback reason` section to its body recording why (one sentence + timestamp). Do not delete the file. If `v<N>-steps/` exists, leave it on disk — archived snapshots are immutable and may be needed for forensic audits.
5. **Promote the chosen ancestor back to `live`.** Rewrite `v<M>.md`'s frontmatter `status: archived` → `status: live` and refresh `promoted_at` to the rollback timestamp. The previous `promoted_at` value is preserved in the rollback reason note for audit.
6. **Verify integers** (same invariant as §5 step 7): exactly one `status: live` in the archive, matching the live file's `version`.

Deprecated versions are never re-promoted automatically. If the user wants a deprecated version back, they edit its `status` manually — the meta-improver does not undeprecate.

---

## 7. Branching (open-ended search)

The `parent_version` field is the open-ended-search hook. When the meta-improver writes `v<N>`, the parent it mutated from is **whatever the parent-selection skill returned**, not necessarily `v<N-1>`.

Concrete consequence: if linear promotion produced `v1 → v2 → v3 → v4` and the parent-selector decides `v2` is the most promising base for the next mutation (e.g. because `v3` and `v4` scored worse and the search space wants exploration), then `v5` will have `parent_version: 2` and `lineage: "v2 → v5"`. The integer in the filename is monotonic (5 > 4 > 3 > 2 > 1), but the `parent_version` graph is a tree, not a line.

This is the substrate that makes the loop **open-ended** in the HyperAgents sense — without it, every mutation overwrites the latest, the search collapses to greedy hill-climbing, and a single bad mutation poisons all descendants. The decision of *which* parent to pick lives entirely in `Skills/artifact-parent-selection.md`; that skill is artifact-agnostic — substitute "routine" for "skill" mentally; the parent-picking logic works identically for both. This file only guarantees that the disk layout supports any choice the selection skill makes.

---

## 8. Live file embeds its version

Inside the live routine file (`<agent>/Routines/<routine-name>.md` for single-file routines, `<agent>/Routines/<routine-name>/<routine-name>.md` for v2 pipelines), the frontmatter carries exactly one piece of versioning state:

```yaml
version: <N>
```

This is the version number currently mirrored into the live file. Any tool that needs to find the canonical archive of "what's live right now" reads this number and opens `_archive/<routine-name>/v<N>.md`. The agreement between live `version` and the single `_archive` entry with `status: live` is the system's primary invariant (see §5 step 7 and §6 step 6).

The live file does NOT carry `parent_version`, `lineage`, `score`, `lessons_applied`, `promoted_at`, or `status`. Putting them there would create two sources of truth that drift. The live file is for the runtime (the scheduler reads `schedule`, `enabled`, `model`, `pipeline_version`, etc. on every fire); the archive copy is for the state machine.

For routines that have not yet been touched by the meta-improver, the `version` field is absent from the live frontmatter. The first promotion writes it.

---

## 9. First-time conversion (bootstrap)

When the meta-improver decides to mutate a routine that has no `_archive/<routine-name>/` directory yet:

1. **Create the directory.** `mkdir -p vault/<agent>/Routines/_archive/<routine-name>/`.
2. **Snapshot the current live as `v1`.** Copy the current body of the live routine file into `vault/<agent>/Routines/_archive/<routine-name>/v1.md`, then prepend the frontmatter described in §3 with these specific values:
   - `version: 1`
   - `parent_version: null`
   - `lineage: "v0 → v1"`
   - `status: archived` (not `live` — `v2` is about to take the live slot, see step 5)
   - `promoted_at: <bootstrap timestamp>` (the timestamp at which this routine first came into existence — use today's date if unknown)
   - `score: null`
   - `lessons_applied: []`
   - `live_routine: <agent>/Routines/<routine-name>.md` (or the parent path inside the v2 folder)
3. **For Pipeline v2 only — snapshot the steps.** `mkdir -p vault/<agent>/Routines/_archive/<routine-name>/v1-steps/` and copy every `steps/<step-id>.md` from the live pipeline into it. No frontmatter is added — step files are preserved as-is per the vault contract.
4. **Bump the live file's frontmatter.** Add `version: 1` to the live routine file's frontmatter if it isn't already there. Do NOT change the body in this step. The live file is now in a consistent v1 state.
5. **Proceed with normal promotion of `v2`.** Run the §5 procedure to write the candidate as `v2`. Because §5 demotes the prior live archive entry from `live → archived`, and `v1` is already `archived` from step 2, no extra demotion is needed — `v2` simply becomes the unique `status: live` entry.

Step 2 deliberately stamps `v1` as `archived` rather than `live` so the post-bootstrap state mirrors a regular post-promotion state without needing a "first time is special" branch elsewhere in the system.

---

## 10. Reading the archive (for parent-selection / audits)

The archive is designed to be read **frontmatter-only** for the common case. Procedure:

1. `ls vault/<agent>/Routines/_archive/<routine-name>/v*.md` to enumerate versions (the `v<N>.md` files, not the `v<N>-steps/` directories).
2. For each file, read **only the first ~15 lines** — enough to capture the full frontmatter block. Do not read the body unless you actually need the prompt text (e.g. you are about to mutate it). Do not descend into `v<N>-steps/` unless the consumer specifically needs step content (a rollback or a step-level mutation).
3. **Filter** by `status != deprecated`. Deprecated versions are kept on disk for audit but are NEVER candidates for parent selection.
4. **Sort** depending on use case:
   - **Chronological** — sort ascending by `version` (the integer). Equivalent to sorting by filename's `v<N>` suffix.
   - **Best-first** — sort descending by `score`, with `score: null` placed at the end (so unevaluated versions don't masquerade as good ones).
   - **Lineage walk** — start from any version and follow `parent_version` repeatedly until `null` is reached. Yields the chain of ancestors. Cycles are impossible because `parent_version < version` is enforced (every parent has a strictly smaller integer).

A typical audit query (best non-deprecated version with a known score) is:

> List `v*.md` where `status in {archived, live, candidate}` and `score is not null`, sort by `score desc`, take 1.

A typical parent-selection query is:

> List `v*.md` where `status in {archived, live}` (NEVER `candidate`, which hasn't been promoted and shouldn't be a base) and `score is not null OR version == 1` (the bootstrap is always a legitimate fallback), then apply the open-ended-search policy from `Skills/artifact-parent-selection.md`.

These access patterns are what makes the frontmatter schema in §3 the actual contract — every field there exists because one of the readers below needs it:

- `meta-routine-improver` reads `lessons_applied`, `lineage`, `parent_version`, and writes new versions.
- The evaluation skill reads any version's body (and step snapshots for v2 pipelines), populates `score`, and may trigger rollback via §6.
- `artifact-parent-selection` reads `version`, `parent_version`, `score`, `status` to decide what to mutate next.

Any change to the schema in §3 MUST update all three consumer skills in the same commit. Diverging the schema silently is the failure mode this file is here to prevent.

---

## 11. Routine-specific quirks

These are gotchas that don't exist for skills and that the meta-routine-improver MUST honor explicitly.

- **Schedule changes are sensitive.** If the candidate proposes a different `schedule.times:`, `schedule.interval:`, `schedule.days:`, or `schedule.monthdays:` from the prior live, the human MUST approve the change. Never auto-promote a schedule change without a Telegram confirmation step — the consequences (missed fires, doubled fires during the cut-over window, off-hours wake-ups) are user-visible in ways a prompt mutation is not. Surface the diff in the Telegram summary as `schedule: <before> → <after>` and require an explicit ack before §5 runs.

- **`enabled: false` candidates can be safely written.** A candidate that exists but is disabled won't fire even if promoted prematurely; useful when drafting a routine that needs human review of side effects. The candidate frontmatter (in the archive copy) is permitted to carry `enabled: false` — promotion still works the same way, but the live file inherits `enabled: false` and the user must flip it manually to activate. This is the recommended path when the routine touches external state (Telegram, Notion, vault writes) and a dry-run is needed before scheduling.

- **Pipeline `pipeline_version:` migrations.** If a candidate changes `pipeline_version:` from `1` to `2` (or vice versa), it is a STRUCTURAL change — the file moves from a single-file routine to a multi-file pipeline (or back), the harness's execution model changes, step files appear or disappear, and downstream readers (the Telegram notification path, the pipeline log writer, the `journal-audit` parser) all behave differently. Surface `pipeline_version: <before> → <after>` PROMINENTLY in the Telegram summary (call it out separately from the routine body diff), require explicit user confirmation before promoting, and refuse to merge such a candidate via any automatic eval-based promotion path. A `pipeline_version` migration is human-only.

- **`model:` change tracking.** Bumping a routine from `sonnet` to `opus` (or any cost-asymmetric change like `glm-4.7 → opus`) changes the per-fire cost; flag the diff in the summary as `model: <before> → <after>`. Cost-decreasing migrations (e.g. `opus → sonnet`) are equally worth surfacing because they may signal a quality regression hidden behind a savings argument. The model change is NOT a blocker like `pipeline_version` is — auto-promotion is allowed if the eval covers it — but the surfaced diff lets the user catch a runaway optimization that trades quality for speed before it becomes the new baseline.
