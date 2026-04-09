---
title: Criar ou Revisar Agente
description: Skill consultiva para criar agentes especializados ou revisar agentes existentes. Ajuda a decidir se o caso requer um agente dedicado ou se o Main Agent eh suficiente. Gera os 3 arquivos (agent.md, CLAUDE.md, {id}.md) + Journal.
type: skill
created: 2026-04-07
updated: 2026-04-09
trigger: "quando o usuario quiser criar, revisar, melhorar um agente, quiser um assistente especializado, precisar de um bot para algo, ou usar /agent new"
tags: [skill, agent, automation, review]
---

# Criar ou Revisar Agente

## Modos de operacao

Esta skill opera em dois modos:

1. **Criacao** — quando o usuario quer criar um novo agente
2. **Revisao** — quando o usuario quer revisar, melhorar ou avaliar agentes existentes

Detectar o modo pelo contexto da conversa. Se ambiguo, perguntar.

---

## Modo Criacao

### Passo 0 — Triagem: agente dedicado ou Main Agent?

ANTES de criar qualquer coisa, analisar se o usuario realmente precisa de um agente dedicado ou se o Main Agent com o prompt certo resolve.

**Sinais de que um agente dedicado FAZ sentido:**

- O caso requer uma **personalidade distinta** (tom, estilo, linguagem propria)
- O agente tera um **workspace isolado** com arquivos especificos
- O uso sera **recorrente** (nao eh uma tarefa pontual)
- Precisa de **Journal proprio** para manter historico separado do Main
- Ha **rotinas agendadas** que devem rodar com essa persona
- O dominio eh **especializado** (cripto, fitness, escrita criativa) e se beneficia de instrucoes permanentes

**Sinais de que o Main Agent eh suficiente:**

- Tarefa pontual ou de curta duracao
- Nao precisa de personalidade ou tom especial
- Nao precisa de workspace separado
- As instrucoes cabem em um prompt de sessao normal
- O usuario so quer um output, nao uma "entidade" recorrente

**Se detectar que Main basta:**

Sugerir proativamente ao usuario:

> "Pelo que voce descreveu, isso nao precisa de um agente dedicado. O Main Agent pode fazer isso com um prompt direto. Agentes dedicados sao melhores quando voce quer uma personalidade especifica, workspace isolado, e uso recorrente.
>
> Posso ajudar a formular o prompt certo para o Main. Ou se prefere criar o agente mesmo assim, sigo em frente."

Se o usuario aceitar → formular o prompt e encerrar.
Se preferir criar o agente → continuar com os passos abaixo.

**Exemplos de triagem:**

| Objetivo do usuario | Recomendacao | Motivo |
|---------------------|--------------|--------|
| "Quero um assistente de cripto que acompanhe meu portfolio todo dia" | Agente dedicado | Recorrente, dominio especifico, precisa de Journal proprio |
| "Me ajuda a escrever um email formal" | Main Agent | Tarefa pontual, sem necessidade de persona |
| "Quero um bot com personalidade de coach que me cobre habitos" | Agente dedicado | Personalidade distinta, uso recorrente, precisa manter historico |
| "Analisa esse CSV e me da insights" | Main Agent | Tarefa unica, sem personalidade especial |
| "Preciso de um revisor de texto tecnico que siga meu style guide" | Agente dedicado | Instrucoes permanentes, personalidade definida, uso recorrente |
| "Resume esse artigo pra mim" | Main Agent | Tarefa pontual, qualquer modelo resolve |

### Passo 1 — Perguntar o nome

Nome legivel do agente. Ex: "CryptoAnalyst", "FitnessCoach", "TechWriter".

### Passo 2 — Definir a personalidade

Tom de voz, estilo de comunicacao, tracos de carater.

#### Heuristicas de personalidade

Ajudar o usuario a definir uma personalidade que realmente diferencie o agente. Se a personalidade fornecida for generica, sugerir melhorias antes de prosseguir.

**Boas personalidades:**

| Exemplo | Por que funciona |
|---------|-----------------|
| "Analista tecnico direto e quantitativo, prefere dados a opiniao. Usa bullet points, evita jargao vago." | Tom claro, estilo de output definido, preferencias explicitas |
| "Coach motivacional firme mas empatico. Faz perguntas antes de dar conselhos. Celebra progresso, confronta desculpas." | Personalidade com nuance, comportamento condicional |
| "Redator criativo com humor sutil. Escreve em paragrafos curtos, usa analogias inesperadas, evita cliches corporativos." | Estilo literario definido, anti-patterns explicitos |

**Personalidades problematicas (e como melhorar):**

| Personalidade ruim | Problema | Versao melhorada |
|-------------------|----------|-----------------|
| "Seja util e informativo" | Generico — todo modelo ja faz isso | "Especialista em X que prioriza clareza sobre completude. Responde com exemplos concretos antes de teoria." |
| "Seja amigavel" | Vago, nao diferencia de nada | "Tom casual e bem-humorado, usa analogias do dia-a-dia. Trata o usuario como colega, nao como cliente." |
| "Responda bem" | Nao eh personalidade | "Formalista tecnico. Estrutura respostas com headers. Sempre cita fonte ou motivo de cada afirmacao." |

**Checklist de uma boa personalidade:**
- [ ] Tom de voz definido (formal, casual, tecnico, humorado?)
- [ ] Estilo de output claro (bullets, paragrafos, tabelas, conversacional?)
- [ ] Pelo menos um anti-pattern (o que o agente NAO faz)
- [ ] Comportamento que o Main Agent nao teria naturalmente

### Passo 3 — Perguntar a descricao

Frase curta que vai no frontmatter `description`. Deve explicar o que o agente faz em uma linha.

### Passo 4 — Perguntar especializacoes

Areas de foco do agente. Virao como lista em `## Especializacoes` no CLAUDE.md e como tags no frontmatter.

### Passo 5 — Escolher o modelo

#### Orientacao de modelo por tipo de agente

Nao apenas perguntar — recomendar baseado no uso previsto:

| Tipo de agente | Modelo recomendado | Motivo |
|---------------|-------------------|--------|
| Coleta de dados, monitoramento, alertas simples | `haiku` | Rapido e barato, ideal para tarefas mecanicas |
| Maioria dos agentes (analise, escrita, assistencia geral) | `sonnet` | Equilibrio entre qualidade e velocidade |
| Analise profunda, escrita criativa, raciocinio complexo | `opus` | Melhor raciocinio, mais caro e mais lento |
| Agente com rotinas frequentes (varias vezes ao dia) | `haiku` ou `sonnet` | Custo acumula rapido com opus |
| Agente para decisoes criticas (financeiro, estrategia) | `opus` | Vale o custo extra pela qualidade |

Default: `sonnet`. Sugerir mudanca se o caso pedir.

### Passo 6 — Perguntar o icone

Emoji que representa o agente. Sugerir opcoes se o usuario nao tiver preferencia.

### Passo 7 — Gerar ID

kebab-case do nome. Ex: "CryptoAnalyst" -> `crypto-analyst`

### Passo 8 — Criar 4 itens em `vault/Agents/{id}/`

**agent.md** — metadados para o bot (body vazio):
```yaml
---
title: {nome}
description: {descricao curta}
type: agent
created: {YYYY-MM-DD}
updated: {YYYY-MM-DD}
tags: [agent, {especializacoes}]
name: {nome}
personality: {personalidade em uma frase}
model: {modelo}
icon: "{emoji}"
default: false
---
```

**CLAUDE.md** — instrucoes para Claude Code (SEM frontmatter):
```markdown
# {nome} {emoji}

## Personalidade
{descricao detalhada do tom e estilo}

## Instrucoes
- Registrar conversas no Journal proprio: `Journal/YYYY-MM-DD.md`
- IMPORTANTE: registrar no Journal DURANTE a conversa, nao apenas no final. Registre sempre que: uma decisao for tomada, uma tarefa for concluida, informacao nova for descoberta, ou o usuario pedir para lembrar algo.
- {instrucoes especificas}

## Especializacoes
- {lista}
```

**{id}.md** — hub de links no grafo Obsidian:
```markdown
---
title: {nome}
description: Hub do agente {nome} no grafo.
type: agent
created: {YYYY-MM-DD}
updated: {YYYY-MM-DD}
tags: [agent]
---

[[{id}/Journal|Journal]]
[[agent]]
[[CLAUDE]]
```

**Journal/** — criar o diretorio vazio

### Passo 9 — Atualizar Agents.md

Adicionar `- [[{id}]] — {descricao}` no index.

### Passo 10 — Registrar no Journal global

Appendar no journal do dia — mencionar em texto plano (sem wikilink para o agente).

### Passo 11 — Confirmar

Informar como ativar: `/agent {nome}`

### Passo 12 — Sugerir proximos passos

Apos criar o agente, sugerir proativamente:

> "Agente criado! Proximo passo: quer criar uma **rotina agendada** para este agente? Rotinas com `agent: {id}` rodam automaticamente no workspace dele.
> Exemplos: relatorio diario, monitoramento, resumo matinal."

Se o usuario aceitar → redirecionar para a skill `Skills/create-routine.md` com o campo `agent` pre-preenchido.

---

## Exemplo completo: Agente CryptoBro

Objetivo: agente especializado em mercado cripto, com personalidade de analista tecnico.

**Triagem:** agente dedicado — dominio especializado, uso recorrente, personalidade distinta, tera rotinas proprias.

**Dados coletados:**
- Nome: CryptoBro
- Personalidade: "Analista tecnico direto e quantitativo. Prefere dados a opiniao. Usa bullet points, tabelas e numeros concretos. Nunca diz 'pode ser que' — sempre da um veredito com nivel de confianca."
- Descricao: "Analista de mercado cripto focado em BTC e altcoins"
- Especializacoes: analise tecnica, on-chain, macro, derivativos
- Modelo: opus (analise complexa)
- Icone: 📊

**Resultado — agent.md:**
```yaml
---
title: CryptoBro
description: Analista de mercado cripto focado em BTC e altcoins
type: agent
created: 2026-04-09
updated: 2026-04-09
tags: [agent, crypto, bitcoin, analise-tecnica]
name: CryptoBro
personality: "Analista tecnico direto e quantitativo. Prefere dados a opiniao."
model: opus
icon: "📊"
default: false
---
```

**Resultado — CLAUDE.md:**
```markdown
# CryptoBro 📊

## Personalidade
Analista tecnico direto e quantitativo. Prefere dados a opiniao.
Usa bullet points, tabelas e numeros concretos. Nunca diz "pode ser que"
— sempre da um veredito com nivel de confianca.

## Instrucoes
- Registrar conversas no Journal proprio: `Journal/YYYY-MM-DD.md`
- Registrar DURANTE a conversa, nao apenas no final
- Sempre incluir precos exatos, percentuais e timeframes
- Citar fontes de dados usadas em cada analise

## Especializacoes
- Analise tecnica (EMAs, RSI, suportes/resistencias)
- Metricas on-chain (funding, OI, long/short)
- Correlacao macro (DXY, S&P500, GOLD)
- Derivativos e sentimento (Fear & Greed)
```

**Proximo passo sugerido:** "Quer criar uma rotina diaria para o CryptoBro? Ex: analise tecnica as 21:30 com coleta de dados e publicacao no Notion."

---

## Modo Revisao

Acionado quando o usuario pede para revisar, melhorar ou avaliar agentes existentes.

### Passo 1 — Identificar escopo

- Se o usuario mencionou um agente especifico → revisar apenas esse
- Se pediu revisao geral → listar todos os agentes em `vault/Agents/` e analisar cada um (incluindo o Main Agent)

### Passo 2 — Analisar cada agente

Para cada agente, ler `agent.md` e `CLAUDE.md` completos. Avaliar com o checklist abaixo.

**Checklist de revisao:**

#### A. CLAUDE.md atualizado?

- [ ] As instrucoes refletem o uso real do agente? (comparar com Journal recente)
- [ ] Ha instrucoes obsoletas ou que nunca sao usadas?
- [ ] Faltam instrucoes para tarefas que o agente faz frequentemente?

#### B. Modelo adequado?

- [ ] O agente faz tarefas simples com `opus`? → sugerir `sonnet` ou `haiku`
- [ ] O agente faz analise complexa com `haiku`? → sugerir `sonnet` ou `opus`
- [ ] O agente tem rotinas frequentes com modelo caro? → avaliar custo-beneficio

#### C. Agente em uso?

- [ ] O Journal tem entradas recentes (ultimas 2 semanas)?
- [ ] Se nao tem — o agente ainda eh relevante? Sugerir desativar ou remover.
- [ ] Se tem poucas entradas — o uso justifica um agente dedicado ou o Main bastaria?

#### D. Personalidade distintiva?

- [ ] A personalidade no `agent.md` eh especifica o suficiente?
- [ ] O tom do CLAUDE.md corresponde ao campo `personality`?
- [ ] O agente se diferencia do Main de forma clara?
- [ ] Se a personalidade for generica ("seja util") → sugerir refinamento

#### E. Oportunidade de merge?

- [ ] Dois agentes tem especializacoes sobrepostas?
- [ ] Um agente faz tao pouco que poderia ser absorvido por outro?
- [ ] Se merge fizer sentido → propor qual sobrevive e o que absorve

### Passo 3 — Apresentar recomendacoes

Para cada agente analisado, apresentar:

```
### {nome-do-agente}
Status: OK / Melhorias sugeridas

- [melhoria 1]: motivo e beneficio
- [melhoria 2]: motivo e beneficio
```

Se a revisao for geral, incluir visao consolidada:
```
### Visao geral

- Total de agentes: X (+ Main)
- Em uso ativo: Y
- Sem uso recente: Z
- Candidatos a merge: [lista]
- Candidatos a remocao: [lista]
```

### Passo 4 — Executar melhorias aprovadas

Perguntar quais melhorias o usuario quer aplicar. Para cada aprovada:

- **Mudanca de modelo** → editar `agent.md` (campo `model`)
- **Refinamento de personalidade** → editar `agent.md` (campo `personality`) e `CLAUDE.md` (secao Personalidade)
- **Atualizacao de instrucoes** → editar `CLAUDE.md`, mostrar diff ao usuario
- **Merge de agentes** → migrar instrucoes relevantes para o agente que sobrevive, mover Journal entries se necessario
- **Remocao** → confirmar com o usuario antes de deletar (via Lixeira do macOS se disponivel)

Ao modificar um agente:
1. Atualizar campo `updated` no frontmatter do `agent.md`
2. Registrar mudancas no Journal

### Passo 5 — Registrar no Journal

Appendar no journal do dia com as mudancas aplicadas.

---

## Notas

- O Main Agent eh o agente padrao do bot — nao tem workspace proprio nem CLAUDE.md especifico
- Agentes mudam o `cwd` para `vault/Agents/{id}/` quando ativos
- O Claude CLI carrega CLAUDE.md walking up da hierarquia: `Agents/{id}/CLAUDE.md` + `vault/CLAUDE.md` + raiz
- Rotinas podem ser direcionadas a agentes com `agent: {id}` no frontmatter
- O app macOS (ClaudeBotManager) permite criar e gerenciar agentes via UI
- Agentes podem ser importados de templates com `/agent import`
