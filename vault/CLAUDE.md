---
title: Vault Rules
description: Universal frontmatter, graph, and linking rules for every agent in the vault.
type: index
created: 2026-04-07
updated: 2026-04-11
tags: [vault, rules, index]
---

# Vault — Universal Rules

**IMPORTANT:** This file is the vault's universal contract. It defines frontmatter rules, the graph model, and linking rules that apply to **every** file in the vault, regardless of which agent owns it. Agent-specific operational instructions live in `<agent>/CLAUDE.md` — for example, `main/CLAUDE.md` for the Main agent.

## Agents rooted in this vault

Every agent sits directly under the vault root. The canonical entry point per agent is its `agent-info.md` file (frontmatter: metadata, body: the single parent wikilink `[[README]]`). This file does NOT list the agents — the agents point up to README directly, not via CLAUDE.md, so the graph tree stays clean with exactly one parent per file.

The user may refer to this directory as **"vault"**, **"knowledge base"**, **"knowledge"**, or **"KB"**. They all mean the same thing: this directory.

## v3.1 Layout — flat per-agent structure

```
vault/
├── README.md
├── CLAUDE.md             ← this file (universal rules)
├── Tooling.md            ← shared tool preferences
├── .graphs/              ← auto-generated graph.json
├── .obsidian/
├── main/
│   ├── agent-info.md     ← metadata (frontmatter) + hub wikilinks (body)
│   ├── CLAUDE.md         ← Main agent's personality / instructions
│   ├── Skills/
│   ├── Routines/
│   ├── Journal/
│   ├── Reactions/
│   ├── Lessons/
│   ├── Notes/
│   └── workspace/
├── crypto-bro/
│   ├── agent-info.md
│   ├── CLAUDE.md
│   ├── Skills/           ← private to crypto-bro
│   ├── Routines/         ← private to crypto-bro
│   ├── Journal/
│   ├── Reactions/
│   ├── Lessons/
│   ├── Notes/
│   └── workspace/
└── parmeirense/
    └── ... (same structure)
```

**Isolamento total.** Every agent — including Main — owns its own Skills, Routines, Journal, Reactions, Lessons, and Notes. Content is NEVER inherited between agents. If Main has a useful skill and crypto-bro needs it, the file must be copied (or recreated) under `crypto-bro/Skills/`.

The vault root contains only shared files (`README.md`, this `CLAUDE.md`, `Tooling.md`) plus each agent's directory. An agent is identified by the presence of `agent-info.md` — any top-level directory without it (e.g. `.graphs`, `.obsidian`, `Images`) is internal scaffolding, not an agent.

### `agent-info.md` — the per-agent hub

Each agent has a single `agent-info.md` file at its root that combines:

- **Metadata** in frontmatter: `name`, `icon`, `model`, `description`, optional `chat_id`/`thread_id` for Telegram routing, etc.
- **Graph wikilinks** in the body: one `[[Skills]]`, `[[Routines]]`, `[[Journal]]`, `[[Reactions]]`, `[[Lessons]]`, `[[Notes]]` link that the Obsidian graph uses to make the agent's subtree reachable from the vault root.

The top-level `vault/CLAUDE.md` (this file) has path-qualified links to each `<agent>/agent-info.md`, giving the graph a single connected tree:
`README → CLAUDE → <agent>/agent-info → Skills/Routines/… → leaves`.

## Language policy

**All vault files MUST be written in English** — frontmatter, instructions, structural content, descriptions, tags. This applies to new files and updates to existing files.

**Exceptions:**
- **Journal entry body content** — may be written in the user's preferred language (the daily log reflects conversation language)
- **Agent signature terms** — character-defining words/phrases may stay in Portuguese (e.g., "porco", "segue meu Pal!") when part of the agent's personality
- **Bot conversations** — always respond in whatever language the user writes in

## How to consume the vault

**Principle: scan before read.** Never open all files in a folder. First list the files and read only the first ~10 lines (frontmatter) of each. Use the `description` field to decide which ones deserve a full read.

### Knowledge graph (`.graphs/graph.json`)

The vault has a lightweight knowledge graph at `.graphs/graph.json`, regenerated daily by the `vault-graph-update` routine. Every node now carries an `agent` attribute derived from its path (`Agents/<id>/…`), which the Active Memory and skill hint helpers use to enforce isolamento total.

**When to use:**
- Before doing extensive glob in large folders
- To find files related to a topic without reading all frontmatters
- To understand community structure inside a single agent

**Fallback:** If `graph.json` doesn't exist or is outdated, fall back to the standard scan-before-read procedure.

### Scan-before-read (standard procedure)

When starting any session (as an agent):
1. If `.graphs/graph.json` exists, query it for structural context inside **your** agent folder
2. Glob `Journal/*.md` — read the last 2-3 days for recent context
3. Read `../../Tooling.md` (relative to your agent cwd) — shared tool preferences
4. If the user mentions a topic, list `Notes/` and read frontmatters to filter by `description` and `tags` before opening full files
5. If a skill is triggered, read `Skills/<skill>.md` for instructions
6. If a routine is triggered, read `Routines/<routine>.md` for the prompt

## Unbreakable rule: YAML frontmatter

Every `.md` in the vault MUST have frontmatter. No exceptions. Creating without frontmatter is an error.

```yaml
---
title: Descriptive name
description: Short sentence explaining the content and when this file is relevant.
type: journal | note | skill | reference | routine | pipeline | agent | index | reaction | lesson | history
created: YYYY-MM-DD
updated: YYYY-MM-DD
tags: [topic1, topic2]
---
```

The `description` field is required and functions as a semantic index. It must contain enough context to decide whether the file needs to be read in full or not.

**Journal descriptions** require special care — they are the primary signal for LLMs scanning which days are relevant:
- MUST be English, keyword-rich, verb-forward or noun-forward
- List 2-4 concrete topics, separated by commas
- Update the description as entries are added throughout the day
- GOOD: `Pipeline polish - friendly source names, GE/Lance images, Telegram notify fix.`
- GOOD: `Threads eval injection validated — 15 posts via HTTP API, fetch_threads.py rewritten.`
- BAD (banned): `Daily log for DATE`, `Registro de atividades`, `Activities for`, anything starting with a date or agent name

**Exempt from frontmatter** (by design):
- `Agents/<id>/agent.md` — metadata is the frontmatter; body is empty
- `Agents/<id>/CLAUDE.md` — instructions for Claude Code, no frontmatter
- Pipeline step prompts under `Routines/{pipeline}/steps/*.md` — raw prompt text only

### Optional `related` field

Semantic relationships that should NOT become wikilinks (to keep the graph clean), but help with navigation:

```yaml
related:
  - file: "file-name"
    type: extracted
    reason: "uses data from the same endpoint"
```

Confidence types: `extracted` (explicit), `inferred` (deduced), `ambiguous` (needs validation).

## Graph structure — a clean tree

Each agent's subtree is a **clean tree graph**. Obsidian Graph View is the primary way for the user to navigate. The chart must be clean, with clear connections and no unnecessary links.

```
README (root hub)
  └── Agents (shared index)
        └── {agent} (hub)
              ├── Journal (index) → daily entries
              ├── Notes (index) → individual notes
              ├── Skills (index) → individual skills
              ├── Routines (index) → individual routines
              └── ... (all per-agent)
```

**Linking rules:**

| Type | Outlinks | Inlinks |
|------|----------|---------|
| README | `Agents` index + `Tooling` | none (root) |
| `Agents/Agents.md` | each agent hub `{id}.md` | README |
| Agent hub `{id}.md` | the agent's own knowledge sub-files only | `Agents` index |
| Index inside an agent (`Skills.md`, `Routines.md`, …) | the direct children in the same folder | agent hub |
| Leaf (routine, note) | `[[ParentIndex]]` on first line + genuine cross-links | its index |
| Skill | NO wikilinks (use paths). Exception: links to own sub-files | Skills index |
| Tooling | none (terminal) | README |

**Files that are NOT graph nodes** (excluded by `vault-graph-builder.py`):
- Daily journal entries (`<agent>/Journal/YYYY-MM-DD.md`) — ephemeral chronological logs
- Bot reactions (`<agent>/Reactions/**`) — webhook config, not knowledge
- Routine execution history (`<agent>/Routines/.history/**`) — churn-y log rollups
- Agent instructions (`<agent>/CLAUDE.md`) — parsed directly by Claude CLI, not browsed in the graph

These files exist on disk but are deliberately not part of the knowledge graph. They MUST NOT contain wikilinks — adding `[[]]` here pollutes Obsidian's graph view via dangling edges and risks leaking to the LLM when read as prompt context.

**Temp branch (`<agent>/agent-temp.md`) — runtime files ARE graph nodes.** Pipeline workspace outputs (`<agent>/.workspace/data/**/*.md`) and the rolling context (`<agent>/.context.md`) are linked via `[[<agent>/agent-temp|Temp]]` so Obsidian distinguishes intentional ephemera from broken/unlinked leaves. Authors of these files (pipeline harness, context writer) inject the parent link automatically. The `agent-temp.md` index itself is one branch off the agent hub, parallel to `Notes`/`Routines`/`Skills`/`Lessons`.

**Core principle: not every mention needs to be a `[[link]]`.** Links exist to create connections IN the Obsidian graph. If the connection doesn't add visual value, don't link. Use plain text.

**Forbidden:**
- README linking to leaves (always through an index)
- Indexes linking to each other across agents
- Two files having multiple connections
- Decorative or "related" wikilinks
- Journal entries creating wikilinks to everything they mention (pollutes the graph)

## Index files (MOCs)

Each folder has an index that functions as a graph hub. These are auto-regenerated by `scripts/vault_indexes.py` using the `vault-query:start` marker blocks — edit manually OUTSIDE the markers only.

- `README.md` → root hub
- `Agents/Agents.md` → lists every agent via `{parent}` field
- `Agents/<id>/Skills/Skills.md`, `Routines/Routines.md`, `Journal/Journal.md`, … → per-agent listings scoped by `scope="<id>/<Sub>"`

## Wikilinks — when to use

**Create a link when:**
- First line of body → `[[ParentIndex]]` (same-folder)
- Pipeline parent → its steps (via the `## Steps` section)
- Skill → its own sub-files
- Leaf → its parent index

**DO NOT create a link when:**
- Mentioning something in the Journal (use plain text)
- Referencing Tooling from within leaves
- Mentioning something "related" that is not a real dependency
- Citing an entity for context without dependency

Each `[[wikilink]]` adds an edge to the Obsidian graph. Fewer edges = a more navigable graph.

## Writing principles for the graph

1. **Atomicity** — each note about a single concept.
2. **Intentional links** — link ONLY real dependencies.
3. **Discoverability** — tags in frontmatter for search.
4. **Stability** — filenames are permalinks. Renaming breaks links.
5. **Incrementality** — never delete, always add.
6. **Tree first** — the graph is a tree (README → Agents → agent hub → index → leaf). Cross-links are the exception.

## Creating files in the vault

**1. Complete frontmatter** (see above).

**2. First line of body = link to parent index, path-qualified:** Routine → `[[<agent>/Routines/agent-routines|Routines]]`, Note → `[[<agent>/Notes/agent-notes|Notes]]`, Lesson → `[[<agent>/Lessons/agent-lessons|Lessons]]`. The path prefix is **required** because every agent has its own `agent-notes.md`/`agent-routines.md`/etc. — bare `[[agent-notes]]` is ambiguous and Obsidian resolves it to a single file across the whole vault, leaving the others without inlinks. **Exception: Skills DO NOT link to parent index** — Skills.md links to the skills, not the other way around.

**3. Cross-links only for real dependencies.** When in doubt, don't link.

**4. Update the folder's index.** (Or let `scripts/vault_indexes.py` regenerate it — the `vault-indexes-update` routine does this daily.)

**5. Record in the day's Journal** (without creating a wikilink to the new file — mention in plain text).

## Frontmatter specs for common types

### Routine
```yaml
---
title: Routine Name
description: What this routine does and when it's relevant.
type: routine
created: YYYY-MM-DD
updated: YYYY-MM-DD
tags: [routine, category]
schedule:
  times: ["09:00", "18:00"]
  days: [mon, tue, wed, thu, fri]
  until: "2026-12-31"
model: sonnet
enabled: true
---

[[Routines]]

Prompt for Claude Code...
```

Folder location is the source of truth for the owning agent — a file at `Agents/crypto-bro/Routines/foo.md` belongs to `crypto-bro`. The legacy `agent:` frontmatter field is still accepted for backcompat but the folder wins if they disagree.

### Pipeline
```yaml
---
title: Pipeline Name
type: pipeline
schedule:
  times: ["09:00"]
  days: ["*"]
model: sonnet
enabled: true
notify: final
---

[[Routines]]

```pipeline
steps:
  - id: collect
    name: Collect data
    model: haiku
    prompt_file: steps/collect.md
  - id: analyze
    depends_on: [collect]
    model: opus
    prompt_file: steps/analyze.md
    output: telegram
```

## Steps

- collect.md
- analyze.md
```

Step prompt files live under `Routines/{pipeline}/steps/*.md` — they have **no frontmatter and no wikilinks**.

**Optional `## Example Output` / `## Expected Output` sections.** When a routine or pipeline step produces structured output and the format matters for correctness or downstream parsing, include an inline example at the end of the prompt body. This is especially important for pipeline steps whose output feeds another step. See `Skills/create-routine.md` and `Skills/create-pipeline.md` for detailed guidance and examples.

**Telegram notifications from steps.** To send additional Telegram messages from a pipeline step or routine, use `scripts/telegram_notify.py "message"`. The script auto-detects the owning agent from the `AGENT_ID` env var (injected by the bot harness) and reads `chat_id`/`thread_id` from the agent's frontmatter. The harness's `notify: final` and `output: telegram` handle the main pipeline output automatically.

### Agent
```yaml
---
title: Name
description: Short description
type: agent
name: Readable Name
personality: Tone and style
model: sonnet
icon: "🤖"
default: false
chat_id: "-100XXXXXXXXXX"   # optional — Telegram group ID for notifications
thread_id: 123              # optional — Telegram topic ID
---
```

`agent.md` is metadata only (empty body). The real instructions live in `CLAUDE.md` inside the same folder.

## Tools (`Tooling.md`)

Map of preferences: which tool to use for each type of task. Consult before choosing an approach. This file is shared across all agents — the whole vault uses the same tool preferences.

**Reading:** Before choosing a tool for a task, read Tooling.md.

**Writing:** When the user informs about a new tool, tooling preference, or useful command — update Tooling.md (do not save to auto-memory).

## Private journal content

Any text you want to keep OUT of the SQLite FTS index (and therefore out of Active Memory injection and SessionStart auto-recall) can be wrapped in `<private>...</private>`. The tags are case-insensitive and can span multiple lines.

```markdown
## 14:30

Regular reflection for the day that is fair game for auto-recall.

<private>
Stuff I want to keep in the journal file but don't want Claude to surface
automatically next session — sensitive reasoning, half-baked ideas, names
I'd rather not have quoted back at the user.
</private>

More public content after the private block.
```

**What happens:**
- `vault/.graphs/graph.json` and the on-disk markdown file keep the original text unchanged — nothing is deleted or rewritten. You can still read it by opening the file directly.
- `scripts/vault_index.py` strips the `<private>...</private>` block before it gets stored in the FTS column, so searching for words inside the block returns nothing.
- The row storing the file is flagged `private=1`. SessionStart auto-recall passes `include_private=False`, so files with any private marker are hidden entirely — an extra layer of caution at the moment the user sees the response.
- Regular `vault_search_text` calls still return public content from files that had private blocks (default `include_private=True`), so the public parts remain useful — only the private text is unrecoverable via search.

Use it for thoughts you'd jot in a paper notebook but wouldn't dictate to a colleague. Do NOT use it as a security feature — anyone with filesystem access still reads the raw file.
