# claude-bot vault MCP server (optional sidecar)

This is an **optional** sidecar that exposes the claude-bot vault to any
Model Context Protocol (MCP) client — Claude Desktop, Cursor, sibling
Claude Code instances, etc. The Telegram bot does **not** depend on this
server. It remains stdlib-only and works without it.

## Why

The Telegram bot is currently the only client that can read and edit the
vault. With this server running, every other MCP client on the same machine
can:

- search the vault by frontmatter properties (`type=routine model=opus`)
- read individual files with structured frontmatter
- list folder contents (cheap, frontmatter only)
- walk the knowledge graph
- run the vault hygiene linter
- create notes and append to today's journal
- read recent routine/pipeline execution history

The server wraps the same `scripts/vault_query.py`, `scripts/vault_lint.py`,
and `scripts/vault_frontmatter.py` modules the bot uses, so the data shape
is identical across clients.

## Setup

```bash
cd mcp-server
pip install -r requirements.txt
python vault_mcp_server.py
```

This installs the [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
in your active Python environment. The bot itself is not affected.

### Connecting from Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "claude-bot-vault": {
      "command": "python",
      "args": ["/absolute/path/to/claude-bot/mcp-server/vault_mcp_server.py"]
    }
  }
}
```

Restart Claude Desktop. You should see the `claude-bot-vault` server show
up in the tool list, with the tools below available.

### Custom vault location

Set `CLAUDE_BOT_VAULT` to override the default (`<project>/vault`):

```bash
CLAUDE_BOT_VAULT=/path/to/another/vault python vault_mcp_server.py
```

## Tools exposed

| Tool                       | What it does                                                        |
|----------------------------|---------------------------------------------------------------------|
| `vault_search`             | Frontmatter-aware search (`type=routine model=opus`)                |
| `vault_read`               | Read a file (frontmatter + body + wikilinks)                        |
| `vault_list`               | List files in a folder (cheap, frontmatter only)                    |
| `vault_related`            | Walk the knowledge graph from a starting node                       |
| `vault_lint_tool`          | Run the vault hygiene linter, return JSON report                    |
| `vault_create_note`        | Create a new `Notes/{slug}.md` with proper frontmatter              |
| `vault_append_journal`     | Append a timestamped entry to today's journal                       |
| `vault_history`            | Read recent routine/pipeline execution records                      |

## Resources exposed

| URI                  | Contents                                                   |
|----------------------|-------------------------------------------------------------|
| `vault://routines`   | Auto-rendered list of all routines + pipelines              |
| `vault://skills`     | Auto-rendered list of all skills                            |
| `vault://graph`      | Raw `vault/.graphs/graph.json`                              |

## Filter expression syntax

Same as the bot's `/find` command:

| Expression                          | Meaning                                          |
|-------------------------------------|--------------------------------------------------|
| `type=routine`                      | Equality                                         |
| `type=routine enabled=true`         | AND of multiple filters                          |
| `tags__contains=publish`            | Substring/list membership                        |
| `model__in=[opus, sonnet]`          | Value is in this list                            |
| `trigger__exists=true`              | Field is present in frontmatter                  |
| `title__startswith=Crypto`          | Prefix match                                     |
| `path__endswith=.md`                | Suffix match                                     |

## Distribution note

This sidecar is **completely optional**. The main `claude-bot.sh` install
flow does not touch `mcp-server/`. New users running the bot for the first
time can ignore this directory entirely. Only opt in if you specifically
want to query/edit the vault from another MCP client.
