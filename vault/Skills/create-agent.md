---
title: Criar Novo Agente
description: Skill interativa para criar agentes especializados. Gera os 3 arquivos (agent.md, CLAUDE.md, {id}.md) + Journal.
type: skill
created: 2026-04-07
updated: 2026-04-07
trigger: "quando o usuario quiser criar um novo agente, ou usar /agent new"
tags: [skill, agent, automation]
---

[[Skills]]

## Passos

1. **Perguntar o nome** — Nome legivel do agente

2. **Perguntar a personalidade** — Tom de voz, estilo de comunicacao

3. **Perguntar a descricao** — Frase curta (vai no frontmatter `description`)

4. **Perguntar especializacoes** — Areas de foco

5. **Perguntar o modelo** — sonnet/opus/haiku. Default: sonnet.

6. **Perguntar o icone** — Emoji que representa o agente

7. **Gerar ID** — kebab-case do nome. Ex: "CryptoAnalyst" -> `crypto-analyst`

8. **Criar 4 itens** em `vault/Agents/{id}/`:

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

9. **Atualizar Agents.md** — adicionar `- [[{id}]] — {descricao}`

10. **Registrar no Journal global** — mencionar em texto plano (sem wikilink para o agente)

11. **Confirmar** — informar como ativar: `/agent {nome}`
