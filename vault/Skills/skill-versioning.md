---
title: Skill Versioning
description: Defines the archive layout, frontmatter schema, and rollback/branching mechanics for versioned skills — the substrate the meta-skill-improver routine writes into.
type: skill
created: 2026-05-19
updated: 2026-05-19
trigger: "when a routine or agent needs to archive an old skill version, promote a new one, roll back, or select a parent for the next mutation"
tags: [skill, meta, self-improvement, versioning, archive]
---

# Skill Versioning

## 1. Why this exists

The `meta-skill-improver` routine writes new versions of an agent's skills as it learns from lessons, evals, and failures. This file is the **contract** for HOW those versions are stored on disk — so every version is rollback-able, branchable, and auditable, and so the parent-selection logic can pick non-latest ancestors without ambiguity.

If the layout described below is not honored, rollback breaks, parent selection breaks, and the open-ended search loop becomes a glorified linear overwrite.

---

## 2. Directory layout

For each skill that is under meta-improver management:

- **Live skill** (unchanged from today): `vault/<agent>/Skills/<skill-name>.md`
- **Archive root**: `vault/<agent>/Skills/_archive/<skill-name>/`
- **Archived versions**: `vault/<agent>/Skills/_archive/<skill-name>/v<N>.md`

`N` is a positive integer starting at `1`. `v1` is always the **initial** version — the live skill content captured **before** the meta-improver touched it for the first time. There are no gaps in the integer sequence and there is no `v0`.

The `_archive` directory uses a leading underscore so Obsidian sorts it to the top of the Skills folder and so a casual reader instantly recognizes it as system-managed scaffolding rather than a normal skill. The directory MUST contain exactly one subdirectory per managed skill, named identically to the live skill filename (without `.md`). Example tree for the Main agent:

```
vault/main/Skills/
├── meta-skill-improver.md           ← live skill
├── _archive/
│   └── meta-skill-improver/
│       ├── v1.md                    ← bootstrap (mirror of original live)
│       ├── v2.md                    ← first mutation
│       ├── v3.md                    ← branched from v1 (open-ended)
│       └── v4.md                    ← currently live mirror
```

Every archived `v<N>.md` file is itself a normal markdown file with its own YAML frontmatter and a body. It is NOT a graph node in the Obsidian sense — archived skills carry `type: history` and the graph builder ignores history nodes (see `vault/CLAUDE.md`).

---

## 3. Frontmatter for archived versions

Every `_archive/<skill-name>/v<N>.md` MUST have this frontmatter shape:

```yaml
---
title: <Skill Title> — v<N>
description: Snapshot of <skill-name> at version N. Branched from v<P>. <one-sentence rationale for what changed>.
type: history
created: <YYYY-MM-DD when this version was written>
updated: <YYYY-MM-DD>
tags: [skill, history, archive, <skill-name>]
version: <int>                       # e.g. 3 — same as the N in the filename
parent_version: <int|null>           # version this was branched from; null only for v1
live_skill: <agent>/Skills/<skill-name>.md
lineage: "v<P> → v<N>"               # human-readable single-hop chain; v1 has "v0 → v1"
score: <float|null>                  # populated by skill-staged-eval; null = not yet evaluated
lessons_applied: ["<agent>/Lessons/<file>.md", ...]   # paths that motivated this version; [] for v1 bootstrap
promoted_at: <YYYY-MM-DDTHH:MM>|null  # null until/unless promoted to live
status: candidate|live|archived|deprecated
---
```

Field notes:

- **`version`** — MUST equal the `N` in the filename (`v3.md` → `version: 3`). The filename is canonical; the field is a convenience for tools that read frontmatter without re-parsing the path.
- **`parent_version`** — for `v1` this is always `null`. For any later version it is the integer of the ancestor this version was mutated from. The parent is **not necessarily** `N - 1`; see §7.
- **`live_skill`** — vault-relative path to the live skill file. Lets a tool find "the canonical home" of an archive without inferring it from directory structure.
- **`lineage`** — single-hop human-readable string; long chains are reconstructed by walking `parent_version` repeatedly, not by stuffing them into one field.
- **`score`** — populated by `Skills/skill-staged-eval.md` after evaluation. `null` means "not yet evaluated" — the parent-selection skill treats `null` distinctly from a low score.
- **`lessons_applied`** — paths to lesson files (`<agent>/Lessons/*.md`) that motivated the mutation. Empty array `[]` for the `v1` bootstrap. The meta-improver uses this both for auditability and to avoid re-applying the same lesson twice in a row.
- **`promoted_at`** — ISO-ish `YYYY-MM-DDTHH:MM` local time when this version was written to the live file. `null` while the version is still a candidate or was never promoted.
- **`status`** — see §4.

---

## 4. State machine

A version sits in exactly one of four states:

| Status        | Meaning                                                                                                  |
| ------------- | -------------------------------------------------------------------------------------------------------- |
| `candidate`   | Just written by the meta-improver. Live skill is still the **previous** version. Not yet promoted.       |
| `live`        | This version is currently mirrored into `<agent>/Skills/<skill-name>.md`. At most one version is `live`. |
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

1. **Capture current live.** Read the body of the live file `vault/<agent>/Skills/<skill-name>.md` and its frontmatter, especially its `version` field — call this `M` (the version currently live, where `M = N - 1` in the linear case but can be any prior version if `v<N>` was branched).
2. **Demote the prior live mirror to `archived`.** Locate `vault/<agent>/Skills/_archive/<skill-name>/v<M>.md` and rewrite its frontmatter `status: live` → `status: archived`. (If the archive file does not yet exist because of a bootstrap edge case, write it from the captured live content — see §9.) Do not touch its body.
3. **Overwrite the live file.** Write the candidate's full body to `vault/<agent>/Skills/<skill-name>.md`. Also update the live file's frontmatter to set `version: N`, `updated: <today>`, and refresh `description` if the mutation changed scope. **Do not** add the other version metadata (`parent_version`, `lineage`, `score`, `lessons_applied`, `promoted_at`, `status`) to the live file — those live only in the archive copy. The live file mirrors body + identity, not state-machine bookkeeping.
4. **Write the new archive copy.** Create `vault/<agent>/Skills/_archive/<skill-name>/v<N>.md` containing the candidate's full body PLUS the version-frontmatter (per §3) with `status: live`, `promoted_at: <now>`, and `version: N`. The archive copy is the source of truth for state; the live file is a body mirror plus `version: N`.
5. **Verify integers.** After the write, the archive directory MUST contain exactly one file with `status: live`, and its `version` MUST equal the `version` in the live file's frontmatter. If this invariant fails, the meta-improver MUST roll back its own writes and abort.

The live file's frontmatter is intentionally minimal — `version: N` is the only piece of state it carries. The rest is owned by `_archive/<skill-name>/v<N>.md`.

---

## 6. Rollback

A live version can become bad in two ways:

- **Manual rollback** — the user (or a routine reviewer) requests it explicitly.
- **Automatic rollback** — `Skills/skill-staged-eval.md` re-evaluates the live version on a subsequent run and the score drops below the previous live's score by more than the eval's regression tolerance.

Procedure when rolling back live `v<N>`:

1. **Find the rollback target.** Scan `vault/<agent>/Skills/_archive/<skill-name>/v*.md`, filter to entries with `status: archived` (NEVER `deprecated`) and `score` not null, then pick the one with the **highest score** that is also strictly greater than `v<N>`'s score. If no such version exists (e.g. nothing was scored yet, or `v<N>` was the highest-scoring), abort the rollback and notify the user — silent rollback to an unscored or worse version is forbidden.
2. **Copy body into the live file.** Take the body of the target `v<M>.md` and write it to `vault/<agent>/Skills/<skill-name>.md`. Update the live file's frontmatter: `version: M`, `updated: <today>`. Refresh `description` if the chosen ancestor's description is meaningfully different.
3. **Mark the bad version `deprecated`.** Rewrite `vault/<agent>/Skills/_archive/<skill-name>/v<N>.md`'s frontmatter `status: live` → `status: deprecated`. Append a brief `## Rollback reason` section to its body recording why (one sentence + timestamp). Do not delete the file.
4. **Promote the chosen ancestor back to `live`.** Rewrite `v<M>.md`'s frontmatter `status: archived` → `status: live` and refresh `promoted_at` to the rollback timestamp. The previous `promoted_at` value is preserved in the rollback reason note for audit.
5. **Verify integers** (same invariant as §5 step 5): exactly one `status: live` in the archive, matching the live file's `version`.

Deprecated versions are never re-promoted automatically. If the user wants a deprecated version back, they edit its `status` manually — the meta-improver does not undeprecate.

---

## 7. Branching (open-ended search)

The `parent_version` field is the open-ended-search hook. When the meta-improver writes `v<N>`, the parent it mutated from is **whatever the parent-selection skill returned**, not necessarily `v<N-1>`.

Concrete consequence: if linear promotion produced `v1 → v2 → v3 → v4` and the parent-selector decides `v2` is the most promising base for the next mutation (e.g. because `v3` and `v4` scored worse and the search space wants exploration), then `v5` will have `parent_version: 2` and `lineage: "v2 → v5"`. The integer in the filename is monotonic (5 > 4 > 3 > 2 > 1), but the `parent_version` graph is a tree, not a line.

This is the substrate that makes the loop **open-ended** in the HyperAgents sense — without it, every mutation overwrites the latest, the search collapses to greedy hill-climbing, and a single bad mutation poisons all descendants. The decision of *which* parent to pick lives entirely in `Skills/skill-parent-selection.md`; this file only guarantees that the disk layout supports any choice that skill makes.

---

## 8. Skill name embedding the live version

The live file `vault/<agent>/Skills/<skill-name>.md` carries exactly one piece of versioning state in its own frontmatter:

```yaml
version: <N>
```

This is the version number currently mirrored into the live file. Any tool that needs to find the canonical archive of "what's live right now" reads this number and opens `_archive/<skill-name>/v<N>.md`. The agreement between live `version` and the single `_archive` entry with `status: live` is the system's primary invariant (see §5 step 5 and §6 step 5).

The live file does NOT carry `parent_version`, `lineage`, `score`, `lessons_applied`, `promoted_at`, or `status`. Putting them there would create two sources of truth that drift. The live file is for the runtime; the archive copy is for the state machine.

For skills that have not yet been touched by the meta-improver, the `version` field is absent from the live frontmatter. The first promotion writes it.

---

## 9. First-time conversion (bootstrap)

When the meta-improver decides to mutate a skill that has no `_archive/<skill-name>/` directory yet:

1. **Create the directory.** `mkdir -p vault/<agent>/Skills/_archive/<skill-name>/`.
2. **Snapshot the current live as `v1`.** Copy the current body of `vault/<agent>/Skills/<skill-name>.md` into `vault/<agent>/Skills/_archive/<skill-name>/v1.md`, then prepend the frontmatter described in §3 with these specific values:
   - `version: 1`
   - `parent_version: null`
   - `lineage: "v0 → v1"`
   - `status: archived` (not `live` — `v2` is about to take the live slot, see step 4)
   - `promoted_at: <bootstrap timestamp>` (the timestamp at which this skill first came into existence — use today's date if unknown)
   - `score: null`
   - `lessons_applied: []`
   - `live_skill: <agent>/Skills/<skill-name>.md`
3. **Bump the live file's frontmatter.** Add `version: 1` to the live file's frontmatter if it isn't already there. Do NOT change the body in this step. The live file is now in a consistent v1 state.
4. **Proceed with normal promotion of `v2`.** Run the §5 procedure to write the candidate as `v2`. Because §5 demotes the prior live archive entry from `live → archived`, and `v1` is already `archived` from step 2, no extra demotion is needed — `v2` simply becomes the unique `status: live` entry.

Step 2 deliberately stamps `v1` as `archived` rather than `live` so the post-bootstrap state mirrors a regular post-promotion state without needing a "first time is special" branch elsewhere in the system.

---

## 10. Reading the archive (for parent-selection / audits)

The archive is designed to be read **frontmatter-only** for the common case. Procedure:

1. `ls vault/<agent>/Skills/_archive/<skill-name>/v*.md` to enumerate versions.
2. For each file, read **only the first ~15 lines** — enough to capture the full frontmatter block. Do not read the body unless you actually need the prompt text (e.g. you are about to mutate it).
3. **Filter** by `status != deprecated`. Deprecated versions are kept on disk for audit but are NEVER candidates for parent selection.
4. **Sort** depending on use case:
   - **Chronological** — sort ascending by `version` (the integer). Equivalent to sorting by filename's `v<N>` suffix.
   - **Best-first** — sort descending by `score`, with `score: null` placed at the end (so unevaluated versions don't masquerade as good ones).
   - **Lineage walk** — start from any version and follow `parent_version` repeatedly until `null` is reached. Yields the chain of ancestors. Cycles are impossible because `parent_version < version` is enforced (every parent has a strictly smaller integer).

A typical audit query (best non-deprecated version with a known score) is:

> List `v*.md` where `status in {archived, live, candidate}` and `score is not null`, sort by `score desc`, take 1.

A typical parent-selection query is:

> List `v*.md` where `status in {archived, live}` (NEVER `candidate`, which hasn't been promoted and shouldn't be a base) and `score is not null OR version == 1` (the bootstrap is always a legitimate fallback), then apply the open-ended-search policy from `Skills/skill-parent-selection.md`.

These access patterns are what makes the frontmatter schema in §3 the actual contract — every field there exists because one of the readers below needs it:

- `meta-skill-improver` reads `lessons_applied`, `lineage`, `parent_version`, and writes new versions.
- `skill-staged-eval` reads any version's body, populates `score`, and may trigger rollback via §6.
- `skill-parent-selection` reads `version`, `parent_version`, `score`, `status` to decide what to mutate next.

Any change to the schema in §3 MUST update all three consumer skills in the same commit. Diverging the schema silently is the failure mode this file is here to prevent.
