# Claude Bot — Development Guide

**IMPORTANTE:** Este eh o CLAUDE.md de DESENVOLVIMENTO do projeto claude-bot. Ele contem instrucoes para quem esta trabalhando no codigo do bot (Python, Swift, shell scripts). Para a knowledge base operacional do bot (vault, rotinas, agentes, journal), ver `vault/CLAUDE.md`.

## Overview

Telegram bot that provides remote access to [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) via Telegram messages. Pure Python (stdlib only), runs as a macOS launchd service.

## Architecture

```
User ↔ Telegram API ↔ claude-fallback-bot.py ↔ Claude Code CLI (subprocess)
```

### Files

| File | Purpose |
|------|---------|
| `claude-fallback-bot.py` | Main bot — Telegram polling, session management, Claude CLI orchestration |
| `claude-bot-menubar.py` | macOS menu bar indicator (requires `rumps`) |
| `claude-bot.sh` | Service manager — install/uninstall/start/stop/restart/status/logs |
| `com.vr.claude-bot.plist` | launchd template for the bot (uses `__HOME__`/`__SCRIPT_DIR__` placeholders) |
| `com.vr.claude-bot-menubar.plist` | launchd template for the menu bar app |

### Runtime Data

All runtime data is stored in `~/.claude-bot/`:
- `sessions.json` — Session persistence (names, IDs, models, agents, message counts)
- `bot.log` — Application log (rotating, 5MB × 3 backups)
- `launchd-stdout.log` / `launchd-stderr.log` — Process output
- `routines-state/YYYY-MM-DD.json` — Estado diario de execucao de rotinas

Quando precisar diagnosticar problemas do bot, ler `~/.claude-bot/bot.log` (ultimas ~50 linhas).

### Key Classes

- **`Session`** (dataclass) — Holds session state: name, claude session ID, model, workspace, message count
- **`SessionManager`** — CRUD for sessions, persists to `sessions.json`
- **`ClaudeRunner`** — Spawns Claude CLI as subprocess, handles streaming JSON output, cancellation (SIGINT → SIGTERM → SIGKILL)
- **`ClaudeTelegramBot`** — Main orchestrator: Telegram long-polling, command routing, inline keyboards, message splitting

### How Claude CLI is Invoked

```python
subprocess.Popen([
    claude_path, "--output-format", "stream-json",
    "--model", model, "--verbose",
    "--session-id", session_id,  # or omitted for new sessions
    "--resume",                  # resumes existing session
    "-p", prompt,
], cwd=workspace)
```

The `--resume` flag enables real session persistence (Claude maintains context across messages).

**Workspace padrao:** `vault/` — o bot opera dentro do vault por padrao. Agentes mudam o cwd para `vault/Agents/{id}/`. O Claude CLI carrega CLAUDE.md walking up da hierarquia, entao:
- Sessao normal: `vault/CLAUDE.md` (primario) + este arquivo (pai)
- Agente ativo: `Agents/{id}/CLAUDE.md` + `vault/CLAUDE.md` + este arquivo

## Configuration

Este projeto usa **dois arquivos `.env` com propositos distintos** — nao os confunda:

### `~/claude-bot/.env` — Config operacional do bot

Lido pelo `claude-fallback-bot.py` na inicializacao e pelo ClaudeBotManager (app macOS). Contem credenciais e caminhos necessarios para o bot funcionar:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | — | Telegram bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Yes | — | Authorized Telegram chat ID |
| `CLAUDE_PATH` | No | `/opt/homebrew/bin/claude` | Path to Claude CLI binary |
| `CLAUDE_WORKSPACE` | No | `vault/` | Working directory for Claude sessions |

**Editado via:** ClaudeBotManager → Settings, ou diretamente no arquivo.

### `vault/.env` — API keys para tarefas do vault

Lido pelo Claude Code quando executa tarefas no contexto do vault (rotinas, sessoes interativas). Contem chaves para servicos externos que o Claude pode precisar acessar:

- `NOTION_API_KEY` — Notion integration
- `FIGMA_TOKEN` — Figma MCP
- Outras chaves de APIs externas conforme necessario

**Nao contem** credenciais do Telegram nem caminhos do bot.

**Por que separados?** `vault/` pode ser sincronizado (iCloud, Git) — misturar tokens do Telegram com API keys de terceiros seria risco de seguranca desnecessario. O bot ops config fica local; as keys de workspace ficam no vault.

## Bot Commands

| Command | Description |
|---------|-------------|
| `/start`, `/help` | Show help |
| `/status` | Session & process info |
| `/sonnet`, `/opus`, `/haiku` | Quick model switch |
| `/model` | Model picker (inline keyboard) |
| `/new [name]` | Create new session |
| `/sessions` | List all sessions |
| `/switch <name>` | Switch session |
| `/delete <name>` | Delete session |
| `/compact` | Auto-compact context |
| `/stop` | Cancel running task |
| `/timeout <sec>` | Change timeout |
| `/workspace <path>` | Change working directory |
| `/effort <low\|medium\|high>` | Set reasoning effort |
| `/clear` | Reset current session |

## Development Guidelines

- **No pip dependencies** for the main bot (`claude-fallback-bot.py`). Only stdlib.
- The menu bar app (`claude-bot-menubar.py`) requires `rumps`.
- Telegram API calls use raw `urllib.request` (no `requests` library).
- All Telegram message edits are rate-limited (`STREAM_EDIT_INTERVAL = 3.0s`).
- Long messages are split respecting Markdown code blocks.
- The bot validates `AUTHORIZED_CHAT_ID` on every incoming message — unauthorized messages are silently ignored.
- Plist files use `__HOME__` and `__SCRIPT_DIR__` placeholders — the install script (`claude-bot.sh`) substitutes them via `sed`.

## Common Tasks

### Adding a new command

1. Add a handler method to `ClaudeTelegramBot` class
2. Register it in the `_COMMANDS` dict or add an `elif` in `_handle_command()`
3. Add it to the help text in `_cmd_start()`

### Changing default model/timeouts

Edit the constants at the top of `claude-fallback-bot.py`:
- `DEFAULT_MODEL` — default model for new sessions
- `config["timeout"]` — default timeout in seconds
- `STREAM_EDIT_INTERVAL` — seconds between Telegram message edits
- `TYPING_INTERVAL` — seconds between typing indicators

## ClaudeBotManager

App macOS nativa (SwiftUI) em `ClaudeBotManager/`. Menu bar app para gerenciar o bot:
- Dashboard com status do bot e sessoes
- Gerenciamento de agentes e rotinas
- Edicao de settings (.env)
- Visualizacao de logs

Build: `swift build` no diretorio `ClaudeBotManager/`.

## Vault

O diretorio `vault/` eh a knowledge base persistente do bot — um grafo Obsidian com Journal, Notes, Skills, Routines, e Agents. Ver `vault/CLAUDE.md` para documentacao completa da estrutura e regras do vault.

## Isolamento de contexto

O Claude Code carrega TODOS os CLAUDE.md na hierarquia de diretorios (do cwd ate a raiz + `~/.claude/CLAUDE.md`). Para que o bot use APENAS as instrucoes deste projeto:

**`.claude/settings.local.json`** (gitignored):
```json
{
  "claudeMdExcludes": [
    "/Users/SEU_USERNAME/CLAUDE.md",
    "/Users/SEU_USERNAME/.claude/CLAUDE.md"
  ]
}
```

Isso bloqueia CLAUDE.md de outros projetos (ex: OpenClaw) quando o Claude CLI roda com `cwd` dentro deste projeto.

**Separacao dev/runtime:** Este CLAUDE.md contem instrucoes de DESENVOLVIMENTO. O `vault/CLAUDE.md` contem a knowledge base OPERACIONAL do bot. Quando o bot invoca o Claude CLI com `cwd=vault/`, o Claude ve primariamente o vault/CLAUDE.md. Este arquivo (da raiz) carrega como pai na hierarquia, mas contem apenas info de desenvolvimento — nao interfere nas operacoes do bot.
