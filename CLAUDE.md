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

All configuration via environment variables (no hardcoded secrets):

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | — | Telegram bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Yes | — | Authorized Telegram chat ID |
| `CLAUDE_PATH` | No | `/opt/homebrew/bin/claude` | Path to Claude CLI binary |
| `CLAUDE_WORKSPACE` | No | `$HOME` | Working directory for Claude sessions |

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

### Regra inquebravel: Zero arquivos orfaos

O vault eh um **grafo**. O Obsidian Graph View eh a forma principal do usuario navegar e entender conexoes. Um arquivo sem links eh invisivel no grafo — um no morto que o usuario nunca encontra.

**Regra: todo arquivo .md criado DEVE ter no minimo:**
1. **Outlinks** — pelo menos 1 wikilink para outro arquivo do vault
2. **Inlink garantido** — ao criar um arquivo, TAMBEM editar ao menos 1 arquivo existente para linkar DE VOLTA ao novo

**Checklist obrigatorio ao criar qualquer arquivo:**
- [ ] O novo arquivo tem `[[wikilinks]]` para arquivos relacionados?
- [ ] Algum arquivo existente ja linka para o novo? Se nao, editar o mais relevante para adicionar o link.
- [ ] O Journal do dia registra a criacao com `[[link-para-novo-arquivo]]`?
- [ ] Se eh uma skill → adicionar link no `vault/README.md` ou em notas que a referenciam
- [ ] Se eh uma rotina → adicionar link no Journal e na nota/agent relacionado
- [ ] Se eh uma nota → adicionar secao `## Relacionados` com links bidirecionais
- [ ] Se eh um agente → linkar de `vault/README.md` e do Journal

**NUNCA** criar um .md solto sem conecta-lo ao grafo. Melhor nao criar do que criar orfao.

### Regra inquebravel: Index files (MOCs)

Cada pasta do vault tem um arquivo index (Map of Content) que funciona como **no hub** no grafo Obsidian. Pastas sao invisiveis no Graph View — somente arquivos aparecem. O index file cria a hierarquia visual.

**Index files existentes:**
- `vault/README.md` → hub raiz, linka para todos os index
- `vault/Journal/Journal.md` → lista entradas recentes
- `vault/Notes/Notes.md` → lista notas existentes
- `vault/Skills/Skills.md` → lista skills disponiveis
- `vault/Routines/Routines.md` → lista rotinas ativas
- `vault/Agents/Agents.md` → lista agentes disponiveis

**Ao criar um arquivo novo:**
1. Adicionar `Parte de [[IndexPai]].` no inicio do body (ex: `Parte de [[Routines]].`)
2. Editar o index da pasta para adicionar `[[novo-arquivo]]` na lista
3. Isso garante: `README → Routines → btc-preco-matinal` no grafo

**Ao criar um agente novo:**
1. Adicionar o agente no `vault/Agents/Agents.md`
2. O `agent.md` do agente deve ter `Parte de [[Agents]].`

**Nunca linkar diretamente do README para arquivos folha** — sempre passar pelo index da pasta.

### Procedimento completo: criando qualquer arquivo no vault

Seguir TODOS os passos abaixo ao criar qualquer .md no vault. Nao pular nenhum.

**1. Criar o arquivo com frontmatter completo:**
```yaml
---
title: Nome descritivo
description: Frase que explica o conteudo e quando eh relevante.
type: (note|skill|routine|agent|journal|reference|index)
created: YYYY-MM-DD
updated: YYYY-MM-DD
tags: [tag1, tag2]
---
```

**2. Primeira linha do body: link para o index pai (uma unica linha):**
- Se for uma skill → `[[Skills]]`
- Se for uma rotina → `[[Routines]]`
- Se for um agente → `[[Agents]]`
- Se for uma nota → `[[Notes]]`

Isso eh suficiente para conectar o arquivo ao grafo. Nao adicionar frases extras nessa linha.

**3. Outlinks adicionais — somente quando verdadeiro:**
- Linkar outros arquivos do vault APENAS se o conteudo realmente depende deles
- Exemplo: se uma rotina usa ferramentas especificas do Tooling.md, adicionar `Requires tools from Tooling.md.` (sem wikilink — o index da pasta ja linka Tooling)
- Nao inflar o body com links decorativos — cada token consumido custa na execucao

**4. Atualizar o index da pasta para listar o novo arquivo:**
- Skill criada → editar `vault/Skills/Skills.md`, adicionar `- [[novo-arquivo]] — descricao`
- Rotina criada → editar `vault/Routines/Routines.md`, adicionar na lista
- Agente criado → editar `vault/Agents/Agents.md`, adicionar na lista
- Nota criada → editar `vault/Notes/Notes.md`, adicionar na lista

**5. Registrar no Journal do dia:**
- Appendar entrada com `[[link-para-novo-arquivo]]`

**Resultado esperado no Graph View:**
```
README → [Index da pasta] → [Novo arquivo]
```
Nunca:
```
README → [Novo arquivo] (orfao sem contexto de pasta)
```

### Wikilinks — sintaxe e padroes

Usar `[[wikilinks]]` do Obsidian para conectar notas entre si.

**Sintaxe:**
- Referencia a nota: `[[nome-da-nota]]`
- Referencia a secao: `[[nome-da-nota#secao]]`
- Referencia ao journal: `[[2026-04-07]]` (nome do arquivo sem pasta)
- Referencia a skill: `[[create-routine]]`
- Referencia a rotina: `[[btc-preco-matinal]]`
- Referencia a agente: `[[jarvis]]` (nome do diretorio do agente)
- Alias para legibilidade: `[[nome-tecnico|nome legivel]]`

**Diretrizes de linkagem:**
- Journal DEVE citar toda nota/skill/rotina/agente mencionado na entrada
- Notas DEVEM ter secao `## Relacionados` no final com links bidirecionais
- Skills DEVEM linkar para `[[Tooling]]` e quaisquer dependencias
- Rotinas DEVEM linkar para o agente (se tiver) e skills referenciadas
- Agentes DEVEM linkar para `[[Tooling]]`, skills que usam, e notas relevantes
- README.md do vault DEVE listar todos os tipos de conteudo com links

**Principio:** se voce menciona algo que existe no vault, linke. Se nao existe e deveria, crie E linke.

### Journal (`vault/Journal/`)

Um arquivo por dia: `YYYY-MM-DD.md`. **Append-only** — nunca sobrescrever.

Ao criar o arquivo do dia:
```yaml
---
title: "Journal — YYYY-MM-DD"
description: Registro do dia YYYY-MM-DD. Conversas, decisoes, rotinas executadas.
type: journal
created: YYYY-MM-DD
tags: [journal]
---
```

Formato de cada entrada (appendar ao final):
```markdown
## HH:MM — Resumo curto

- Topicos discutidos (com [[wikilinks]] para notas relevantes)
- Decisoes tomadas
- Acoes realizadas
- Skills executadas → [[skill-nome]]
- Rotinas executadas → [[rotina-nome]]
- Notas criadas → [[nota-nome]]

---
```

**Toda entrada do Journal DEVE conter wikilinks** para as entidades mencionadas. O Journal eh o hub temporal do grafo — ele conecta tudo que aconteceu no dia.

Consolidacao acontece automaticamente quando o usuario usa `/new`, `/switch`, ou `/important` no Telegram. Se o bot enviar um prompt de consolidacao, registre tudo que foi relevante na sessao.

### Notes (`vault/Notes/`)

Knowledge base incremental. Cada nota eh um no do grafo.

- Nomes em kebab-case: `como-funciona-x.md`
- Nunca deletar conteudo existente — adicionar ou atualizar secoes
- Tags no frontmatter para busca rapida
- **Sempre** incluir wikilinks para notas relacionadas em uma secao `## Relacionados` no final
- Atualizar o campo `updated` no frontmatter ao modificar

Criar notas quando:
- O usuario compartilha conhecimento duravel (nao efemero)
- Uma decisao arquitetural eh tomada
- Um padrao ou processo eh estabelecido
- Uma referencia externa importante eh descoberta

### Skills (`vault/Skills/`)

Definicoes de tarefas recorrentes. Cada skill eh um .md executavel.

```yaml
---
title: Nome da Skill
type: skill
created: YYYY-MM-DD
updated: YYYY-MM-DD
trigger: "quando o usuario pedir X"
tags: [skill, categoria]
---

# Nome da Skill

## Objetivo
O que esta skill faz e quando usar.

## Dependencias
- [[Tooling]] — ferramentas necessarias
- [[nota-relevante]] — contexto

## Passos
1. ...
2. ...

## Notas
Observacoes, edge cases, historico de execucoes.
```

**Toda execucao de skill DEVE gerar um registro no Journal do dia** com link `[[skill-nome]]`.

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

Prompt que sera enviado ao Claude Code...
Pode referenciar skills: execute a skill [[nome-da-skill]].
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

Agentes especializados que vivem no vault como nos centrais do grafo Obsidian. Cada agente tem personalidade, instrucoes, modelo padrao, e journal proprio.

Estrutura de um agente:
```
vault/Agents/{id}/
  agent.md       # Identidade, personalidade, instrucoes (no central do grafo)
  Journal/       # Journal proprio do agente (YYYY-MM-DD.md)
```

Formato do `agent.md`:
```yaml
---
title: Nome do Agente
description: Frase curta sobre o agente e quando usa-lo.
type: agent
created: YYYY-MM-DD
updated: YYYY-MM-DD
tags: [agent, especializacao]
name: Nome Legivel
personality: Descricao do tom e estilo de comunicacao.
model: sonnet
icon: "🤖"
default: false
---
```

Seguido por secoes: Personalidade, Instrucoes, Especializacoes, Relacionados.

**Comportamento quando um agente esta ativo:**
- O prompt do usuario recebe contexto do agente (personalidade + instrucoes)
- Journal eh registrado em `vault/Agents/{id}/Journal/` (nao no global)
- O modelo da sessao muda para o modelo padrao do agente
- `/important` e consolidacao de sessao usam o journal do agente

**Criacao de agentes:**
- Via Telegram: `/agent new` dispara a skill [[create-agent]]
- Via Claude Code: criar diretorio e `agent.md` manualmente
- Selecao: `/agent` mostra teclado com agentes disponiveis

**Principio:** agentes sao nos do grafo, nao silos. Eles referenciam [[Tooling]], [[Notes]], [[Skills]] e outros agentes via wikilinks.

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
2. **Linkabilidade** — se voce menciona algo que ja existe como nota, linke. Se nao existe e deveria, crie.
3. **Discoverability** — tags no frontmatter + secao `## Relacionados` no final. O usuario navega o graph view.
4. **Estabilidade** — nomes de arquivo sao permalinks. Renomear quebra links. Escolha bem na criacao.
5. **Incrementalidade** — nunca apagar, sempre adicionar. O historico de evolucao de uma nota tem valor.

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
