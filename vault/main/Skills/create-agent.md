---
title: Create Agent
description: Consultative skill for creating specialized agents. Helps decide whether a case requires a dedicated agent or if the Main Agent is sufficient. Generates the v3.5 flat per-agent structure.
type: skill
created: 2026-04-07
updated: 2026-04-16
trigger: "when the user wants to create a new agent, wants a specialized assistant, needs a bot for something, or uses /agent new"
tags: [skill, agent, automation, create]
---

# Create Agent

### Step 0 — Triage: dedicated agent or Main Agent?

BEFORE creating anything, analyze whether the user truly needs a dedicated agent or whether the Main Agent with the right prompt would do the job.

**Signs that a dedicated agent MAKES sense:**

- The case requires a **distinct personality** (tone, style, own voice)
- The agent will have an **isolated workspace** with specific files
- Usage will be **recurring** (not a one-off task)
- Needs its **own Journal** to maintain a history separate from Main
- There are **scheduled routines** that should run under this persona
- The domain is **specialized** (crypto, fitness, creative writing) and benefits from permanent instructions

**Signs that the Main Agent is sufficient:**

- One-off or short-lived task
- No need for a special personality or tone
- No need for a separate workspace
- The instructions fit in a normal session prompt
- The user just wants output, not a recurring "entity"

**If you detect that Main is enough:**

Proactively suggest to the user:

> "From what you described, this doesn't need a dedicated agent. The Main Agent can handle it with a direct prompt. Dedicated agents are better when you want a specific personality, isolated workspace, and recurring use.
>
> I can help formulate the right prompt for Main. Or if you'd prefer to create the agent anyway, I'll proceed."

If the user agrees → formulate the prompt and close.
If they prefer to create the agent → continue with the steps below.

**Triage examples:**

| User's goal | Recommendation | Reason |
|-------------|---------------|--------|
| "I want a crypto assistant that tracks my portfolio every day" | Dedicated agent | Recurring, specific domain, needs own Journal |
| "Help me write a formal email" | Main Agent | One-off task, no persona needed |
| "I want a bot with a coach personality that keeps me accountable for habits" | Dedicated agent | Distinct personality, recurring use, needs to maintain history |
| "Analyze this CSV and give me insights" | Main Agent | Single task, no special personality |
| "I need a technical text reviewer that follows my style guide" | Dedicated agent | Permanent instructions, defined personality, recurring use |
| "Summarize this article for me" | Main Agent | One-off task, any model handles it |

### Step 1 — Ask for the name

Human-readable name for the agent. E.g.: "CryptoAnalyst", "FitnessCoach", "TechWriter".

### Step 2 — Define the personality

Tone of voice, communication style, character traits.

#### Personality heuristics

Help the user define a personality that truly differentiates the agent. If the provided personality is generic, suggest improvements before proceeding.

**Good personalities:**

| Example | Why it works |
|---------|-------------|
| "Direct and quantitative technical analyst, prefers data over opinion. Uses bullet points, avoids vague jargon." | Clear tone, defined output style, explicit preferences |
| "Firm but empathetic motivational coach. Asks questions before giving advice. Celebrates progress, confronts excuses." | Nuanced personality, conditional behavior |
| "Creative writer with subtle humor. Writes in short paragraphs, uses unexpected analogies, avoids corporate clichés." | Defined literary style, explicit anti-patterns |

**Problematic personalities (and how to improve them):**

| Bad personality | Problem | Improved version |
|----------------|---------|-----------------|
| "Be helpful and informative" | Generic — every model already does that | "Expert in X who prioritizes clarity over completeness. Answers with concrete examples before theory." |
| "Be friendly" | Vague, indistinguishable from anything | "Casual and humorous tone, uses everyday analogies. Treats the user as a colleague, not a client." |
| "Answer well" | Not a personality | "Technical formalist. Structures responses with headers. Always cites a source or reason for each statement." |

**Good personality checklist:**
- [ ] Defined tone of voice (formal, casual, technical, humorous?)
- [ ] Clear output style (bullets, paragraphs, tables, conversational?)
- [ ] At least one anti-pattern (what the agent does NOT do)
- [ ] Behavior that the Main Agent would not naturally have

### Step 3 — Ask for the description

Short sentence that goes in the frontmatter `description`. Should explain what the agent does in one line.

### Step 4 — Ask for specializations

Agent's focus areas. These will appear as a list under `## Specializations` in CLAUDE.md and as tags in the frontmatter.

### Step 5 — Choose the model

#### Model guidance by agent type

Don't just ask — recommend based on the intended use:

| Agent type | Recommended model | Reason |
|-----------|------------------|--------|
| Data collection, monitoring, simple alerts | `haiku` | Fast and cheap, ideal for mechanical tasks |
| Most agents (analysis, writing, general assistance) | `sonnet` | Balance between quality and speed |
| Deep analysis, creative writing, complex reasoning | `opus` | Best reasoning, more expensive and slower |
| Agent with frequent routines (multiple times per day) | `haiku` or `sonnet` | Costs accumulate fast with opus |
| Agent for critical decisions (financial, strategy) | `opus` | The extra cost is worth the quality |

Default: `sonnet`. Suggest a change if the case calls for it.

### Step 6 — Ask for the icon

Emoji that represents the agent. Suggest options if the user has no preference.

### Step 7 — Ask for the color

Pick one of the supported palette names for the Obsidian graph-view color group. The bot syncs `.obsidian/graph.json` automatically on `/indexes` and on startup, so the agent's subtree will visually light up in the selected color. Available names:

- `grey` — neutral default, used for the Main agent
- `red`, `orange`, `yellow`, `green`, `teal`, `blue`, `purple` — vivid picks

Suggest a color that doesn't clash with already-in-use agents. Ask the user, default to `grey` if no preference.

### Step 8 — Generate ID

kebab-case of the name. E.g.: "CryptoAnalyst" -> `crypto-analyst`

### Step 9 — Create the agent directory at `vault/{id}/`

v3.5 flat layout — every agent lives directly under the vault root with the following structure:

```
vault/{id}/
  agent-{id}.md                    # hub: frontmatter (metadata) + body wikilinks DOWN to sub-indexes
  CLAUDE.md                        # personality/instructions (read by Claude CLI, not a graph node)
  Skills/agent-skills.md           # auto-listing index for this agent's skills
  Routines/agent-routines.md       # dual marker (pipelines + routines)
  Journal/agent-journal.md         # auto-listing index for daily entries
  Reactions/agent-reactions.md
  Lessons/agent-lessons.md
  Notes/agent-notes.md
  Journal/.activity/               # runtime — bot's activity log (dotfile, hidden by Obsidian)
  .workspace/                      # runtime — pipeline data (dotfile, hidden by Obsidian)
```

**Hub filename.** The hub file is `agent-<id>.md` (NOT `agent-info.md` or `agent.md`). Using the id in the name gives every agent hub a unique basename vault-wide — which matters because Obsidian resolves bare wikilinks by shortest basename match, so two files named `agent-info.md` (one per agent) would collide.

**Sub-index naming.** Each per-folder index file uses the `agent-<lowername>.md` prefix (`agent-skills.md`, `agent-routines.md`, etc.) so the LLM and the bot's loaders know it's a graph hub, not regular knowledge content. The bot's `SUB_INDEX_FILENAMES_SET` constant skips these filenames when iterating actual content files.

**`agent-{id}.md`** — frontmatter holds metadata, body lists the sub-indexes via path-qualified wikilinks (parent → child convention):
```yaml
---
title: {name}
description: {short description}
type: agent
created: {YYYY-MM-DD}
updated: {YYYY-MM-DD}
tags: [agent, hub]
name: {name}
model: {model}
icon: "{emoji}"
color: {palette-name}
default: false
personality: {personality in one sentence}
# Optional — Telegram routing. Let the agent auto-activate when messages
# arrive on a specific chat/thread. Omit both for a plain agent.
chat_id: "-100XXXXXXXXXX"    # Telegram group/channel ID (optional)
thread_id: 123                # Telegram topic ID inside the group (optional)
---

- [[{id}/Skills/agent-skills|Skills]]
- [[{id}/Routines/agent-routines|Routines]]
- [[{id}/Journal/agent-journal|Journal]]
- [[{id}/Reactions/agent-reactions|Reactions]]
- [[{id}/Lessons/agent-lessons|Lessons]]
- [[{id}/Notes/agent-notes|Notes]]
- [[{id}/CLAUDE|CLAUDE]]
```

**Telegram isolation (`chat_id` + `thread_id`).** When both fields are set, the bot's `_agent_chat_map` routes any message arriving on that specific (chat, thread) pair to this agent's session. The routing is exact-match: `(chat_id, thread_id)` tuples. An agent with only `chat_id` set routes based on chat; an agent with neither routes via manual `/agent <name>` switching. Two agents cannot share the same `(chat_id, thread_id)` pair — the last-loaded wins. Use this to give each agent its own Telegram topic/group and keep conversations strictly separate.

**CLAUDE.md** — instructions for Claude Code (NO frontmatter, NO wikilinks):
```markdown
# {name} {emoji}

## Personality
{detailed description of tone and style}

## Instructions
- Record conversations in own Journal: `Journal/YYYY-MM-DD.md`
- IMPORTANT: record in the Journal DURING the conversation, not only at the end. Record whenever: a decision is made, a task is completed, new information is discovered, or the user asks to remember something.
- {specific instructions}

## Specializations
- {list}
```

**Sub-index files** — each contains frontmatter + a `vault-query:start` marker block scoped to its own folder. Example for `Skills/agent-skills.md`:

```markdown
---
title: Skills
description: Skills belonging to the {id} agent.
type: index
created: {YYYY-MM-DD}
updated: {YYYY-MM-DD}
tags: [index, skills]
---

# Skills ({id})

<!-- vault-query:start filter="type=skill" scope="{id}/Skills" sort="title" format="- [[{link}|{stem}]] — {description}" -->
_(no matches)_
<!-- vault-query:end -->
```

The marker block is auto-populated by `scripts/vault_indexes.py` on the next `/indexes` run. Sub-indexes do NOT carry a parent wikilink — agent-info points DOWN to them, not the other way (parent → child convention).

**Children files** (individual routines, skills, daily journals) have **NO wikilinks at the top of their body** — they receive their inbound edge from the index file via the marker block.

**Journal/.activity/** and **.workspace/** are runtime directories — the dot-prefix makes Obsidian hide them automatically (hardcoded behavior, no `userIgnoreFilters` needed). `.workspace/data/<pipeline>/` is where pipeline step outputs land at runtime; it's created lazily by the bot's `_get_agent_workspace()` helper the first time a routine or pipeline runs for this agent, so you don't need to pre-create it — just include it in the initial scaffolding so the folder is there from day one.

### Step 10 — Sync the Obsidian graph colors

Run the indexes script directly from the bot root — no need to ask the user:

```bash
cd ~/claude-bot && python3 scripts/vault_indexes.py
```

This regenerates all vault marker blocks AND syncs `.obsidian/graph.json` so the new agent gets its own colored group in the graph view. Do this as part of the creation flow, not as a follow-up instruction to the user.

### Step 11 — Record in the Main agent's Journal

Append to today's `main/Journal/YYYY-MM-DD.md` — mention in plain text (no wikilink to the agent).

### Step 12 — Auto-switch confirmation

The bot automatically switches to the newly created agent after this skill finishes. The session is also reset so the next message runs with the new agent's context, model, and workspace.

You do NOT need to tell the user to manually switch. Just confirm that the agent was created successfully and mention the model that was configured.

### Step 13 — Suggest next steps

After creating the agent, proactively suggest:

> "Agent created! Next step: would you like to create a **scheduled routine** for this agent? Routines placed in `vault/{id}/Routines/` automatically run with the agent's own cwd, model, and isolated context.
> Examples: daily report, monitoring, morning summary."

If the user agrees → redirect to the skill `Skills/create-routine.md` with the `agent` field pre-filled.

---

## Full example: CryptoBro Agent

Goal: agent specialized in the crypto market, with a technical analyst personality.

**Triage:** dedicated agent — specialized domain, recurring use, distinct personality, will have its own routines.

**Collected data:**
- Name: CryptoBro
- Personality: "Direct and quantitative technical analyst. Prefers data over opinion. Uses bullet points, tables, and concrete numbers. Never says 'might be' — always gives a verdict with a confidence level."
- Description: "Crypto market analyst focused on BTC and altcoins"
- Specializations: technical analysis, on-chain, macro, derivatives
- Model: opus (complex analysis)
- Icon: 📊

**Result — agent.md:**
```yaml
---
title: CryptoBro
description: Crypto market analyst focused on BTC and altcoins
type: agent
created: 2026-04-09
updated: 2026-04-09
tags: [agent, crypto, bitcoin, technical-analysis]
name: CryptoBro
personality: "Direct and quantitative technical analyst. Prefers data over opinion."
model: opus
icon: "📊"
default: false
---
```

**Result — CLAUDE.md:**
```markdown
# CryptoBro 📊

## Personality
Direct and quantitative technical analyst. Prefers data over opinion.
Uses bullet points, tables, and concrete numbers. Never says "might be"
— always gives a verdict with a confidence level.

## Instructions
- Record conversations in own Journal: `Journal/YYYY-MM-DD.md`
- Record DURING the conversation, not only at the end
- Always include exact prices, percentages, and timeframes
- Cite data sources used in each analysis

## Specializations
- Technical analysis (EMAs, RSI, support/resistance)
- On-chain metrics (funding, OI, long/short)
- Macro correlation (DXY, S&P500, GOLD)
- Derivatives and sentiment (Fear & Greed)
```

**Suggested next step:** "Would you like to create a daily routine for CryptoBro? E.g.: technical analysis at 21:30 with data collection and publishing to Notion."

---

## Notes

- The Main Agent is a first-class agent in v3.5 — it lives at `vault/main/` with its own `agent-main.md`, `CLAUDE.md`, `Skills/`, `Routines/`, `Journal/`, `Reactions/`, `Lessons/`, `Notes/`, and `.workspace/`
- Switching agent changes the session's `cwd` to `vault/<id>/` (handled by `cmd_agent_switch` and `_auto_activate_agent`)
- Claude CLI loads CLAUDE.md walking up the hierarchy: `vault/<id>/CLAUDE.md` + `vault/CLAUDE.md` + project root
- Routines placed under `vault/<id>/Routines/` run as that agent — folder is the source of truth; the legacy `agent:` frontmatter field is still accepted but the folder wins on disagreement
- The macOS app (ClaudeBotManager) creates agents via `VaultService.saveAgent()` using the same v3.5 structure — both flows produce identical on-disk layouts
- Agents can be imported from OpenClaw workspaces via `/agent import` (see `Skills/import-agent.md`)
- **Isolamento total:** when a session is active on agent X, skill discovery, routine scanning, Active Memory, and graph-based skill hints all filter by path so only `vault/X/` content is visible. Messages arriving on another agent's Telegram chat/thread are routed to that agent automatically via `_agent_chat_map`.
