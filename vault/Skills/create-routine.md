---
title: Create Routine
description: Author a new single-prompt scheduled task (vault/<agent>/Routines/*.md with type=routine). Use whenever creating or modifying a routine. For multi-step DAG workflows, use create-pipeline instead.
type: skill
created: 2026-05-02
updated: 2026-05-02
tags: [skill, routine, infrastructure, authoring]
---

# Create Routine

A **routine** is a single Claude CLI invocation that runs on a schedule. One prompt in, one output out. Output goes to Telegram unless the routine returns the literal string `NO_REPLY`, in which case it runs silently.

This skill is shared infrastructure — it lives at `vault/Skills/` and is invoked identically by every agent. It assumes the routine file will live at `vault/<owning-agent>/Routines/<name>.md` and that the file's location on disk is the authoritative source of the owning agent (no `agent:` frontmatter field needed in v3.5+).

## 1. When to use this skill

Use when the user says any of:

- "Create a routine to do X every morning"
- "Schedule a recurring check for Y"
- "Run Z at 09:00 every day"
- "Make a daily reminder that…"
- `/routine` (interactive Telegram flow)
- "Disable / re-enable / change the schedule of routine X"

If the user's request is for a multi-step DAG (collect → analyze → publish, with intermediate validation, branching, or different models per step), STOP and use `[[Skills/create-pipeline]]` instead. See the fork below.

## 2. Routine vs pipeline — the fork

A routine fits when ALL of these are true:

- The work is **one prompt** — read X, do Y, output Z.
- No **intermediate validation** of partial output is needed.
- No **structured handoff** to a downstream step.
- The whole job comfortably fits in **one Claude CLI invocation** (rough rule: under 5 minutes, under one model's context budget).
- A **single model choice** is appropriate for the whole job.

Switch to a **pipeline** when ANY of these are true:

- The work has **multiple distinct stages** (e.g. fetch → parse → summarize → publish).
- Different stages would benefit from **different models** (haiku to scrape, opus to analyze).
- A **cheap screening step** could decide whether expensive downstream work runs at all (early-exit via `NO_REPLY`).
- Stages are **independent** and could run in **parallel**.
- The output of one stage is the **structured input** of another (and you want the harness to enforce that contract).
- You want **per-step retry**, **per-step notification**, or **per-step failure isolation**.

**When in doubt, prefer the simpler routine.** Promote to a pipeline only when the routine is genuinely outgrowing the single-prompt shape. A routine you wish was a pipeline is easier to convert later than a pipeline you wish was a routine.

| User's goal | Pick |
|-------------|------|
| "Remind me to drink water at 10am" | Routine |
| "Daily crypto market report from 5 sources, pick the best 3 stories, write a summary" | Pipeline |
| "Check if there are new commits in repo X since yesterday and tell me" | Routine |
| "Compare prices across 5 sites and generate a comparative report" | Pipeline |
| "Journal backup every Sunday" | Routine |
| "Weekly newsletter — research, draft, review, send" | Pipeline |
| "Read yesterday's journal and ask me 3 reflection questions" | Routine |
| "Scout headlines, score them, write the ones that score >7, publish to Notion" | Pipeline |

## 3. Frontmatter — what each field does

The canonical reference is `.claude/rules/vault-runtime-features.md` (under "Routines → Frontmatter fields"). Read it for the complete table including types, defaults, and edge cases. The summary below is just to anchor the discussion — when in doubt, the rules file wins.

| Field | Required | Default | Notes |
|-------|----------|---------|-------|
| `title` | yes | — | Short descriptive title. |
| `description` | yes | — | One-sentence keyword-rich description. Used by scanners and indexers. |
| `type` | yes | — | Must be `routine` (use `pipeline` for multi-step). |
| `created` / `updated` | yes | — | YYYY-MM-DD. Update `updated` whenever the file changes. |
| `tags` | yes | — | Always include `routine`; add category tags. |
| `schedule.times` | one of times/interval | — | List of `HH:MM` (24h, BRT). |
| `schedule.interval` | one of times/interval | — | E.g. `30m`, `4h`, `3d`, `2w`. **Mutually exclusive with `times`.** |
| `schedule.days` | no | `["*"]` | Weekday filter or `["*"]` for every day. |
| `schedule.monthdays` | no | — | E.g. `[1, 15]` to filter for specific days of month. |
| `schedule.until` | no | — | YYYY-MM-DD end date. |
| `model` | no | `sonnet` | `opus`, `sonnet`, `haiku`, `glm-4.7`, `glm-5.1`, `gpt-5-codex`. |
| `enabled` | no | `true` | Set `false` to disable without deleting the file. |
| `context` | no | `full` | `full` injects vault SYSTEM_PROMPT; `minimal` skips it. See section 5. |
| `effort` | no | (CLI default) | `low` / `medium` / `high` / `max` — reasoning effort. |
| `voice` | no | `false` | Also send response as TTS audio on Telegram. |
| `notify` | no | `final` | Routines really only use `final` — pipeline-specific values (`all`, `summary`, `none`) don't apply. |

**Do NOT add an `agent:` frontmatter field.** Folder location is the source of truth: `vault/<id>/Routines/foo.md` implies `agent=<id>`. The legacy `agent:` field is still parsed for backcompat, but if it disagrees with the folder, the folder wins and the bot logs a warning.

## 4. Schedule patterns

Pick **either** `times` **or** `interval`, never both.

**Clock-based (`times` + `days`):**

```yaml
schedule:
  times: ["09:00", "18:00"]
  days: ["mon", "tue", "wed", "thu", "fri"]
```

Runs at 09:00 and 18:00 on weekdays.

**Interval-based:**

```yaml
schedule:
  interval: "30m"
  days: ["*"]
```

Runs every 30 minutes, every day. Allowed units: `m` (minutes), `h` (hours), `d` (days), `w` (weeks).

**Day-of-month filter (works with either mode):**

```yaml
schedule:
  times: ["06:30"]
  days: ["*"]
  monthdays: [1]
```

Runs at 06:30 on the 1st of every month. (Used by the `skill-audit` routine for monthly audits.)

**Bounded routine:**

```yaml
schedule:
  times: ["20:00"]
  days: ["*"]
  until: "2026-12-31"
```

Auto-disables itself after the `until` date.

**Common pitfall:** specifying both `times` and `interval` — the runtime picks one and silently ignores the other. Don't.

## 5. Context modes — `full` vs `minimal`

`context` controls whether Claude receives the bot's vault `SYSTEM_PROMPT` (which instructs it to scan Journal/Tooling/Notes/etc.).

- **`context: full`** (default) — Claude gets the SYSTEM_PROMPT and behaves like an interactive session: it can read the Journal, consult `Tooling.md`, follow agent personality from `<agent>/CLAUDE.md`, and so on. Use when the routine genuinely needs the agent's context.
- **`context: minimal`** — SYSTEM_PROMPT is omitted. Claude still reads the standard CLAUDE.md hierarchy (vault → agent), but no vault-scanning instructions are injected. **Faster, cheaper, more deterministic** — choose this whenever the routine is self-contained.

**Active Memory and skill hints DO NOT apply to routines.** Both helpers fire only on interactive turns where the bot owns the system prompt. Routines pass `system_prompt=None`-equivalent paths and are excluded by design. So:

- If your routine needs vault context to do its job → `context: full`.
- If your routine is standalone (calls a script, fetches a URL, formats fixed data) → `context: minimal`. This is the right default for the majority of routines.

**Rule of thumb:** start with `minimal`, escalate to `full` only when you find yourself wanting Claude to "know what's in the vault" without explicit instructions.

## 6. The `NO_REPLY` pattern

If a routine's output is exactly the literal string `NO_REPLY`, the bot sends nothing to Telegram. The routine ran silently. This is THE pattern for:

- **Conditional notifications:** "If something interesting happened, send a Telegram message; otherwise stay quiet."
- **Background maintenance:** "Run the cleanup; only notify on failure."
- **Self-managed Telegram delivery:** "Build a custom Telegram message with inline buttons via `urllib`, send it yourself, then return NO_REPLY so the harness doesn't echo your output."

Detection is tolerant — the bot accepts `NO_REPLY`, `NO REPLY`, `NOREPLY`, `no_reply`, and trailing-punctuation variants (`NO_REPLY.`, `NO_REPLY!`). Prefer the canonical `NO_REPLY` for consistency.

**Critical rule for silent routines:** the prompt MUST tell Claude to output `NO_REPLY` **and nothing else** — no preamble, no confirmation, no explanation. Any stray text outside the silence sentinel will be sent to Telegram. Be explicit:

> "When finished, respond with exactly the string `NO_REPLY` and nothing else — no summary, no confirmation. Any extra text will be sent to Telegram unnecessarily."

## 7. Prompt-writing guidelines

A routine's prompt is a single Claude CLI invocation. Treat it as production code, not a chat message.

1. **Be specific about inputs.** Don't write "Check the journal." Write "Read `Journal/YYYY-MM-DD.md` for today's date in BRT and look for entries tagged X." Spell out file paths, time windows, and data sources.
2. **Define the output format up front.** "Output as a Markdown bullet list with title + URL." Or "Output as JSON: `{stories: [...]}`." If a downstream tool parses the output, give an `## Example Output` section at the end of the prompt body so Claude has a concrete target.
3. **Define the silent case.** If the routine can have nothing to report, say so explicitly: "If no new commits, output exactly `NO_REPLY` and nothing else."
4. **Define the failure case.** "If the API returns an error, output 'API unavailable — will retry next run.'" Don't let Claude fall through to "I tried but couldn't…"
5. **Reference skills for procedures.** If the routine involves a multi-step procedure that exists elsewhere, link the skill: "Follow `Skills/X.md` to extract knowledge from the latest session." Don't inline a long procedure in the prompt — keep the routine prompt focused.
6. **Time-zone awareness.** Routines run in BRT (the bot's timezone). If you compare to external timestamps (UTC APIs, GitHub events), say so explicitly: "Today's date in BRT is YYYY-MM-DD. Convert UTC timestamps to BRT before comparing."
7. **Idempotency.** If the routine retries (e.g. crash, `/run` re-trigger), will it duplicate work? When in doubt, ask Claude to check for an idempotency marker before writing: "Before appending to the Journal, check whether an entry already exists for HH:MM. If so, skip."

## 8. Path conventions inside the cwd

The routine runs with **cwd at `vault/<owning-agent>/`**. So all relative paths in the prompt resolve from there:

| Path in prompt | Resolves to |
|----------------|-------------|
| `Skills/X.md` | `vault/<agent>/Skills/X.md` (agent's own skill) |
| `Journal/2026-05-02.md` | `vault/<agent>/Journal/2026-05-02.md` |
| `Notes/foo.md` | `vault/<agent>/Notes/foo.md` |
| `data/...` | `vault/<agent>/.workspace/data/<run-id>/...` (per-run scratch dir, when present) |
| `../Skills/Y.md` | `vault/Skills/Y.md` (shared infrastructure skill) |
| `../Tooling.md` | `vault/Tooling.md` |
| `~/claude-bot/scripts/...` | repo scripts (use absolute paths or `~`) |

For shared infra skills, prefer the path-qualified wikilink in narrative text (`[[Skills/extract-knowledge]]`) and a concrete `../Skills/extract-knowledge.md` for file reads.

## 9. Body — what goes in the prompt body

The body of the routine file has TWO required structural elements before the prompt itself:

1. **First line:** the parent-index wikilink, **path-qualified**:
   ```markdown
   [[<agent>/Routines/agent-routines|Routines]]
   ```
   This is one of the rare exceptions to the "skills don't link to parent" rule — routines DO link up because they are not skills, they are leaves of `<agent>/Routines/`. The path qualifier is required because every agent has its own `agent-routines.md` file (bare `[[agent-routines]]` is ambiguous).

2. **The prompt itself**, written in clear declarative English.

Optional but encouraged:

3. An **`## Example Output`** section at the bottom showing exactly what a successful run looks like. Especially valuable when the output is structured (Markdown table, JSON, fixed Telegram message format).

## 10. Example: a complete simple routine

`vault/main/Routines/morning-water-reminder.md`:

```markdown
---
title: Morning Water Reminder
description: Sends a one-line reminder at 09:00 to drink water before the first coffee. No data sources, no conditions.
type: routine
created: 2026-05-02
updated: 2026-05-02
tags: [routine, reminder, health]
schedule:
  times: ["09:00"]
  days: ["*"]
model: haiku
enabled: true
context: minimal
---

[[main/Routines/agent-routines|Routines]]

Send a short, friendly reminder to drink a glass of water before the first coffee. One sentence, no emoji clutter (one is fine).

## Example Output

Bom dia — antes do café, um copo d'água. Hidrata.
```

Note: `haiku` (cheap and fast for a one-liner), `context: minimal` (no vault knowledge needed), no `until` (open-ended).

## 11. Example: a routine with `NO_REPLY` conditional

`vault/main/Routines/repo-commits-check.md`:

```markdown
---
title: Repo Commits Check
description: Checks every 4 hours whether claude-bot's main has new commits since last poll. If so, summarizes them in 3 bullets. If not, returns NO_REPLY silently.
type: routine
created: 2026-05-02
updated: 2026-05-02
tags: [routine, maintenance, repo]
schedule:
  interval: "4h"
  days: ["*"]
model: haiku
enabled: true
context: minimal
---

[[main/Routines/agent-routines|Routines]]

Check the claude-bot repo for new commits on `origin/main` since the last fetch.

```bash
cd ~/claude-bot && git fetch origin main --quiet 2>/dev/null && git rev-list HEAD..origin/main --count
```

If the count is `0`, output exactly `NO_REPLY` and nothing else — no preamble, no confirmation. Any other text will be sent to Telegram unnecessarily.

If the count is greater than 0, list the new commits:

```bash
cd ~/claude-bot && git log HEAD..origin/main --oneline
```

Then output a Telegram-ready summary in this format:

## Example Output

When commits found:

```
*claude-bot:* 3 commits atrás
- dc3ff64 feat: dynamic shell substitution
- 6d009b6 chore: add Claude Code hooks
- 12ea244 fix: z.AI proxy absorbs 429s
```

When nothing new:

```
NO_REPLY
```
```

## 12. Common mistakes

- **Using a routine when the work is really a pipeline.** Symptom: the prompt grows to 200+ lines with multiple "Step 1 / Step 2 / Step 3" sections, intermediate validation, conditional branching across stages. Convert to a pipeline.
- **Forgetting `schedule:`.** A routine without a schedule never runs. The bot will load the file but the scheduler will skip it.
- **Specifying both `schedule.times` and `schedule.interval`.** Mutually exclusive — pick one.
- **Setting `context: full` when it isn't needed.** Wastes tokens and slows the run. Default to `minimal` and escalate only when the routine clearly needs vault context.
- **Letting silent routines leak text.** If you intend a silent run, the prompt MUST say "output exactly `NO_REPLY` and nothing else — no summary, no confirmation." Otherwise Claude will helpfully add "All clean! ✓" and that text goes to Telegram.
- **Adding an `agent:` frontmatter field.** Drop it. Folder location is the source of truth in v3.5+. The bot logs a warning if `agent:` disagrees with the folder.
- **Bare parent wikilink (`[[Routines]]` or `[[agent-routines]]`).** Required form is path-qualified: `[[<agent>/Routines/agent-routines|Routines]]`. Bare links collide because every agent has its own index file.
- **Hardcoding Telegram chat IDs or bot tokens.** Read them from `~/claude-bot/.env` at runtime (see the `update-check` routine for the canonical pattern). Or use `scripts/telegram_notify.py "msg"` which auto-resolves the agent's chat/thread from frontmatter.
- **Assuming Active Memory or skill hints will fire.** They won't — those are interactive-only. Routines must instruct themselves to read the vault explicitly when they need to.
- **No fallback for missing data.** "If the API fails, …" — always define this branch. A routine that silently outputs nothing on failure is indistinguishable from a healthy `NO_REPLY` run.
- **Forgetting to update the day's Journal.** When you create a routine via this skill, append a one-line note to the day's Journal. The bot's `vault/<agent>/CLAUDE.md` instructs agents to log creation events; routines are no exception.

## 13. Checklist before declaring the routine complete

- [ ] File saved at `vault/<owning-agent>/Routines/<kebab-case-name>.md`.
- [ ] Frontmatter has `type: routine`, `title`, `description`, `created`, `updated`, `tags`, `schedule`, `model`, `enabled`.
- [ ] `schedule` has either `times` or `interval` (not both).
- [ ] `days` defaults to `["*"]` if not specified — but explicit is better.
- [ ] `context` chosen consciously: `minimal` for self-contained, `full` only if vault context is needed.
- [ ] First body line is `[[<agent>/Routines/agent-routines|Routines]]` — path-qualified.
- [ ] Prompt specifies inputs, output format, silent case (if any), failure case.
- [ ] If output is structured: `## Example Output` section at the bottom.
- [ ] If silent: prompt explicitly says "output `NO_REPLY` and nothing else."
- [ ] No `agent:` frontmatter field (folder is the source of truth).
- [ ] No bare parent wikilink — always path-qualified.
- [ ] No hardcoded credentials — read from `~/claude-bot/.env` or use `scripts/telegram_notify.py`.
- [ ] One-line entry appended to the day's Journal noting the new routine.
- [ ] (Optional) Manually run `/run <routine-name>` once on Telegram to validate end-to-end before letting the schedule fire it.

The folder's `agent-routines.md` index will pick up the new file automatically on the next `vault-indexes-update` run (daily) or via manual `/indexes`. You don't need to edit the index by hand.
