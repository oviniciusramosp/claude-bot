---
title: Create Routine
description: Skill for creating scheduled routines. Proactively analyzes whether the user's use case would work better as a parallel pipeline and triages accordingly.
type: skill
created: 2026-04-07
updated: 2026-04-16
trigger: "when the user wants to create a new routine, schedule a recurring task, set up a scheduled job, or use /routine"
tags: [skill, routine, automation, create]
---

# Create Routine

### Step 0 — Triage: simple routine or pipeline?

BEFORE creating anything, analyze the user's goal to determine whether it would be better as a simple routine or as a multi-agent pipeline.

**Signals that it should be a pipeline (not a routine):**

- The goal involves **multiple distinct steps** (collect → analyze → write → publish)
- Needs to fetch data from **3+ independent sources** (APIs, websites, databases)
- Involves verbs like "collect and then analyze", "fetch from multiple sources", "produce a report"
- Has a final **publication step** (Notion, Telegram, email, webhook)
- Intermediate steps could use **different models** (haiku for collection, opus for analysis)
- The whole process would take **more than 5 minutes** with a single agent
- Parts of the work are **independent of each other** and could run in parallel
- **A cheap screening step can decide whether expensive downstream work should run at all** — pipelines support early-exit via `NO_REPLY` (a haiku gate that finds nothing causes the opus/sonnet steps behind it to auto-skip, saving real tokens). See `Skills/create-pipeline.md` Rule 6.

**If 2+ pipeline signals are detected:**

Proactively suggest to the user:

> "Based on what you described, this would work better as a **pipeline** instead of a simple routine. Pipelines allow:
> - Breaking into X parallel steps (faster collection)
> - Using different models per step (haiku for collection, opus for analysis)
> - Automatic retry per step if a source fails
>
> Should I create it as a pipeline? Or do you prefer a simple routine?"

If the user accepts → read and follow the `Skills/create-pipeline.md` skill for the rest of the flow.
If they prefer a simple routine → continue with the steps below.

**Triage examples:**

| User's goal | Recommendation | Reason |
|-------------|----------------|--------|
| "Remind me to drink water at 10am" | Simple routine | Single task, no steps |
| "Daily crypto market report" | Pipeline | Collection + analysis + writing + publishing |
| "Summary of my emails every morning" | Simple routine | One task, one source |
| "Compare prices across 5 sites and generate a report" | Pipeline | 5 parallel sources + analysis |
| "Journal backup every Sunday" | Simple routine | One mechanical task |
| "Weekly newsletter with research and writing" | Pipeline | Research + writing + review + send |

### Step 1 — Ask for the goal

What should the routine do? Ask for a clear description of the prompt.

#### Prompt engineering guidance

Help the user formulate an effective prompt. If the provided prompt is vague, suggest improvements before proceeding.

**Good prompts for routines:**

| Example | Why it works |
|---------|-------------|
| "List the top 5 Hacker News topics with links. Format: bullet list with title + URL. If the API fails, respond 'HN unavailable — will retry next run'." | Clear output format, fallback instruction, defined scope |
| "Check if there are new commits in repo X since yesterday. If so, summarize the changes in 3 bullets. If not, respond NO_REPLY." | Explicit conditional, uses NO_REPLY for silence, clear time scope |
| "Read yesterday's journal and generate 3 reflection questions based on the decisions made. Format: numbered list." | Specific data source, structured output, defined quantity |

**Problematic prompts (and how to improve them):**

| Bad prompt | Problem | Improved version |
|------------|---------|-----------------|
| "Analyze the crypto market" | Vague — which aspect? What output? | "List the top 5 cryptos by market cap with 24h change. Format: markdown table." |
| "Update me on the news" | No source, no format, no scope | "Summarize the 3 most relevant tech news from TechCrunch today. Format: title + 1 sentence each." |
| "Do a backup" | Backup of what? To where? | "Copy the content of Journal/YYYY-MM-DD.md to Notes/backups/journal-YYYY-MM-DD.md" |

**Good routine prompt checklist:**
- [ ] Clear scope (what to do, from where, up to what)
- [ ] Defined output format (bullets, table, plain text)
- [ ] Fallback instruction (what to do if something fails)
- [ ] Quantity/limit when applicable (top 5, last 3 days)

**Note on `NO_REPLY`:**
- In a **simple routine**, `NO_REPLY` makes the bot send nothing to Telegram — the routine completes silently. Use it when there's nothing worth reporting that run.
- In a **pipeline**, `NO_REPLY` ALSO triggers early-exit: every downstream step that depends on a gate returning `NO_REPLY` is auto-skipped, saving tokens on expensive models. If the user's use case involves "check X and only analyze if something changed", that's a pipeline signal — suggest conversion.
- **Detection is tolerant.** The bot accepts `NO_REPLY`, `NO REPLY`, `NOREPLY`, `no_reply`, and variants with trailing punctuation (`NO_REPLY.`, `NO_REPLY!`). Any of these forms in the prompt are equivalent, but prefer the canonical `NO_REPLY` for consistency.

#### When to add an `## Example Output` section

If the routine produces structured or formatted output (Telegram message, JSON, markdown report, table), include an `## Example Output` section at the end of the prompt body. Claude reads it at execution time and follows the format automatically — no extra instructions needed.

**Add it when:**
- The output is a Telegram message with specific formatting (bold, emojis, bullet structure)
- The output is structured data another system will consume (JSON, YAML, key-value)
- The output is a report or summary with a specific section layout
- The format has been a source of inconsistency in past runs

**Skip it when:**
- The routine uses `NO_REPLY` (no output to format)
- The prompt is a simple instruction with obvious output ("copy file X to Y")
- The output format is genuinely open-ended ("reflect on today's journal")

**Example — routine prompt with output guidance:**

```
List the top 5 Hacker News topics with links. If the API fails, respond "HN unavailable — will retry next run."

## Example Output

- **Show HN: Building a Rust compiler in 30 days** — https://news.ycombinator.com/item?id=12345
- **PostgreSQL 18 released with native JSON columns** — https://news.ycombinator.com/item?id=12346
- **The unreasonable effectiveness of plain text** — https://news.ycombinator.com/item?id=12347
- **Ask HN: How do you manage dotfiles?** — https://news.ycombinator.com/item?id=12348
- **YC W26 batch announced** — https://news.ycombinator.com/item?id=12349
```

### Step 2 — Ask for schedules

At what times should it run? Format HH:MM (24h). Can be multiple: "09:00 and 18:00".

### Step 3 — Ask for days of the week

On which days? Options:
- Weekdays (mon, tue, wed, thu, fri)
- Every day (*)
- Specific days (e.g.: mon, wed, fri)
- Weekend (sat, sun)

### Step 4 — Ask for model

Which model to use? Suggest based on the task type:

| Task type | Recommended model | Reason |
|-----------|------------------|--------|
| Reminder, notification, backup, simple check | `haiku` | Fast and cheap — no deep reasoning needed |
| Summary, formatting, data collection, listing | `sonnet` | Balance between quality and cost — safe default |
| Deep analysis, creative writing, complex decision, multi-source synthesis | `opus` | Best reasoning and output quality |

If the user doesn't know, use `sonnet` as default.

### Step 4.5 — Optional fields

Ask if the user needs any of these additional fields:

**`context: minimal`** — Skips the vault system prompt (Journal, Tooling, etc.). The routine runs only with the CLAUDE.md files in the hierarchy. Use when:
- The routine does NOT need to read the vault (e.g.: fetching external data, generating fixed reminders)
- Token savings and speed are a priority
- The prompt is self-contained and does not depend on vault context

**`voice: true`** — In addition to the text message, sends the response as TTS audio on Telegram. Use when:
- The user consumes routines on the go (e.g.: morning briefing, news summary)
- The content is short and makes sense to listen to (not tables or long lists)

**Agent ownership (folder is the source of truth).** In v3.5, a routine's owning agent is determined by **where the file lives on disk**, NOT by a frontmatter field. If the user wants the routine to belong to agent `crypto-bro`, save it at `vault/crypto-bro/Routines/<name>.md` — no `agent:` field needed. The bot will run it with `crypto-bro`'s cwd, skills, journal, and Telegram chat/thread automatically. If the user doesn't mention an owning agent, save to `vault/main/Routines/<name>.md` (the default). The legacy `agent: <id>` frontmatter field is still accepted for backcompat, but if it disagrees with the folder, the folder wins and a warning is logged.

If no optional fields are needed, move forward without adding them.

### Step 5 — Ask for end date

Until when should the routine run? Format YYYY-MM-DD. Optional (no limit if omitted).

### Step 6 — Generate file name

Convert the goal to kebab-case for the filename. E.g.: "morning crypto report" → `morning-crypto-report.md`

### Step 7 — Create the file

Generate at `vault/<owning-agent>/Routines/{name}.md` (e.g., `vault/main/Routines/morning-digest.md` for the Main agent, or `vault/crypto-bro/Routines/crypto-alert.md` for crypto-bro). The folder you pick determines the owning agent — never use the old flat `vault/Routines/` path, which doesn't exist in v3.5.

Use the following format:

```yaml
---
title: {descriptive title}
description: {short sentence about what the routine does and when it runs}
type: routine
created: {YYYY-MM-DD}
updated: {YYYY-MM-DD}
tags: [routine, {relevant categories}]
schedule:
  times: ["{HH:MM}", "{HH:MM}"]
  days: [{days}]
  until: "{YYYY-MM-DD}"
model: {model}
enabled: true
---

{Full prompt to be sent to Claude Code}

{If the output format matters, add:}

## Example Output

{A concrete example of what the output should look like}
```

**DO NOT add a `[[Routines]]` wikilink at the top of the body.** In v3.5 the graph is parent → child only — the `agent-routines.md` index lists its children via an auto-regenerated marker block, so leaf files never link up. Adding a parent wikilink would create a duplicate edge and fail the vault lint.

### Step 8 — Let the index regenerate itself

The owning agent's `vault/<agent>/Routines/agent-routines.md` contains a `vault-query:start` marker block scoped to its own folder. The next run of `scripts/vault_indexes.py` (or the daily `vault-indexes-update` routine, or a manual `/indexes` on Telegram) will automatically pick up the new file and render it inside the marker block. You do NOT need to edit the index by hand.

### Step 9 — Record in the Journal

Append to the day's journal:
```
## HH:MM — New routine created

- Created routine {routine-name}
- Times: {times}
- Days: {days}
- Model: {model}

---
```

### Step 10 — Confirm

Inform the user that the routine was created and when the next execution will be.

---

## Notes

- The routine prompt can reference skills by name
- The prompt can include instructions to consult Tooling and .env
- Routines can be disabled by changing `enabled: false` in the frontmatter
- The bot's scheduler checks routines every 60 seconds
- Routines that fail appear with a red icon in the menu bar
- **If the user wants a routine with multiple steps/agents/steps, use the `Skills/create-pipeline.md` skill instead of this one.** Pipelines have `type: pipeline` and allow orchestrating multiple sub-agents with dependencies, parallelism, and different models per step.
- **Telegram notifications:** To send additional Telegram messages from a routine, call the script via `subprocess.run(["python3", os.environ["TELEGRAM_NOTIFY"], "--text", text])`. The harness injects `TELEGRAM_NOTIFY` (script path), `AGENT_ID`, `AGENT_CHAT_ID`, and `AGENT_THREAD_ID` — no hardcoded paths or IDs needed. See `Tooling.md`.
