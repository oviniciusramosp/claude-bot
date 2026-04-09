---
title: Import or Review Imported Agent
description: Skill to import agents from external systems (e.g. OpenClaw) into the claude-bot vault, or to review previously imported agents to verify whether the CLAUDE.md synthesis was adequate. Reads instruction files, config and metadata and generates the vault/Agents/{id}/ structure with agent.md + CLAUDE.md + Journal/.
type: skill
created: 2026-04-07
updated: 2026-04-09
trigger: "when the user wants to import an agent from OpenClaw or another system, import agent from another system, review imported agent, verify import, or use /import agent"
tags: [skill, agent, openclaw, import, automation, review]
---

# Import or Review Imported Agent

## Modes of operation

- **Import** — import an agent from an external system (currently OpenClaw) into the vault
- **Review** — review previously imported agents to verify whether the CLAUDE.md synthesis was adequate

## Dependencies

- Agents/Agents.md — destination for imported agents
- Skills/create-agent.md — reference format for the generated structure

## Objective

Migrate agents from OpenClaw (OC) to the claude-bot vault, translating instruction files, model config and metadata into a standard vault/Agents/{id}/ structure.

## Steps

### 1. List available agents in OpenClaw

Check the config file at `~/.openclaw/openclaw.json` under the `agents.list` key. Each entry has:

```
{ "id": "...", "name": "...", "model": "...", "workspace": "..." }
```

List the agents found in the config file. Present the user with the list showing ID, name and model.

### 2. Ask which agent to import

Wait for the user's choice. Accept either the ID or the name.

### 3. Locate the agent's source files

For each agent, the relevant files are distributed across:

**Agent config:** `~/.openclaw/openclaw.json` → `agents.list[id]`
- Fields: `id`, `name`, `model`, `workspace`, `thinkingDefault`, `reasoningDefault`
- Default model (if not specified): inherited from `agents.defaults.model.primary`

**Agent workspace:** Check the `workspace` field in the agent's config. If it doesn't exist, use the default `~/.openclaw/workspace/`. Each agent's specific workspaces are defined in the config file.

**Instruction files:** Inside the workspace, under `instructions/`. Typical structure:
```
instructions/
  {domain}/
    _globals.md      # Global domain rules
    _style.md        # Writing style
    _apis.md         # Endpoints and tools
    _notion.md       # Notion integration
    {role}.md        # Instructions per sub-agent (manager, writer, analyst, etc.)
```

**Identity and Soul:** At the workspace root:
- `IDENTITY.md` — name, emoji, vibe
- `SOUL.md` — personality and behavioral guidelines
- `USER.md` — context about the user
- `AGENTS.md` — workspace operational rules

### 4. Read the instruction files

Read all `.md` files in `instructions/` of the agent's workspace (recursive). Prioritize:
1. Files with `_` prefix (globals, style, apis) — these are shared context
2. The `*-manager.md` file — this is the main orchestrator
3. Remaining sub-agent files — specific roles

Also read `IDENTITY.md` and `SOUL.md` from the workspace to extract personality.

### 5. Generate the structure in the vault

Create under `vault/Agents/{id}/`:

```
vault/Agents/{id}/
  agent.md       # Metadata (frontmatter parsed by the bot)
  CLAUDE.md      # Synthesized instructions
  Journal/       # Directory for own journal
```

#### 5a. Generate agent.md

```yaml
---
title: {name}
description: {short description based on the instruction files}
type: agent
created: {YYYY-MM-DD}
updated: {YYYY-MM-DD}
tags: [agent, imported, openclaw, {specialization tags}]
name: {name}
personality: {extracted from IDENTITY.md and SOUL.md}
model: {mapped model — see table below}
icon: "{emoji from IDENTITY.md or inferred}"
default: {true if id == "main", otherwise false}
source: openclaw
source_id: {original id in OC}
source_workspace: {OC workspace path}
---

[[Agents]]
```

#### 5b. Generate CLAUDE.md

Synthesize the instruction files into a clean CLAUDE.md. DO NOT copy verbatim — reorganize into:

```markdown
# {name}

## Personality
{Synthesized from workspace IDENTITY.md + SOUL.md}

## Instructions
- Record conversations in own Journal: Journal/YYYY-MM-DD.md
- {main instructions extracted from the instruction files}

## Specializations
- {list of focus areas, based on sub-agents and domains}

## Original sub-agents (reference)
{List of OC sub-agents with a short description of each, for reference.
Do not replicate all the logic — just document who did what.}

## Data sources
{APIs, endpoints, tools extracted from the _apis.md/_notion.md instruction files}
```

The agent's CLAUDE.md does NOT need to repeat vault rules (frontmatter, wikilinks, etc.) — those come from the parent CLAUDE.md at ~/claude-bot/.

#### 5c. Create Journal/

Empty directory. The agent will start recording from the first session.

### 6. Map the model

Use the mapping table (see Notes section) to convert the OC model to the claude-bot model.

### 7. Update the index

Edit `vault/Agents/Agents.md` and add: `- [[{id}]] — {short description} (imported from OpenClaw)`

### 8. Record in the global Journal

Append to the day's journal:
```markdown
## HH:MM — Agent imported from OpenClaw

- Agent {id} imported from OpenClaw via skill import-agent
- Source: {workspace path}
- Mapped model: {OC model} -> {vault model}
- {N} instruction files processed

---
```

### 9. Confirm

Inform the user:
- The agent was created at `vault/Agents/{id}/`
- How many instruction files were processed
- Which model was mapped
- How to activate: `/agent {name}` on Telegram
- Suggest reviewing the generated CLAUDE.md for adjustments

## Notes

### Model mapping table

| OC Alias | OC Model | claude-bot Model | Notes |
|---|---|---|---|
| perfil-escrita | zai/glm-5.1 | sonnet | OC primary model -> bot default |
| perfil-glm-5 | zai/glm-5 | sonnet | Deep-llm, maps to sonnet |
| perfil-glm-flash | zai/glm-4.7-flash | haiku | Light-llm, FREE |
| perfil-glm-free | zai/glm-4.5-flash | haiku | Light-llm, FREE |
| perfil-opus | anthropic/claude-opus-4-6 | opus | Direct mapping |
| perfil-sonnet | anthropic/claude-sonnet-4-6 | sonnet | Direct mapping |
| perfil-haiku | anthropic/claude-haiku-4-5 | haiku | Direct mapping |
| perfil-codex | openai-codex/gpt-5.4 | sonnet | No direct equivalent |
| perfil-flash | google/gemini-2.0-flash | haiku | Light-llm |
| perfil-leve | ollama/jarvis-local | haiku | Last resort |

If the agent inherits the default model (`agents.defaults.model.primary`), use `sonnet`.

> **Note:** This table reflects the models available at the time of creation. Check for new or discontinued models before using.

## Review Mode

Triggered when the user asks to review imported agents or verify whether the import was adequate.

### Step 1 — Identify imported agents

List agents in `vault/Agents/` that have `source: openclaw` (or another source) in the `agent.md` frontmatter.

### Step 2 — Analyze each imported agent

For each agent, read `agent.md`, `CLAUDE.md`, and the Journal. Evaluate with the checklist:

#### A. Synthesis quality

- [ ] Does the CLAUDE.md capture the essence of the original instruction files?
- [ ] Was important information lost in the synthesis? (compare with `source_workspace` if accessible)
- [ ] Is the CLAUDE.md too long (>200 lines)? Can it be condensed?
- [ ] Is the CLAUDE.md too short? Are there missing instructions that existed in the original?

#### B. Model and personality

- [ ] Does the mapped model make sense for the agent's actual use?
- [ ] Was the personality extracted from IDENTITY.md/SOUL.md faithful?
- [ ] Does the icon represent the agent well?

#### C. Post-import usage

- [ ] Does the agent have Journal entries? (is it being used?)
- [ ] If in use — has the user encountered issues that require adjustments to CLAUDE.md?
- [ ] If NOT in use — is the agent relevant? Suggest deactivating or removing it.

#### D. Vault integration

- [ ] Does the agent have associated routines? If not and it should → suggest creating via `Skills/create-routine.md`
- [ ] Have OC skills this agent used been recreated in the vault?
- [ ] Have OC cron jobs this agent had been converted into routines?

### Step 3 — Present recommendations

```
### {agent-name} (imported from {source})
Status: OK / Improvements suggested

- [improvement 1]: reason and benefit
- [improvement 2]: reason and benefit
```

### Step 4 — Execute approved improvements

- **Improve CLAUDE.md** → re-synthesize from the original instruction files (if accessible)
- **Adjust model** → edit `agent.md`
- **Create routines** → redirect to `Skills/create-routine.md` with `agent: {id}`
- **Recreate OC skills** → use vault format `Skills/{name}.md`

### Step 5 — Record in Journal

Append to the day's journal with the applied changes.

---

### Caveats

- **Sub-agents do not migrate 1:1.** OC uses multi-agent pipelines (manager -> writer -> reviewer). The vault consolidates into a single agent. → If the original workflow was complex, suggest creating a **pipeline** via `Skills/create-pipeline.md` to replicate the orchestration.
- **Instruction files with `_` prefix are shared context** (_globals, _style, _apis, _notion). They must be incorporated into CLAUDE.md, not ignored.
- **OC cron jobs and schedules do not migrate automatically.** → After importing, ask the user if they want to create routines for this agent using `Skills/create-routine.md` with `agent: {id}`.
- **OC memory is not imported.** Files in `memory/` are historical and do not migrate. → If there is critical context in memory/, suggest creating a note in `vault/Notes/` with the relevant content.
- **OC skills must be recreated** as vault skills in `Skills/{name}.md`. → List the skills this agent used in OC and ask if the user wants to recreate any of them.
- **The `source_workspace` field in agent.md** preserves the reference to the original OC workspace for future consultation of the detailed instruction files.
