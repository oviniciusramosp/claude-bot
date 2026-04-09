---
title: Importar ou Revisar Agente Importado
description: Skill para importar agentes de sistemas externos (ex. OpenClaw) para o vault do claude-bot, ou revisar agentes previamente importados para verificar se a sintese do CLAUDE.md foi adequada. Le instruction files, config e metadata e gera a estrutura vault/Agents/{id}/ com agent.md + CLAUDE.md + Journal/.
type: skill
created: 2026-04-07
updated: 2026-04-09
trigger: "quando o usuario quiser importar um agente do OpenClaw ou de outro sistema, importar agente de outro sistema, revisar agente importado, verificar importacao, ou usar /import agent"
tags: [skill, agent, openclaw, import, automation, review]
---

# Importar ou Revisar Agente Importado

[[Skills]]

## Modos de operacao

- **Importacao** — importar agente de sistema externo (atualmente OpenClaw) para o vault
- **Revisao** — revisar agentes previamente importados para verificar se a sintese do CLAUDE.md foi adequada

## Dependencias

- Agents/Agents.md — destino dos agentes importados
- Skills/create-agent.md — formato de referencia para a estrutura gerada

## Objetivo

Migrar agentes do OpenClaw (OC) para o vault do claude-bot, traduzindo instruction files, config de modelo e metadata em uma estrutura padrao vault/Agents/{id}/.

## Passos

### 1. Listar agentes disponiveis no OpenClaw

Verificar o arquivo de config em `~/.openclaw/openclaw.json` na chave `agents.list`. Cada entrada tem:

```
{ "id": "...", "name": "...", "model": "...", "workspace": "..." }
```

Listar os agentes encontrados no arquivo de config. Apresentar ao usuario a lista com ID, nome e modelo.

### 2. Perguntar qual agente importar

Aguardar a escolha do usuario. Aceitar o ID ou o nome.

### 3. Localizar os arquivos fonte do agente

Para cada agente, os arquivos relevantes estao distribuidos em:

**Config do agente:** `~/.openclaw/openclaw.json` → `agents.list[id]`
- Campos: `id`, `name`, `model`, `workspace`, `thinkingDefault`, `reasoningDefault`
- Modelo default (se nao especificado): herda de `agents.defaults.model.primary`

**Workspace do agente:** Verificar o campo `workspace` na config do agente. Se nao existir, usar o default `~/.openclaw/workspace/`. Os workspaces especificos de cada agente estao definidos no arquivo de config.

**Instruction files:** Dentro do workspace, em `instructions/`. Estrutura tipica:
```
instructions/
  {dominio}/
    _globals.md      # Regras globais do dominio
    _style.md        # Estilo de escrita
    _apis.md         # Endpoints e ferramentas
    _notion.md       # Integracao Notion
    {role}.md        # Instrucoes por sub-agente (manager, writer, analyst, etc.)
```

**Identity e Soul:** Na raiz do workspace:
- `IDENTITY.md` — nome, emoji, vibe
- `SOUL.md` — personalidade e diretrizes de comportamento
- `USER.md` — contexto sobre o usuario
- `AGENTS.md` — regras operacionais do workspace

### 4. Ler os instruction files

Ler todos os `.md` em `instructions/` do workspace do agente (recursivo). Priorizar:
1. Arquivos com prefixo `_` (globals, style, apis) — sao contexto compartilhado
2. O arquivo `*-manager.md` — eh o orquestrador principal
3. Demais arquivos de sub-agentes — roles especificos

Tambem ler `IDENTITY.md` e `SOUL.md` do workspace para extrair personalidade.

### 5. Gerar a estrutura no vault

Criar em `vault/Agents/{id}/`:

```
vault/Agents/{id}/
  agent.md       # Metadados (frontmatter parseado pelo bot)
  CLAUDE.md      # Instrucoes sintetizadas
  Journal/       # Diretorio para journal proprio
```

#### 5a. Gerar agent.md

```yaml
---
title: {name}
description: {descricao curta baseada nos instruction files}
type: agent
created: {YYYY-MM-DD}
updated: {YYYY-MM-DD}
tags: [agent, imported, openclaw, {tags de especializacao}]
name: {name}
personality: {extraido de IDENTITY.md e SOUL.md}
model: {modelo mapeado — ver tabela abaixo}
icon: "{emoji do IDENTITY.md ou inferido}"
default: {true se id == "main", senao false}
source: openclaw
source_id: {id original no OC}
source_workspace: {path do workspace OC}
---

[[Agents]]
```

#### 5b. Gerar CLAUDE.md

Sintetizar os instruction files em um CLAUDE.md limpo. NAO copiar verbatim — reorganizar em:

```markdown
# {name}

## Personalidade
{Sintetizado de IDENTITY.md + SOUL.md do workspace}

## Instrucoes
- Registrar conversas no Journal proprio: Journal/YYYY-MM-DD.md
- {instrucoes principais extraidas dos instruction files}

## Especializacoes
- {lista de areas de foco, baseada nos sub-agentes e dominios}

## Sub-agentes originais (referencia)
{Lista dos sub-agentes do OC com descricao curta de cada um, para referencia.
Nao replicar toda a logica — apenas documentar quem fazia o que.}

## Fontes de dados
{APIs, endpoints, ferramentas extraidos dos instruction files _apis.md/_notion.md}
```

O CLAUDE.md do agente NAO precisa repetir regras do vault (frontmatter, wikilinks, etc.) — essas vem do CLAUDE.md pai em ~/claude-bot/.

#### 5c. Criar Journal/

Diretorio vazio. O agente comecara a registrar a partir da primeira sessao.

### 6. Mapear modelo

Usar a tabela de mapeamento (ver secao Notas) para converter o modelo OC para o modelo claude-bot.

### 7. Atualizar o index

Editar `vault/Agents/Agents.md` e adicionar: `- [[{id}]] — {descricao curta} (importado do OpenClaw)`

### 8. Registrar no Journal global

Appendar no journal do dia:
```markdown
## HH:MM — Agente importado do OpenClaw

- Agente [[{id}]] importado do OpenClaw via [[import-agent]]
- Fonte: {workspace path}
- Modelo mapeado: {OC model} -> {vault model}
- {N} instruction files processados

---
```

### 9. Confirmar

Informar ao usuario:
- O agente foi criado em `vault/Agents/{id}/`
- Quantos instruction files foram processados
- Qual modelo foi mapeado
- Como ativar: `/agent {nome}` no Telegram
- Sugerir revisar o CLAUDE.md gerado para ajustes

## Notas

### Tabela de mapeamento de modelos

| Alias OC | Modelo OC | Modelo claude-bot | Notas |
|---|---|---|---|
| perfil-escrita | zai/glm-5.1 | sonnet | Modelo primario OC -> default do bot |
| perfil-glm-5 | zai/glm-5 | sonnet | Deep-llm, mapeia para sonnet |
| perfil-glm-flash | zai/glm-4.7-flash | haiku | Light-llm, FREE |
| perfil-glm-free | zai/glm-4.5-flash | haiku | Light-llm, FREE |
| perfil-opus | anthropic/claude-opus-4-6 | opus | Mapeamento direto |
| perfil-sonnet | anthropic/claude-sonnet-4-6 | sonnet | Mapeamento direto |
| perfil-haiku | anthropic/claude-haiku-4-5 | haiku | Mapeamento direto |
| perfil-codex | openai-codex/gpt-5.4 | sonnet | Sem equivalente direto |
| perfil-flash | google/gemini-2.0-flash | haiku | Light-llm |
| perfil-leve | ollama/jarvis-local | haiku | Ultimo recurso |

Se o agente herda o modelo default (`agents.defaults.model.primary`), usar `sonnet`.

> **Nota:** Esta tabela reflete os modelos disponiveis na data de criacao. Verificar se ha modelos novos ou descontinuados antes de usar.

## Modo Revisao

Acionado quando o usuario pede para revisar agentes importados ou verificar se a importacao ficou adequada.

### Passo 1 — Identificar agentes importados

Listar agentes em `vault/Agents/` que tem `source: openclaw` (ou outro source) no frontmatter do `agent.md`.

### Passo 2 — Analisar cada agente importado

Para cada agente, ler `agent.md`, `CLAUDE.md`, e o Journal. Avaliar com o checklist:

#### A. Qualidade da sintese

- [ ] O CLAUDE.md captura a essencia dos instruction files originais?
- [ ] Informacoes importantes foram perdidas na sintese? (comparar com `source_workspace` se acessivel)
- [ ] O CLAUDE.md esta muito longo (>200 linhas)? Pode ser condensado?
- [ ] O CLAUDE.md esta muito curto? Faltam instrucoes que existiam no original?

#### B. Modelo e personalidade

- [ ] O modelo mapeado faz sentido para o uso real do agente?
- [ ] A personalidade extraida de IDENTITY.md/SOUL.md ficou fiel?
- [ ] O icone representa bem o agente?

#### C. Uso pos-importacao

- [ ] O agente tem entradas no Journal? (esta sendo usado?)
- [ ] Se esta em uso — o usuario encontrou problemas que requerem ajuste no CLAUDE.md?
- [ ] Se NAO esta em uso — o agente eh relevante? Sugerir desativar ou remover.

#### D. Integracao com o vault

- [ ] O agente tem rotinas associadas? Se nao e deveria → sugerir criar via [[create-routine]]
- [ ] Skills do OC que este agente usava foram recriadas no vault?
- [ ] Cron jobs do OC que este agente tinha foram convertidos em rotinas?

### Passo 3 — Apresentar recomendacoes

```
### {nome-do-agente} (importado de {source})
Status: OK / Melhorias sugeridas

- [melhoria 1]: motivo e beneficio
- [melhoria 2]: motivo e beneficio
```

### Passo 4 — Executar melhorias aprovadas

- **Melhorar CLAUDE.md** → re-sintetizar a partir dos instruction files originais (se acessiveis)
- **Ajustar modelo** → editar `agent.md`
- **Criar rotinas** → redirecionar para [[create-routine]] com `agent: {id}`
- **Recriar skills do OC** → usar formato vault `Skills/{nome}.md`

### Passo 5 — Registrar no Journal

Appendar no journal do dia com as mudancas aplicadas.

---

### Caveats

- **Sub-agentes nao migram 1:1.** O OC usa pipelines multi-agente (manager -> writer -> reviewer). O vault consolida em um agente unico. → Se o workflow original era complexo, sugerir criar uma **pipeline** via [[create-pipeline]] para replicar a orquestracao.
- **Instruction files com prefixo `_` sao contexto compartilhado** (_globals, _style, _apis, _notion). Devem ser incorporados no CLAUDE.md, nao ignorados.
- **Cron jobs e schedules do OC nao migram automaticamente.** → Apos importar, perguntar ao usuario se quer criar rotinas para este agente usando [[create-routine]] com `agent: {id}`.
- **Memory do OC nao eh importada.** Os arquivos em `memory/` sao historicos e nao migram. → Se houver contexto critico em memory/, sugerir criar uma nota em `vault/Notes/` com o conteudo relevante.
- **Skills do OC devem ser recriadas** como vault skills em `Skills/{nome}.md`. → Listar as skills que o agente usava no OC e perguntar se o usuario quer recriar alguma.
- **O campo `source_workspace` no agent.md** preserva a referencia ao workspace OC original para consulta futura dos instruction files detalhados.
