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
runner.run(
    prompt=prompt,
    model=model,
    session_id=session_id,      # None for fresh sessions (routines always use None)
    workspace=workspace,        # cwd for the subprocess
    system_prompt=SYSTEM_PROMPT # None when minimal_context=True
)
```

O `ClaudeRunner` monta o comando com `--print --dangerously-skip-permissions --output-format stream-json`. O `--append-system-prompt` instrui o Claude a ler o vault (Journal, Tooling, etc.) — pode ser omitido via `system_prompt=None` quando a rotina usa `context: minimal`.

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

## Versionamento e Commits

### Bumpar a versão

O projeto usa **Semantic Versioning** (MAJOR.MINOR.PATCH). A versão vive em dois lugares — sempre atualizar os dois juntos:

1. `claude-fallback-bot.py`, linha `BOT_VERSION = "X.Y.Z"` — adicionar comentário descritivo
2. `ClaudeBotManager/Sources/App/Info.plist`, campo `CFBundleShortVersionString`

Critérios:
- **PATCH** (2.0.0 → 2.0.1) — bug fix, ajuste de prompt, mudança de configuração
- **MINOR** (2.0.0 → 2.1.0) — nova feature, mudança de comportamento, refactoring estrutural
- **MAJOR** (2.0.0 → 3.0.0) — breaking change na API do bot, redesign de sessões/workspace

### Quando commitar

**Commitar proativamente** após cada mudança coerente — não acumular alterações não relacionadas num commit só.

Fazer commit imediatamente após:
- Qualquer mudança em `claude-fallback-bot.py` (corrigir bug, adicionar comando, mudar constante)
- Criação ou edição de skill, rotina, ou agent no vault
- Mudança em CLAUDE.md (raiz ou vault)
- Mudança em configuração (`.env`, plist, `settings.local.json`)

Sequência padrão:
```bash
# 1. Bumpar versão (se mudança relevante)
# 2. Verificar sintaxe
python3 -m py_compile claude-fallback-bot.py

# 3. Commitar
git add claude-fallback-bot.py vault/CLAUDE.md CLAUDE.md  # arquivos específicos
git commit -m "tipo: descrição concisa"
```

Formato da mensagem de commit:
- `feat: adiciona comando /foo`
- `fix: corrige timeout em sessões com agente`
- `refactor: separa CLAUDE.md em dev/runtime`
- `chore: bump version 2.0.0 → 2.1.0`

## Routines

### Frontmatter fields

| Campo | Tipo | Default | Descricao |
|-------|------|---------|-----------|
| `type` | string | `routine` | `routine` ou `pipeline` |
| `schedule.times` | list | — | Horarios HH:MM (24h) |
| `schedule.days` | list | `["*"]` | Dias da semana ou `["*"]` para todos |
| `schedule.until` | string | — | Data limite YYYY-MM-DD (opcional) |
| `model` | string | `sonnet` | Modelo a usar |
| `agent` | string | — | Agente para rotear a execucao |
| `enabled` | bool | `true` | Ativa/desativa a rotina |
| `context` | string | `full` | `minimal` = pula system prompt do vault, usa apenas CLAUDE.md |
| `notify` | string | `final` | Pipeline only: `final\|all\|summary\|none` |

### Contexto minimal vs full

- **`full`** (default): O Claude recebe o `SYSTEM_PROMPT` que instrui a ler Journal, Tooling, vault. Bom para rotinas que precisam de contexto do vault.
- **`minimal`**: O `--append-system-prompt` eh omitido. O Claude roda apenas com os CLAUDE.md da hierarquia de diretorios (automatico pelo CLI). Economiza tokens e eh mais rapido para tarefas pontuais.

### Pipeline notifications

Pipelines notificam via `_notify_success` / `_notify_failure`. O step marcado com `output: telegram` tem seu output enviado ao Telegram. O campo `notify` controla:
- `final` — envia output do step marcado (ou ultimo step) ao completar
- `all` — envia progresso a cada step completado
- `summary` — envia resumo compacto (X/Y steps in Nm Ns)
- `none` — silencioso (falhas sempre notificam)

### Rotina `NO_REPLY`

Se o output de uma rotina (nao pipeline) for exatamente `NO_REPLY`, o bot nao envia nada ao Telegram. Usado para rotinas que enviam mensagens manualmente ou que devem rodar em silencio.

### Rotinas built-in (commitadas no repo)

| Rotina | Descricao |
|--------|-----------|
| `update-check` | Verifica diariamente se ha updates do Claude Code CLI (brew) ou do repo (git). Notifica apenas quando ha algo para atualizar. |

## ClaudeBotManager

App macOS nativa (SwiftUI) em `ClaudeBotManager/`. Menu bar app para gerenciar o bot:
- Dashboard com status do bot e sessoes
- Gerenciamento de agentes, rotinas e skills
- Delete via Lixeira do macOS (restauravel pelo Finder)
- Toggle de contexto minimal para rotinas
- Edicao de settings (.env)
- Visualizacao de logs

Build com Xcode toolchain (requer macOS 26 SDK):
```bash
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer \
  /Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/swift build \
  --package-path ClaudeBotManager
```

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
