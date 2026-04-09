---
title: Criar ou Revisar Pipeline Multi-Agente
description: Skill para criar ou revisar pipelines com multiplos steps paralelos. Analisa proativamente oportunidades de paralelismo e anti-patterns em pipelines existentes.
type: skill
created: 2026-04-08
updated: 2026-04-09
trigger: "quando o usuario quiser criar, revisar, melhorar ou otimizar uma pipeline, rotina com multiplos passos, rotina com sub-agentes, ou workflow multi-step"
tags: [skill, pipeline, routine, automation, multi-agent, review, parallelism]
---

[[Skills]]

## Modos de operacao

Esta skill opera em dois modos:

1. **Criacao** — quando o usuario quer criar uma nova pipeline
2. **Revisao** — quando o usuario quer revisar, melhorar ou otimizar pipelines existentes

Detectar o modo pelo contexto da conversa. Se ambiguo, perguntar.

---

## Modo Criacao

### O que e uma pipeline

Uma pipeline e uma rotina do tipo `type: pipeline` que orquestra multiplos steps (sub-agentes). Diferente de uma rotina simples (um prompt → um Claude → um output), a pipeline:

- Tem multiplos steps, cada um com seu proprio modelo (haiku/sonnet/opus)
- Steps podem depender de outros (`depends_on`) — respeitando uma DAG
- Steps sem dependencias rodam em paralelo automaticamente
- Todos os steps compartilham um workspace temporario (`data/`) — cada step le outputs dos anteriores e escreve o seu
- O orquestrador Python gerencia a execucao, retries e timeouts
- Apenas o step marcado com `output: telegram` envia o resultado final

### Estrutura de arquivos

```
vault/Routines/
  {nome-da-pipeline}.md              ← definicao (frontmatter + bloco ```pipeline)
  {nome-da-pipeline}/                ← pasta com prompts dos steps
    steps/
      {step-1-id}.md                 ← prompt do step 1
      {step-2-id}.md                 ← prompt do step 2
      ...
```

### Passos para criar

#### 1. Entender o objetivo

O que a pipeline deve produzir no final? Quais etapas intermediarias sao necessarias?

#### 2. Decompor em steps com paralelismo maximo

Esta e a etapa mais importante. O objetivo e maximizar paralelismo e minimizar tempo total.

**Principio: se dois steps nao dependem do output um do outro, eles DEVEM rodar em paralelo.**

Para cada step, determinar:
- `id`: slug em kebab-case (ex: `coletar-dados`, `analisar`, `escrever`)
- `name`: nome legivel (ex: "Coletar dados de mercado")
- `model`: haiku (rapido/barato), sonnet (equilibrado), opus (complexo)
- `depends_on`: lista de step ids que devem completar antes deste rodar
- `timeout`: limite total em segundos (default: 1200 = 20min)
- `inactivity_timeout`: limite de inatividade em segundos (default: 300 = 5min)
- `retry`: numero de tentativas em caso de falha (default: 0)
- `output: telegram`: marcar NO ULTIMO step que produz o output final

**Regras de modelo por tipo de step:**
- Coleta de dados → `haiku` (rapido, barato, bom para APIs e scraping)
- Analise / escrita criativa → `opus` (melhor raciocinio, mais caro)
- Revisao / validacao → `sonnet` ou `opus` (depende da complexidade)
- Publicacao / API calls → `sonnet` ou `haiku` (tarefas mecanicas)

#### 3. Aplicar regras de paralelismo (CRITICO)

Analisar os steps propostos e aplicar estas regras proativamente:

**Regra 1 — Coletor atômico: nunca criar um collector monolítico.**
Se um step precisa buscar dados de 3+ fontes independentes (APIs, sites, bancos de dados), quebre em sub-steps paralelos — um por fonte ou grupo de fontes relacionadas.

Exemplo RUIM:
```
[collector: busca Binance + CoinGecko + Yahoo + GitHub] → [analyst]
```
Tempo: soma de todas as buscas (sequencial).

Exemplo BOM:
```
[collect-binance] ──┐
[collect-coingecko]─┤
[collect-yahoo] ────┼→ [analyst]
[collect-github] ───┘
```
Tempo: max de uma busca (paralelo). Ate 4x mais rapido.

**Regra 2 — Assets paralelos com analise.**
Se a pipeline gera assets (capa, graficos, imagens) que nao dependem da analise completa, rodar em paralelo com a analise — nao depois.

Exemplo RUIM:
```
[collect] → [analyst] → [cover] → [writer]
```

Exemplo BOM:
```
[collect] → [analyst] → [writer]
[collect] → [cover] ─────────────→ [publisher]
```
Cover e analyst rodam em paralelo porque ambos dependem apenas do collect.

**Regra 3 — Dependencia minima.**
Cada step deve depender apenas dos steps cujo output ele realmente precisa ler. Nunca depender de um step "por seguranca" se nao vai usar seu output.

**Regra 4 — Retry em collectors.**
Steps que fazem chamadas externas (APIs, scraping, webhooks) devem ter `retry: 1` no minimo. Falhas transitorias sao comuns e nao devem matar o pipeline inteiro.

**Regra 5 — Timeouts proporcionais.**
- Collectors (curl/API): 120-300s timeout, 120s inactivity
- Analise (opus pensando): 600-900s timeout, 300s inactivity
- Escrita (opus gerando texto longo): 600-900s timeout, 300s inactivity
- Revisao: 300-600s timeout, 180s inactivity
- Publicacao (API calls): 120-180s timeout, 60s inactivity

#### 4. Apresentar DAG visual ao usuario

Antes de criar os arquivos, mostrar a DAG proposta em formato visual:

```
Wave 1 (paralelo):
  collect-fonte-a  ──┐  haiku, ~30s
  collect-fonte-b  ──┤  haiku, ~30s
  collect-fonte-c  ──┘  haiku, ~30s

Wave 2 (paralelo):
  analyst  ←── todos os collectors    opus, ~3min
  cover    ←── collect-fonte-a        sonnet, ~1min

Wave 3:  writer    ←── analyst           opus, ~5min
Wave 4:  reviewer  ←── writer            opus, ~3min
Wave 5:  publisher ←── reviewer + cover  sonnet, ~1min

Tempo total estimado: ~13min (vs ~25min sequencial)
```

Perguntar se o usuario aprova ou quer ajustar.

#### 5. Perguntar schedule

Mesmas opcoes de rotina: horarios (HH:MM), dias, data limite.

#### 6. Gerar nome

Converter o objetivo em kebab-case.

#### 7. Criar o arquivo principal

`vault/Routines/{nome}.md`:

```yaml
---
title: "{titulo descritivo}"
description: "{frase curta sobre o pipeline}"
type: pipeline
created: {YYYY-MM-DD}
updated: {YYYY-MM-DD}
tags: [pipeline, {categorias}]
schedule:
  times: ["{HH:MM}"]
  days: [{dias}]
model: {modelo default}
enabled: true
agent: {agente se aplicavel}
notify: final
---

[[Routines]]

```pipeline
steps:
  - id: {step-1-id}
    name: "{Step 1 Name}"
    model: {modelo}
    prompt_file: steps/{step-1-id}.md
    timeout: {timeout}
    inactivity_timeout: {inactivity}
    retry: {retry}

  - id: {step-2-id}
    name: "{Step 2 Name}"
    model: {modelo}
    depends_on: [{step-1-id}]
    prompt_file: steps/{step-2-id}.md

  - id: {step-final-id}
    name: "{Step Final Name}"
    model: {modelo}
    depends_on: [{step-anterior-id}]
    prompt_file: steps/{step-final-id}.md
    output: telegram
```
```

**Campos opcionais adicionais no frontmatter:**

- `context: minimal` — pula o system prompt do vault (Tooling, Journal, etc.). Util quando os steps da pipeline nao precisam de conhecimento do vault e voce quer economizar tokens e ganhar velocidade. Ideal para pipelines puramente tecnicas (coleta de dados, transformacao, envio).
- `voice: true` — alem de enviar o output final como texto no Telegram, tambem envia como audio (TTS). Util para newsletters, briefings matinais, ou qualquer output que o usuario queira ouvir em vez de ler.

#### 8. Criar pasta de steps

`vault/Routines/{nome}/steps/`

#### 9. Criar arquivo de prompt para cada step

`vault/Routines/{nome}/steps/{step-id}.md`

IMPORTANTE sobre prompts dos steps:
- NAO mencionar compartilhamento de arquivos — o orquestrador ja injeta instrucoes sobre o workspace automaticamente
- NAO instruir o step a ler ou escrever em `data/` — isso e automatico
- Focar apenas na TAREFA do step: "Analise os dados coletados e produza uma analise tecnica"
- O step recebe automaticamente: lista de arquivos disponiveis, instrucao de onde escrever output
- Escrever prompts curtos e diretos — o contexto do pipeline ja e injetado pelo orquestrador

#### 10. Atualizar o index

Editar `vault/Routines/Routines.md` e adicionar: `- [[{nome}]] — descricao`

#### 11. Registrar no Journal

Appendar no journal do dia com detalhes da pipeline criada.

#### 12. Confirmar

Informar ao usuario a pipeline criada, quantos steps, quais rodam em paralelo, e quando sera a proxima execucao.

---

## Exemplo completo: Newsletter Semanal

Objetivo: pipeline que toda segunda-feira pesquisa 3 fontes (blog, Reddit, Hacker News), escreve uma newsletter, revisa e envia por email.

### Arquivo principal: `vault/Routines/newsletter-semanal.md`

```yaml
---
title: "Newsletter Semanal de Tech"
description: "Pipeline semanal que pesquisa 3 fontes, redige newsletter e envia por email"
type: pipeline
created: 2026-04-09
updated: 2026-04-09
tags: [pipeline, newsletter, tech]
schedule:
  times: ["08:00"]
  days: [mon]
model: sonnet
enabled: true
notify: final
---

[[Routines]]

```pipeline
steps:
  - id: collect-blogs
    name: "Coletar posts de blogs"
    model: haiku
    prompt_file: steps/collect-blogs.md
    timeout: 180
    inactivity_timeout: 120
    retry: 1

  - id: collect-reddit
    name: "Coletar posts do Reddit"
    model: haiku
    prompt_file: steps/collect-reddit.md
    timeout: 180
    inactivity_timeout: 120
    retry: 1

  - id: collect-hn
    name: "Coletar posts do Hacker News"
    model: haiku
    prompt_file: steps/collect-hn.md
    timeout: 180
    inactivity_timeout: 120
    retry: 1

  - id: write-newsletter
    name: "Redigir newsletter"
    model: opus
    depends_on: [collect-blogs, collect-reddit, collect-hn]
    prompt_file: steps/write-newsletter.md
    timeout: 600
    inactivity_timeout: 300

  - id: review
    name: "Revisar newsletter"
    model: opus
    depends_on: [write-newsletter]
    prompt_file: steps/review.md
    timeout: 300
    inactivity_timeout: 180

  - id: send-email
    name: "Enviar por email"
    model: haiku
    depends_on: [review]
    prompt_file: steps/send-email.md
    timeout: 120
    inactivity_timeout: 60
    output: telegram
```
```

### DAG visual

```
Wave 1 (paralelo):
  collect-blogs  ──┐  haiku, ~30s
  collect-reddit ──┤  haiku, ~30s
  collect-hn     ──┘  haiku, ~30s

Wave 2:  write-newsletter ←── todos os collectors   opus, ~5min
Wave 3:  review           ←── write-newsletter       opus, ~2min
Wave 4:  send-email       ←── review                 haiku, ~30s

Tempo total estimado: ~8min (vs ~15min sequencial)
```

### Exemplo de prompt de step: `steps/write-newsletter.md`

```markdown
Voce eh um redator de newsletters de tecnologia.

Leia os dados coletados das 3 fontes e escreva uma newsletter concisa com:
- 5-7 destaques da semana, priorizando por relevancia e novidade
- Para cada destaque: titulo, resumo de 2-3 frases, e link original
- Tom: informativo mas acessivel, sem jargao desnecessario
- Formato: Markdown com headers e bullet points

Salve o resultado como newsletter.md
```

Note que o prompt NAO menciona `data/`, caminhos de arquivos de input, nem instrui sobre workspace — tudo isso eh injetado automaticamente pelo orquestrador.

---

## Modo Revisao

Acionado quando o usuario pede para revisar, melhorar ou otimizar pipelines existentes.

### Passo 1 — Identificar escopo

- Se o usuario mencionou uma pipeline especifica → revisar apenas essa
- Se pediu revisao geral → listar todas em `vault/Routines/` com `type: pipeline`

### Passo 2 — Analisar cada pipeline

Para cada pipeline, ler o arquivo principal e todos os step prompts. Avaliar com o checklist abaixo.

**Checklist de revisao:**

#### A. Paralelismo

- [ ] **Collector monolitico?** — Um step coleta dados de 3+ fontes? Sugerir split em sub-collectors paralelos.
- [ ] **Cadeia 100% sequencial?** — Todos os steps dependem do anterior? Verificar se algum poderia rodar em paralelo (ex: cover em paralelo com analise).
- [ ] **Dependencias excessivas?** — Algum step depende de outro sem usar seu output? Remover dependencia.
- [ ] **Assets em serie?** — Geracao de imagem/capa/grafico espera analise terminar? Se nao precisa do output da analise, paralelizar.

#### B. Modelos

- [ ] **Haiku para coleta?** — Steps que apenas fazem curl/API calls devem usar `haiku`, nunca `opus`.
- [ ] **Opus para analise/escrita?** — Steps que requerem raciocinio profundo ou criatividade devem usar `opus`.
- [ ] **Modelo caro em tarefa simples?** — Steps mecanicos (publicar, enviar, formatar) nao precisam de `opus`.

#### C. Resiliencia

- [ ] **Retry em collectors?** — Steps com chamadas externas devem ter `retry: 1` no minimo.
- [ ] **Timeout adequado?** — Collectors com >300s e excessivo? Steps opus com <300s e insuficiente?
- [ ] **Inactivity timeout?** — Steps sem `inactivity_timeout` explicito usam default (300s). Collectors devem ter 120s. Publicacao 60s.

#### D. Prompts

- [ ] **Prompt do step menciona `data/`?** — Remover. O orquestrador injeta isso automaticamente.
- [ ] **Prompt generico demais?** — Instrucoes vagas como "analise os dados" sem especificar O QUE analisar.
- [ ] **Prompt muito longo?** — Se >500 palavras, considerar se tudo e necessario.

#### E. Historico de execucao

- Ler `~/.claude-bot/routines-state/YYYY-MM-DD.json` (ultimos 2-3 dias)
- Verificar se ha falhas recorrentes, quais steps falham, com que erro
- Timeouts reais vs configurados — se o step esta sendo morto pelo timeout, ajustar
- Se o collector demora muito, e candidato a split paralelo

### Passo 3 — Apresentar recomendacoes

Para cada pipeline analisada, apresentar:

```
### {nome-da-pipeline}

**Estrutura atual:**
[step1] → [step2] → [step3] → [step4]
Tempo estimado: ~Xmin (sequencial)

**Melhorias sugeridas:**

1. ⚡ **Paralelizar coleta** — split [step1] em 3 sub-collectors paralelos
   Ganho: coleta de ~5min para ~1min

2. 🔄 **Adicionar retry** — [step1] e [step3] fazem chamadas externas sem retry
   Ganho: resiliencia a falhas transitorias

3. 🧠 **Ajustar modelo** — [step3] usa opus mas so formata texto (sonnet basta)
   Ganho: ~40% mais rapido e mais barato

**Estrutura proposta:**
[sub-collect-a] ──┐
[sub-collect-b] ──┼→ [analyst] → [writer] → [publisher]
[sub-collect-c] ──┘
Tempo estimado: ~Ymin (Zx mais rapido)
```

### Passo 4 — Executar melhorias aprovadas

Perguntar quais melhorias o usuario quer aplicar. Para cada aprovada:

- **Split de collector** → criar novos step files, atualizar pipeline definition, remover step antigo
- **Mudanca de modelo/timeout/retry** → editar o pipeline definition
- **Rewrite de prompt** → editar o step file, mostrar diff ao usuario
- **Reorganizacao de DAG** → atualizar `depends_on` nos steps afetados

Ao modificar uma pipeline:
1. Atualizar campo `updated` no frontmatter
2. Manter step files antigos ate confirmar que os novos funcionam (ou deletar se usuario aprovar)
3. Registrar mudancas no Journal

### Passo 5 — Registrar no Journal

Appendar no journal do dia com as mudancas aplicadas.

---

## Anti-patterns (referencia rapida)

| Anti-pattern | Problema | Solucao |
|-------------|----------|---------|
| Collector monolitico | Um step busca 10 APIs sequencialmente | Split em N sub-collectors paralelos |
| Cadeia totalmente linear | A → B → C → D → E sem nenhum paralelismo | Identificar steps independentes e paralelisar |
| Opus para curl | Modelo caro fazendo chamadas HTTP triviais | Usar haiku para coleta |
| Sem retry em API calls | Falha transitorias matam o pipeline | retry: 1 em steps com chamadas externas |
| Timeout uniforme | Todos os steps com 1200s | Ajustar por tipo: collectors curtos, analise longos |
| Cover sequencial | Geracao de capa espera analise inteira | Paralelizar se cover depende apenas dos dados brutos |
| Prompt com `data/` | Step menciona workspace | Remover — orquestrador injeta automaticamente |

---

## Notas

- O scheduler detecta `type: pipeline` automaticamente e usa o PipelineExecutor
- Pipelines usam workspace compartilhado em /tmp/claude-pipeline-{nome}-{timestamp}/data/
- Cada step e um subprocess Claude CLI independente (nao compartilham sessao)
- Se um step falha e tem `retry > 0`, ele e re-executado
- Se um step falha sem retry, todos os steps dependentes sao marcados como SKIPPED
- Timeouts: `inactivity_timeout` mata steps inativos (sem output), `timeout` e o limite hard total
- O campo `notify` controla notificacoes Telegram: `final` (so output), `all` (cada step), `summary`, `none`
- Falhas SEMPRE notificam no Telegram independente do modo
