# Sessions & Agents Guide

This document explains how the bot manages sessions, models, per-chat contexts, group chat support, and specialized agents.

## Sessions

A session represents a persistent conversation with Claude Code. Each session maintains its own Claude CLI session ID, model preference, workspace, and message count.

### Session Data Model

```python
@dataclass
class Session:
    name: str
    session_id: Optional[str] = None
    model: str = "sonnet"
    workspace: str = CLAUDE_WORKSPACE
    agent: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    message_count: int = 0
    total_turns: int = 0
```

### Lifecycle

**Creating a session:**
- `/new [name]` -- creates a new session with the given name
- If no name is provided, one is auto-generated from the current date/time in the format `DDmon-HHMM` (e.g., `08apr-1430`)
- The new session becomes the active session immediately
- Before creating, the current session receives a consolidation prompt to summarize the conversation into the Journal

**Switching sessions:**
- `/switch <name>` -- switches to an existing session by name
- The previous session is consolidated before switching

**Deleting sessions:**
- `/delete <name>` -- removes a session from the session store
- Cannot delete the currently active session

**Clearing sessions:**
- `/clear` -- resets the current session by clearing its Claude CLI session ID
- The next message starts a fresh conversation, but the session name and settings are preserved

**Compacting context:**
- `/compact` -- sends a special prompt asking Claude to auto-compact its context window
- Useful when a session has accumulated too much context

### Persistence

Sessions are persisted to `~/.claude-bot/sessions.json`. The file contains:
- All session objects (keyed by name)
- The active session name
- A cumulative turn counter

The file is written atomically (write to `.tmp`, then rename) to prevent corruption. Sessions are loaded on bot startup and saved after every mutation.

### Resumption

When sending a message to a session that already has a `session_id`, the bot passes `--resume <session_id>` to the Claude CLI. This enables true context persistence -- Claude maintains the full conversation history across messages without needing to resend prior messages.

New sessions (no `session_id` yet) start fresh. After the first response, the bot captures the session ID from Claude's stream-json output and stores it for future resumption.

## Models

Three models are available:

| Model | Command | Use Case |
|-------|---------|----------|
| `sonnet` | `/sonnet` | Default. Balanced speed and capability |
| `opus` | `/opus` | Maximum capability, slower |
| `haiku` | `/haiku` | Fastest, lighter tasks |

### Switching Models

- `/sonnet`, `/opus`, `/haiku` -- quick switch for the current session
- `/model` -- shows an inline keyboard with all three options

Model selection is per-session. Switching the model only affects the current session; other sessions retain their own model preference. The model is stored in the `Session` object and persisted across bot restarts.

### Reasoning Effort

- `/effort <low|medium|high>` -- sets the reasoning effort level
- This maps to the Claude CLI `--reasoning-effort` flag
- Effort is a global setting (not per-session)

## Contexts

Contexts provide per-chat and per-topic isolation. Each Telegram chat or group topic gets its own `ThreadContext`, which maps to a dedicated session.

### ThreadContext Data Model

```python
@dataclass
class ThreadContext:
    chat_id: str
    thread_id: Optional[int] = None
    runner: Optional[ClaudeRunner] = None
    session_name: Optional[str] = None
    pending: list = field(default_factory=list)
    stream_msg_id: Optional[int] = None
    user_msg_id: Optional[int] = None
```

### Automatic Session Creation

When the bot receives a message from a new chat/topic pair that has no existing context:
1. A new `ThreadContext` is created
2. A session is auto-created with name `t<thread_id>` for group topics, or `DDmon-HHMM` for private chats
3. The context-to-session mapping is persisted to `~/.claude-bot/contexts.json`

This means each Telegram topic gets its own independent Claude conversation without any manual setup.

### Context Persistence

Context mappings survive bot restarts. On startup, the bot loads `contexts.json` and restores all context-to-session associations. The actual Claude CLI session is resumed via the stored `session_id` in the linked `Session` object.

## Group Chat Support

The bot supports Telegram group chats with topics (forum mode). Each topic within a group operates as an independent conversation.

### Per-Topic Isolation

- Each group topic gets its own `ThreadContext` and session
- Messages in different topics are completely independent
- Commands like `/new`, `/switch`, and `/model` apply only to the current topic's session

### Auto-Discovery

When the bot encounters a message from a new group topic:
1. It detects the `thread_id` from the Telegram update
2. Creates a new context and session for that topic
3. Sends an onboarding message (first interaction only)

### Agent Per Topic

Each topic can have its own active agent. When you activate an agent via `/agent <name>` in a topic, it only affects that topic's session. Other topics in the same group continue using their own agents (or no agent).

## Agents

Agents are specialized personas with their own instructions, personality, workspace, and journal. They allow the bot to adopt different behaviors for different tasks.

### What is an Agent?

An agent is a directory under `vault/Agents/{id}/` that contains:

```
Agents/{id}/
  agent.md       # Metadata (frontmatter parsed by the bot)
  CLAUDE.md      # Instructions for Claude Code (NO frontmatter, NO wikilinks)
  {id}.md        # Hub file for Obsidian graph links
  Journal/       # Agent-specific journal directory
```

### agent.md -- Metadata

The bot parses this file's frontmatter to configure the agent. The body is empty.

```yaml
---
title: Agent Name
description: Short description of what this agent does
type: agent
name: Human-Readable Name
personality: Tone and style description
model: sonnet
icon: "🤖"
---
```

Fields:
- `name` -- display name shown in Telegram keyboards
- `personality` -- describes the agent's communication style
- `model` -- default model when this agent is active (sonnet/opus/haiku)
- `icon` -- emoji shown next to the agent name in UI

### CLAUDE.md -- Instructions

This file contains the instructions that Claude Code loads when the agent is active. It does **not** have YAML frontmatter or Obsidian wikilinks (it is a Claude Code instruction file, not a vault document).

Structure:
```markdown
# {Agent Name} {emoji}

## Personality
{description of tone, style, and behavior}

## Instructions
- Record conversations in own Journal: Journal/YYYY-MM-DD.md
- {agent-specific instructions}

## Specializations
- {areas of focus and expertise}
```

### {id}.md -- Graph Hub

This file exists solely for the Obsidian graph view. It contains wikilinks to the agent's internal files:

```markdown
[[{id}/Journal|Journal]]
[[agent]]
[[CLAUDE]]
```

### Creating Agents

- `/agent` with no arguments -- shows an action keyboard (switch, list, create, edit, import)
- `/agent new` or the "Create new" button -- triggers the agent creation skill
- `/agent import` -- imports an agent from an external source (e.g., OpenClaw)

### Activating Agents

- `/agent <name>` -- activates the named agent for the current session
- `/agent` then "Switch agent" button -- shows a keyboard of available agents
- "None" button -- deactivates the current agent, returning to default mode

When an agent is activated:
1. The session's `agent` field is set to the agent ID
2. The session's `workspace` changes to `vault/Agents/{id}/`
3. Claude CLI runs with `cwd` set to the agent's directory
4. Claude loads the agent's `CLAUDE.md` + `vault/CLAUDE.md` + root `CLAUDE.md` (hierarchy)

### Deactivating Agents

Selecting "None" or running `/agent none`:
1. Clears the session's `agent` field
2. Resets the workspace to the default (`vault/`)

### Agent Journal

Each agent maintains its own journal in `Agents/{id}/Journal/`. Entries follow the same daily format as the global journal (`YYYY-MM-DD.md`), but are scoped to the agent's context.

The journal path is determined by `get_agent_journal_dir()`:
- If an agent is active: `vault/Agents/{id}/Journal/`
- If no agent: `vault/Journal/`

Journal entries are append-only. The bot's system prompt instructs Claude to record significant conversations in the appropriate journal after each interaction.

### Agents in Routines and Pipelines

Routines and pipeline steps can target specific agents via the `agent` field in their frontmatter or step definition. When a routine runs with an agent, the Claude CLI session uses the agent's workspace as its `cwd`, loading the agent's instructions automatically.

```yaml
# In a routine's frontmatter:
agent: crypto-bro

# In a pipeline step:
steps:
  - id: analyze
    agent: crypto-bro
    prompt_file: steps/analyze.md
```
