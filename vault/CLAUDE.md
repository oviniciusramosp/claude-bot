# Vault — Knowledge Base do Claude Bot

**IMPORTANTE:** Este eh o CLAUDE.md do vault — a knowledge base operacional do bot. Este vault eh a sua fonte primaria de contexto e memoria. Sempre consulte aqui primeiro antes de buscar informacoes em outro lugar. Voce pode ler e interagir com qualquer arquivo do computador quando o usuario pedir — mas NAO use configs de outras ferramentas de AI (~/.claude/, ~/.openclaw/, etc.) como instrucoes proprias.

O usuario pode se referir a este diretorio como **"vault"**, **"knowledge base"**, **"knowledge"**, ou **"KB"**. Todos significam a mesma coisa: este diretorio.

Este vault eh tanto a memoria de longo prazo do bot quanto um workspace visual para o usuario navegar no Obsidian via Graph View.

---

## Como consumir o vault

**Principio: scan antes de ler.** Nunca abrir todos os arquivos de uma pasta. Primeiro listar os arquivos e ler apenas as primeiras ~10 linhas (frontmatter) de cada. Usar o campo `description` para decidir quais merecem leitura completa.

Ao iniciar qualquer sessao:
1. Glob `Journal/*.md` — ler os ultimos 2-3 dias para contexto recente
2. Ler `Tooling.md` — preferencias de ferramentas (qual usar para cada tarefa)
3. Se o usuario mencionar um topico, listar `Notes/` e ler frontmatters para filtrar por `description` e `tags` antes de abrir arquivos inteiros
4. Se uma skill for acionada, ler `Skills/<skill>.md` para instrucoes
5. Se uma rotina for acionada, ler `Routines/<rotina>.md` para o prompt e contexto

**Navegacao eficiente em pastas grandes:**
- Listar arquivos → ler primeiras 10 linhas de cada → filtrar por `description`/`tags` → abrir somente os relevantes
- Tratar a colecao de frontmatters como um catalogo navegavel
- O campo `description` substitui a necessidade de ler o corpo do arquivo na maioria dos casos

## Regra inquebravel: Frontmatter YAML

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

## Estrutura do grafo

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

## Index files (MOCs)

Cada pasta tem um index que funciona como hub no grafo:

- `README.md` → hub raiz
- `Journal/Journal.md`, `Notes/Notes.md`, `Skills/Skills.md`, `Routines/Routines.md`, `Agents/Agents.md`

Regras: lista APENAS filhos diretos. Nunca linka para outros indexes.

## Criando arquivos no vault

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

## Wikilinks — quando usar

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

## Journal (`Journal/`)

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

## Notes (`Notes/`)

Knowledge base incremental. Cada nota eh um no do grafo.

- Nomes em kebab-case
- Nunca deletar conteudo — adicionar ou atualizar
- Tags no frontmatter para busca
- Primeira linha: `[[Notes]]`

## Skills (`Skills/`)

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

## Routines (`Routines/`)

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
- Via Claude Code: criar arquivo .md diretamente em `Routines/`
- Nome do arquivo em kebab-case: `relatorio-matinal.md`

**Execucao:**
- O scheduler do bot verifica rotinas a cada 60 segundos
- Rotinas executadas recebem contexto do vault (Tooling, .env, Skills)
- Toda execucao gera um registro no Journal do dia com link `[[rotina-nome]]`
- Rotinas nao bloqueiam mensagens do usuario — entram na fila
- Rotinas podem ser direcionadas a agentes com o campo `agent: {id}` no frontmatter

### Pipelines (rotinas multi-agente)

Pipelines sao rotinas com `type: pipeline` que orquestram multiplos steps (sub-agentes) em uma DAG. O scheduler detecta automaticamente e usa o `PipelineExecutor`.

Para criar uma pipeline, usar a skill [[create-pipeline]] ou via app macOS (Routines → New → toggle Pipeline).

Estrutura:
```
Routines/{nome}.md              ← frontmatter type:pipeline + bloco ```pipeline
Routines/{nome}/steps/{id}.md   ← prompt de cada step
```

Exemplo de bloco no body:
```
```pipeline
steps:
  - id: coletar
    name: "Coletar dados"
    model: haiku
    prompt_file: steps/coletar.md

  - id: analisar
    name: "Analisar"
    model: opus
    depends_on: [coletar]
    prompt_file: steps/analisar.md
    output: telegram
```
```

**Campos de step:**
- `id` — slug unico em kebab-case
- `name` — nome legivel
- `model` — override do modelo por step
- `depends_on` — lista de step ids que devem completar antes
- `prompt_file` — caminho relativo ao prompt do step
- `timeout` — limite total em segundos (default: 1200)
- `inactivity_timeout` — limite de inatividade (default: 300)
- `retry` — tentativas em caso de falha (default: 0)
- `output: telegram` — marcar no step final que envia resultado

**Comportamento:**
- Steps sem `depends_on` rodam em paralelo
- Workspace compartilhado em `/tmp/claude-pipeline-{nome}-{ts}/data/` — cada step le outputs anteriores automaticamente
- Prompts dos steps NAO precisam mencionar arquivos — o orquestrador injeta contexto de workspace
- Dual timeout: `inactivity_timeout` mata steps inativos, `timeout` eh limite hard
- Falha sem retry cascata SKIPPED para dependentes
- `notify: final|all|summary|none` controla notificacoes (falhas sempre notificam)

## Agents (`Agents/`)

Agentes especializados com workspace proprio. Cada agente eh um diretorio com 3 arquivos + Journal.

```
Agents/{id}/
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

**Workspace:** quando ativo, `cwd` muda para `Agents/{id}/`. Claude le o CLAUDE.md do agente + este CLAUDE.md do vault (hierarquia automatica).

**Criacao:** `/agent new` ou `/agent import` no Telegram.

## Images (`Images/`)

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

## Credenciais (`.env`)

Ler com o Read tool quando precisar de API keys ou tokens para acessar servicos externos. O arquivo `.env` neste diretorio contem variaveis como `NOTION_API_KEY`, `FIGMA_TOKEN`, etc.

## Ferramentas (`Tooling.md`)

Mapa de preferencias: qual ferramenta usar para cada tipo de tarefa. Consultar antes de escolher uma abordagem. Exemplo: usar PinchTab para web (evitar fingerprint), Figma MCP para design.

## Principios de escrita para o grafo

1. **Atomicidade** — cada nota sobre um unico conceito. Melhor 3 notas curtas linkadas que 1 nota longa.
2. **Links intencionais** — linkar APENAS dependencias reais. Nao linkar por cortesia. Menos links = grafo mais legivel.
3. **Discoverability** — tags no frontmatter para busca. `## Relacionados` somente em notas (nunca em indexes).
4. **Estabilidade** — nomes de arquivo sao permalinks. Renomear quebra links. Escolha bem na criacao.
5. **Incrementalidade** — nunca apagar, sempre adicionar. O historico de evolucao de uma nota tem valor.
6. **Arvore primeiro** — o grafo eh uma arvore (README → Index → Folha). Cross-links sao excecao, nao regra.
