# Vault Structure Reference

Complete reference for the `vault/` directory -- the persistent knowledge base used by the claude-bot.

## Overview

The vault is an [Obsidian](https://obsidian.md/) knowledge base that serves as the bot's persistent context and long-term memory. It is structured as a **clean tree graph** designed for both AI consumption and human navigation via Obsidian's Graph View.

The bot operates with `vault/` as its default working directory. When Claude Code CLI runs, it reads `vault/CLAUDE.md` for operational instructions. The vault stores journal entries, notes, skills, routines, pipelines, and agent definitions.

## Directory Layout

```
vault/
  README.md              # Hub root -- links to all indexes
  CLAUDE.md              # Operational instructions for the bot (runtime)
  Tooling.md             # Tool preferences map (which tool for which task)
  .env                   # API keys for external services (Notion, Figma, etc.)
  Journal/
    Journal.md           # Index (MOC) for journal entries
    YYYY-MM-DD.md        # Daily journal entries (one per day)
  Notes/
    Notes.md             # Index for knowledge notes
    *.md                 # Individual atomic notes (kebab-case)
  Skills/
    Skills.md            # Index for skills
    *.md                 # Individual skill definitions
  Routines/
    Routines.md          # Index for routines
    *.md                 # Routine definitions (scheduled tasks)
    {pipeline-name}/     # Pipeline step directory
      steps/
        *.md             # Individual pipeline step prompts
  Agents/
    Agents.md            # Index for agents
    {agent-id}/
      agent.md           # Agent metadata (frontmatter only, body empty)
      CLAUDE.md          # Agent-specific instructions for Claude Code
      {agent-id}.md      # Hub file for Obsidian graph links
      Journal/
        YYYY-MM-DD.md    # Agent-specific journal entries
  Images/
    screenshots/         # Screenshot images
    diagramas/           # Diagrams
    referencias/         # Reference images
```

## File Types

| Type | Location | Description |
|------|----------|-------------|
| `journal` | `Journal/YYYY-MM-DD.md` | Daily log entries, append-only |
| `note` | `Notes/*.md` | Atomic knowledge notes on a single concept |
| `skill` | `Skills/*.md` | Procedural instructions the bot can execute |
| `routine` | `Routines/*.md` | Scheduled tasks with cron-like schedules |
| `pipeline` | `Routines/*.md` (type: pipeline) | Multi-step DAG-based orchestration |
| `agent` | `Agents/{id}/agent.md` | Specialized agent with custom personality |
| `reference` | Various | Static reference material |
| `index` | `{Folder}/{Folder}.md` | Map of Content (MOC) linking to children |

## Frontmatter Schema

Every `.md` file in the vault **must** have YAML frontmatter. No exceptions.

### Universal Fields

```yaml
---
title: Descriptive Name
description: Short sentence explaining what the file contains and when it is relevant.
type: journal | note | skill | routine | pipeline | agent | reference | index
created: YYYY-MM-DD
updated: YYYY-MM-DD
tags: [topic1, topic2]
---
```

The `description` field is mandatory and acts as a semantic index. It should contain enough context to decide whether the file needs to be fully read.

### Type-Specific Fields

**Skills** add:
```yaml
trigger: "when the user asks for X"
```

**Routines** add:
```yaml
schedule:
  times: ["09:00", "18:00"]     # HH:MM in 24h local time
  days: [mon, tue, wed, thu, fri]  # or ["*"] for every day
  until: "2026-12-31"            # optional expiry date
model: sonnet                     # sonnet | opus | haiku
enabled: true                     # true | false
```

**Pipelines** add:
```yaml
type: pipeline                    # distinguishes from regular routine
notify: final | all | summary | none
```

Plus a fenced `pipeline` block in the body (see Skills section below).

**Agents** (`agent.md`) add:
```yaml
name: Human-Readable Name
personality: Tone and style description
model: sonnet
icon: "emoji"
```

**Routines with agent targeting** add:
```yaml
agent: agent-id                  # runs in that agent's workspace
```

## Linking Rules

The vault is a **tree-first graph**. Cross-links are the exception, not the rule.

### Link Hierarchy

```
README.md (root hub)
  |
  +-- Journal.md (index) --> YYYY-MM-DD.md entries
  +-- Notes.md (index) --> individual notes
  +-- Skills.md (index) --> individual skills
  +-- Routines.md (index) --> individual routines
  +-- Agents.md (index) --> individual agents
  +-- Tooling.md (leaf)
```

### Link Rules by File Type

| File Type | Outgoing Links | Incoming Links |
|-----------|---------------|----------------|
| README | All indexes + Tooling | None (root) |
| Index | Its direct children only | README |
| Leaf (skill, note, routine) | `[[IndexParent]]` on first line + genuine cross-links | Its index |
| Agent hub (`{id}.md`) | Internal agent files | Agents index |
| Journal entry | `[[Journal]]` or `[[{agent}/Journal\|Journal]]` | Journal index |
| Tooling | None (terminal) | README |

### What NOT to Link

- README must never link directly to leaf files (always go through indexes).
- Indexes must never link to other indexes.
- No two files should have multiple connections.
- No decorative or "related" links.
- Journal entries must not create wikilinks for entities they mention (use plain text).

### Wikilink Syntax

```
[[filename]]                    # simple link
[[path/to/file|Display Text]]  # link with alias
[[filename#section]]            # link to section
```

## Journal System

### Global Journal

Located at `Journal/YYYY-MM-DD.md`. One file per day, **append-only** (never delete content).

**Entry format:**

```markdown
## HH:MM -- Short summary

- Topics discussed
- Decisions made
- Actions taken

---
```

The first line of the body must be `[[Journal]]`.

### Agent Journals

Each agent has its own journal in `Agents/{id}/Journal/YYYY-MM-DD.md`. Same format, but the first line links back to the agent's journal index:

```markdown
[[{agent-id}/Journal|Journal]]
```

### Journal Rules

- Never create wikilinks to entities mentioned in journal entries (plain text only).
- Always append, never overwrite or delete.
- Record significant conversations with timestamps.

## Skills

Skills are procedural instruction files in `Skills/`. They define actions the bot can execute when triggered.

**File format:**

```yaml
---
title: Skill Name
description: What it does and when to use it.
type: skill
trigger: "when the user asks for X"
tags: [skill, category]
---

[[Skills]]

## Objective
...

## Steps
1. ...

## Notes
...
```

Cross-links in skills are only for real dependencies (e.g., `[[Routines]]` if the skill creates routines).

## Notes

Knowledge notes in `Notes/` follow the **atomic notes** principle: each note covers a single concept.

**Rules:**

- Filenames in kebab-case.
- Never delete content -- always add or update.
- Tags in frontmatter for searchability.
- First line of body: `[[Notes]]`.
- Better to have 3 short linked notes than 1 long note.

## Consuming the Vault Efficiently

The vault is designed for a **scan-before-read** approach:

1. List files in a directory.
2. Read only the first ~10 lines (frontmatter) of each file.
3. Use the `description` field to decide which files deserve full reading.
4. Only then open the relevant files completely.

This prevents unnecessary token usage when the bot processes the vault on each session start.
