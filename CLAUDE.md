# Claude Bot — Project Knowledge Base

**IMPORTANTE:** Este eh o CLAUDE.md do projeto claude-bot. Quando o bot invoca o Claude CLI com `cwd=~/claude-bot/`, este arquivo eh a fonte primaria de instrucoes. Para isolar o bot de outros projetos (ex: OpenClaw), crie `.claude/settings.local.json` com `claudeMdExcludes` apontando para CLAUDE.md de outros projetos. Ver secao "Isolamento de contexto" abaixo.

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
- `sessions.json` — Session persistence (names, IDs, models, agents, message counts). Consultar para contexto de sessoes anteriores.
- `bot.log` — Application log (rotating, 5MB × 3 backups). Consultar para diagnosticar erros.
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

## Configuration

Este projeto usa **dois arquivos `.env` com propositos distintos** — nao os confunda:

### `~/claude-bot/.env` — Config operacional do bot

Lido pelo `claude-fallback-bot.py` na inicializacao e pelo ClaudeBotManager (app macOS). Contem credenciais e caminhos necessarios para o bot funcionar:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | — | Telegram bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Yes | — | Authorized Telegram chat ID |
| `CLAUDE_PATH` | No | `/opt/homebrew/bin/claude` | Path to Claude CLI binary |
| `CLAUDE_WORKSPACE` | No | `$HOME` | Working directory for Claude sessions |

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

---

## Vault — Knowledge Base Persistente

O diretorio `vault/` eh a knowledge base do projeto — um grafo de conhecimento Obsidian que cresce incrementalmente a cada sessao. O usuario pode se referir a ele como **"vault"**, **"knowledge base"**, **"knowledge"**, ou **"KB"**. Todos significam a mesma coisa: `vault/`.

Ele eh tanto a memoria de longo prazo do bot quanto um workspace visual para o usuario navegar no Obsidian via Graph View.

### Como consumir o vault

**Principio: scan antes de ler.** Nunca abrir todos os arquivos de uma pasta. Primeiro listar os arquivos e ler apenas as primeiras ~10 linhas (frontmatter) de cada. Usar o campo `description` para decidir quais merecem leitura completa.

Ao iniciar qualquer sessao:
1. Glob `vault/Journal/*.md` — ler os ultimos 2-3 dias para contexto recente
2. Ler `vault/Tooling.md` — preferencias de ferramentas (qual usar para cada tarefa)
3. Se o usuario mencionar um topico, listar `vault/Notes/` e ler frontmatters para filtrar por `description` e `tags` antes de abrir arquivos inteiros
4. Se uma skill for acionada, ler `vault/Skills/<skill>.md` para instrucoes
5. Se uma rotina for acionada, ler `vault/Routines/<rotina>.md` para o prompt e contexto

**Navegacao eficiente em pastas grandes:**
- Listar arquivos → ler primeiras 10 linhas de cada → filtrar por `description`/`tags` → abrir somente os relevantes
- Tratar a colecao de frontmatters como um catalogo navegavel
- O campo `description` substitui a necessidade de ler o corpo do arquivo na maioria dos casos

### Regra inquebravel: Frontmatter YAML

Todo `.md` no vault DEVE ter frontmatter. Sem excecao. Criar sem frontmatter eh um erro.

```yaml
---
title: Nome descritivo
description: Frase curta explicando o conteudo e quando este arquivo eh relevante.
type: journal | note | skill | reference | routine
created: YYYY-MM-DD
updated: YYYY-MM-DD
tags: [topico1, topico2]
---
```

O campo `description` eh obrigatorio e funciona como indice semantico. Deve conter contexto suficiente para decidir se o arquivo precisa ser lido inteiro ou nao.

### Estrutura do grafo

O vault eh um **grafo em arvore limpa**. O Obsidian Graph View eh a forma principal do usuario navegar. O chart deve ser limpo, com conexoes claras e sem links desnecessarios.

```
README (hub raiz)
  ├── Journal (index) → entradas diarias
  ├── Notes (index) → notas individuais
  ├── Skills (index) → skills individuais
  ├── Routines (index) → rotinas individuais
  ├── Agents (index) → agentes individuais
  └── Tooling (folha terminal)
```

**Regras de linkagem:**

| Tipo | Outlinks | Inlinks |
|------|----------|---------|
| README | indexes + Tooling | nenhum (raiz) |
| Index | seus filhos diretos | README |
| Leaf (skill, rotina, nota) | `[[IndexPai]]` na primeira linha + cross-links genuinos | seu index |
| Agente | `{id}.md` com links internos | Agents index |
| Journal entry | `[[Journal]]` ou `[[{agent}/Journal\|Journal]]` | Journal index |
| Tooling | nenhum (terminal) | README |

**Principio central: nem toda mencao precisa ser um `[[link]]`.** Links existem para criar conexoes NO GRAFO do Obsidian. Se a conexao nao agrega visualmente, nao linke. Use texto plano.

**Proibido:**
- README linkar para folhas (sempre via index)
- Indexes linkarem entre si
- Dois arquivos terem multiplas conexoes
- Links decorativos ou "relacionados"
- Journal entries criarem wikilinks para tudo que mencionam (polui o grafo)

### Index files (MOCs)

Cada pasta tem um index que funciona como hub no grafo:

- `vault/README.md` → hub raiz
- `vault/Journal/Journal.md`, `vault/Notes/Notes.md`, `vault/Skills/Skills.md`, `vault/Routines/Routines.md`, `vault/Agents/Agents.md`

Regras: lista APENAS filhos diretos. Nunca linka para outros indexes.

### Criando arquivos no vault

**1. Frontmatter completo:**
```yaml
---
title: Nome
description: Frase curta sobre conteudo e relevancia.
type: (note|skill|routine|agent|journal|reference|index)
created: YYYY-MM-DD
updated: YYYY-MM-DD
tags: [tag1, tag2]
---
```

**2. Primeira linha do body = link para index pai:**
Skill → `[[Skills]]`, Rotina → `[[Routines]]`, Nota → `[[Notes]]`

**3. Cross-links somente para dependencias reais.** Na duvida, nao linkar.

**4. Atualizar o index da pasta** com `- [[novo-arquivo]] — descricao`

**5. Registrar no Journal do dia** (sem criar wikilink para o arquivo novo — mencionar em texto plano)

### Wikilinks — quando usar

**Criar link quando:**
- Primeira linha do body → `[[IndexPai]]`
- Referenciar pasta interna de agente → `[[{id}/Journal|Journal]]`
- Skill depende de outro arquivo → `[[arquivo-alvo]]`

**NAO criar link quando:**
- Mencionar algo no Journal (usar texto plano, nao `[[link]]`)
- Referenciar Tooling de dentro de folhas
- Mencionar algo "relacionado" que nao eh dependencia real
- Citar uma entidade por contexto sem dependencia

**Sintaxe:**
- `[[nome-do-arquivo]]` — link simples
- `[[pasta/subpasta/arquivo|Texto visivel]]` — com alias (para referenciar pastas)
- `[[nome#secao]]` — para secoes

### Journal (`vault/Journal/`)

Um arquivo por dia: `YYYY-MM-DD.md`. Append-only.

```yaml
---
title: "Journal YYYY-MM-DD"
description: Registro do dia YYYY-MM-DD.
type: journal
created: YYYY-MM-DD
updated: YYYY-MM-DD
tags: [journal]
---

[[Journal]]
```

Formato de entrada:
```markdown
## HH:MM — Resumo curto

- Topicos discutidos
- Decisoes tomadas
- Acoes realizadas

---
```

**Journal NAO cria wikilinks para entidades mencionadas.** O formato do arquivo e sua localizacao na pasta sao suficientes para o grafo. Isso mantem o chart limpo.

Para journals de agentes, primeira linha: `[[{agent-id}/Journal|Journal]]`

### Notes (`vault/Notes/`)

Knowledge base incremental. Cada nota eh um no do grafo.

- Nomes em kebab-case
- Nunca deletar conteudo — adicionar ou atualizar
- Tags no frontmatter para busca
- Primeira linha: `[[Notes]]`

### Skills (`vault/Skills/`)

Cada skill eh um .md com instrucoes procedurais.

```yaml
---
title: Nome da Skill
description: O que faz e quando usar.
type: skill
trigger: "quando o usuario pedir X"
tags: [skill, categoria]
---

[[Skills]]

## Objetivo
...

## Passos
1. ...

## Notas
...
```

Cross-links somente para pastas-alvo da skill (ex: `[[Routines]]` se a skill cria rotinas).

### Routines (`vault/Routines/`)

Rotinas agendadas que executam prompts no Claude Code automaticamente.

Cada rotina eh um `.md` com frontmatter de schedule + prompt no body:

```yaml
---
title: Nome da Rotina
description: O que esta rotina faz e quando eh relevante.
type: routine
created: YYYY-MM-DD
updated: YYYY-MM-DD
tags: [routine, categoria]
schedule:
  times: ["09:00", "18:00"]
  days: [mon, tue, wed, thu, fri]
  until: "2026-12-31"
model: sonnet
enabled: true
---

[[Routines]]

Prompt que sera enviado ao Claude Code...
```

**Campos do schedule:**
- `times` — horarios HH:MM (24h, horario local)
- `days` — dias da semana: mon/tue/wed/thu/fri/sat/sun, ou `["*"]` para todos
- `until` — data limite YYYY-MM-DD (opcional)
- `model` — modelo a usar (sonnet/opus/haiku)
- `enabled` — true/false

**Criacao de rotinas:**
- Via Telegram: comando `/routine` dispara a skill [[create-routine]]
- Via Claude Code: criar arquivo .md diretamente em `vault/Routines/`
- Nome do arquivo em kebab-case: `relatorio-matinal.md`

**Execucao:**
- O scheduler do bot verifica rotinas a cada 60 segundos
- Rotinas executadas recebem contexto do vault (Tooling, .env, Skills)
- Toda execucao gera um registro no Journal do dia com link `[[rotina-nome]]`
- Rotinas nao bloqueiam mensagens do usuario — entram na fila
- Rotinas podem ser direcionadas a agentes com o campo `agent: {id}` no frontmatter

### Agents (`vault/Agents/`)

Agentes especializados com workspace proprio. Cada agente eh um diretorio com 3 arquivos + Journal.

```
vault/Agents/{id}/
  agent.md       # Metadados (frontmatter parseado pelo bot, body vazio)
  CLAUDE.md      # Instrucoes para Claude Code (SEM frontmatter, SEM wikilinks)
  {id}.md        # Hub de links internos do agente no grafo
  Journal/       # Journal proprio do agente
```

**agent.md** — metadados parseados pelo bot. Body vazio:
```yaml
---
title: Nome
description: Descricao curta
type: agent
name: Nome Legivel
personality: Tom e estilo
model: sonnet
icon: "🤖"
---
```

**CLAUDE.md** — instrucoes lidas pelo Claude Code quando o agente esta ativo. NAO tem frontmatter. NAO tem wikilinks. Contem apenas:
```markdown
# {Nome} {emoji}

## Personalidade
{descricao do tom e estilo}

## Instrucoes
- Registrar conversas no Journal proprio: Journal/YYYY-MM-DD.md
- {instrucoes especificas}

## Especializacoes
- {areas de foco}
```

**{id}.md** — hub do agente no grafo Obsidian. Contem links internos:
```markdown
[[{id}/Journal|Journal]]
[[agent]]
[[CLAUDE]]
```

**Workspace:** quando ativo, `cwd` muda para `vault/Agents/{id}/`. Claude le o CLAUDE.md do agente + o CLAUDE.md do projeto (hierarquia automatica).

**Criacao:** `/agent new` ou `/agent import` no Telegram.

### Images (`vault/Images/`)

Imagens do Telegram chegam como arquivos temporarios em `/tmp/claude-bot-images/`. Analise-as normalmente.

**Salvar no vault somente quando o usuario pedir explicitamente** (ex: "guarde essa imagem", "salva isso").

Ao salvar, organizar em subpastas tematicas:
```
Images/
├── screenshots/
├── diagramas/
├── referencias/
└── ...
```

Registrar no Journal quando salvar: `Imagem salva em [[Images/subpasta/nome.ext]]`.

### Credenciais (`vault/.env`)

Ler com o Read tool quando precisar de API keys ou tokens para acessar servicos externos. O arquivo contem variaveis como `NOTION_API_KEY`, `FIGMA_TOKEN`, etc.

### Ferramentas (`vault/Tooling.md`)

Mapa de preferencias: qual ferramenta usar para cada tipo de tarefa. Consultar antes de escolher uma abordagem. Exemplo: usar PinchTab para web (evitar fingerprint), Figma MCP para design.

### Principios de escrita para o grafo

1. **Atomicidade** — cada nota sobre um unico conceito. Melhor 3 notas curtas linkadas que 1 nota longa.
2. **Links intencionais** — linkar APENAS dependencias reais. Nao linkar por cortesia. Menos links = grafo mais legivel.
3. **Discoverability** — tags no frontmatter para busca. `## Relacionados` somente em notas (nunca em indexes).
4. **Estabilidade** — nomes de arquivo sao permalinks. Renomear quebra links. Escolha bem na criacao.
5. **Incrementalidade** — nunca apagar, sempre adicionar. O historico de evolucao de uma nota tem valor.
6. **Arvore primeiro** — o grafo eh uma arvore (README → Index → Folha). Cross-links sao excecao, nao regra.

---

## Isolamento de contexto

O Claude Code carrega TODOS os CLAUDE.md na hierarquia de diretorios (do cwd ate a raiz + `~/.claude/CLAUDE.md`). Para que o bot use APENAS as instrucoes deste projeto, crie:

**`.claude/settings.local.json`** (gitignored):
```json
{
  "claudeMdExcludes": [
    "/Users/SEU_USERNAME/CLAUDE.md",
    "/Users/SEU_USERNAME/.claude/CLAUDE.md"
  ]
}
```

Isso bloqueia CLAUDE.md de outros projetos (ex: OpenClaw) quando o Claude CLI roda com `cwd=~/claude-bot/`. Outros projetos nao sao afetados.

Sem isso, o Claude vera instrucoes de TODOS os CLAUDE.md pai, o que pode causar confusao (ex: encontrar agentes de outros sistemas, seguir instrucoes de modelos errados).
