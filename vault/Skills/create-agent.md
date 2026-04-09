---
title: Create or Review Agent
description: Consultative skill for creating specialized agents or reviewing existing ones. Helps decide whether a case requires a dedicated agent or if the Main Agent is sufficient. Generates the 3 files (agent.md, CLAUDE.md, {id}.md) + Journal.
type: skill
created: 2026-04-07
updated: 2026-04-09
trigger: "when the user wants to create, review, or improve an agent, wants a specialized assistant, needs a bot for something, or uses /agent new"
tags: [skill, agent, automation, review]
---

# Create or Review Agent

## Modes of operation

This skill operates in two modes:

1. **Creation** — when the user wants to create a new agent
2. **Review** — when the user wants to review, improve, or evaluate existing agents

Detect the mode from the conversation context. If ambiguous, ask.

---

## Creation Mode

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

### Step 7 — Generate ID

kebab-case of the name. E.g.: "CryptoAnalyst" -> `crypto-analyst`

### Step 8 — Create 4 items in `vault/Agents/{id}/`

**agent.md** — metadata for the bot (empty body):
```yaml
---
title: {name}
description: {short description}
type: agent
created: {YYYY-MM-DD}
updated: {YYYY-MM-DD}
tags: [agent, {specializations}]
name: {name}
personality: {personality in one sentence}
model: {model}
icon: "{emoji}"
default: false
---
```

**CLAUDE.md** — instructions for Claude Code (NO frontmatter):
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

**{id}.md** — link hub in the Obsidian graph:
```markdown
---
title: {name}
description: Hub for agent {name} in the graph.
type: agent
created: {YYYY-MM-DD}
updated: {YYYY-MM-DD}
tags: [agent]
---

[[{id}/Journal|Journal]]
[[agent]]
[[CLAUDE]]
```

**Journal/** — create the empty directory

### Step 9 — Update Agents.md

Add `- [[{id}]] — {description}` to the index.

### Step 10 — Record in the global Journal

Append to the day's journal — mention in plain text (no wikilink to the agent).

### Step 11 — Confirm

Inform how to activate: `/agent {name}`

### Step 12 — Suggest next steps

After creating the agent, proactively suggest:

> "Agent created! Next step: would you like to create a **scheduled routine** for this agent? Routines with `agent: {id}` run automatically in its workspace.
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

## Review Mode

Triggered when the user asks to review, improve, or evaluate existing agents.

### Step 1 — Identify scope

- If the user mentioned a specific agent → review only that one
- If a general review was requested → list all agents in `vault/Agents/` and analyze each one (including the Main Agent)

### Step 2 — Analyze each agent

For each agent, read `agent.md` and `CLAUDE.md` in full. Evaluate using the checklist below.

**Review checklist:**

#### A. CLAUDE.md up to date?

- [ ] Do the instructions reflect the agent's actual usage? (compare with recent Journal)
- [ ] Are there obsolete instructions or ones that are never used?
- [ ] Are instructions missing for tasks the agent performs frequently?

#### B. Model appropriate?

- [ ] Is the agent doing simple tasks with `opus`? → suggest `sonnet` or `haiku`
- [ ] Is the agent doing complex analysis with `haiku`? → suggest `sonnet` or `opus`
- [ ] Does the agent have frequent routines with an expensive model? → evaluate cost-benefit

#### C. Agent in use?

- [ ] Does the Journal have recent entries (last 2 weeks)?
- [ ] If not — is the agent still relevant? Suggest disabling or removing.
- [ ] If few entries — does the usage justify a dedicated agent or would Main suffice?

#### D. Distinctive personality?

- [ ] Is the personality in `agent.md` specific enough?
- [ ] Does the tone in CLAUDE.md match the `personality` field?
- [ ] Does the agent clearly differentiate itself from Main?
- [ ] If the personality is generic ("be helpful") → suggest refinement

#### E. Merge opportunity?

- [ ] Do two agents have overlapping specializations?
- [ ] Does one agent do so little that it could be absorbed by another?
- [ ] If a merge makes sense → propose which one survives and what it absorbs

### Step 3 — Present recommendations

For each analyzed agent, present:

```
### {agent-name}
Status: OK / Improvements suggested

- [improvement 1]: reason and benefit
- [improvement 2]: reason and benefit
```

If the review is general, include a consolidated overview:
```
### Overview

- Total agents: X (+ Main)
- Actively in use: Y
- No recent usage: Z
- Merge candidates: [list]
- Removal candidates: [list]
```

### Step 4 — Apply approved improvements

Ask which improvements the user wants to apply. For each approved one:

- **Model change** → edit `agent.md` (field `model`)
- **Personality refinement** → edit `agent.md` (field `personality`) and `CLAUDE.md` (Personality section)
- **Instructions update** → edit `CLAUDE.md`, show diff to the user
- **Agent merge** → migrate relevant instructions to the surviving agent, move Journal entries if necessary
- **Removal** → confirm with the user before deleting (via macOS Trash if available)

When modifying an agent:
1. Update the `updated` field in `agent.md` frontmatter
2. Record changes in the Journal

### Step 5 — Record in the Journal

Append to the day's journal with the applied changes.

---

## Notes

- The Main Agent is the bot's default agent — it has no own workspace or specific CLAUDE.md
- Agents change the `cwd` to `vault/Agents/{id}/` when active
- Claude CLI loads CLAUDE.md walking up the hierarchy: `Agents/{id}/CLAUDE.md` + `vault/CLAUDE.md` + root
- Routines can be routed to agents with `agent: {id}` in the frontmatter
- The macOS app (ClaudeBotManager) allows creating and managing agents via UI
- Agents can be imported from templates with `/agent import`
