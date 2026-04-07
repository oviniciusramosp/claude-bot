---
title: Criar Novo Agente
description: Skill interativa para criar agentes especializados. Guia o usuario com perguntas sobre nome, personalidade, modelo e especializacoes, e gera os arquivos em vault/Agents/.
type: skill
created: 2026-04-07
updated: 2026-04-07
trigger: "quando o usuario quiser criar um novo agente, ou usar /agent new"
tags: [skill, agent, automation]
---

# Criar Novo Agente

## Objetivo

Ajudar o usuario a criar um agente especializado que vive dentro do vault e pode ser ativado via `/agent <nome>`.

[[Skills]]

## Dependencias

- [[Agents]] — destino dos agentes gerados por esta skill

## Passos

1. **Perguntar o nome** — Nome legivel do agente (ex: "Jarvis", "CryptoAnalyst", "Palmeiras Scout")

2. **Perguntar a personalidade** — Como o agente deve se comportar. Tom de voz, estilo de comunicacao. Ex: "Direto e tecnico, sem rodeios" ou "Amigavel e didatico"

3. **Perguntar a descricao** — Uma frase curta que explique o que o agente faz (vai no frontmatter `description`)

4. **Perguntar especializacoes** — Areas de foco do agente. Lista de topicos em que ele eh especialista.

5. **Perguntar o modelo padrao** — Qual modelo usar por padrao? Opcoes: sonnet (rapido), opus (profundo), haiku (leve). Default: sonnet.

6. **Perguntar o icone** — Um emoji que representa o agente. Ex: 🤖, 📊, ⚽, 🔬

7. **Perguntar se eh o agente padrao** — Deve ser ativado automaticamente? (`default: true` no frontmatter)

8. **Gerar ID** — Converter o nome em kebab-case para o ID do diretorio. Ex: "CryptoAnalyst" -> `crypto-analyst`

9. **Criar a estrutura** — Gerar em `vault/Agents/{id}/`:

```
vault/Agents/{id}/
  agent.md       # Arquivo central do agente
  Journal/       # Diretorio para journal proprio
```

O `agent.md` deve seguir este formato:

```yaml
---
title: {nome}
description: {descricao curta}
type: agent
created: {YYYY-MM-DD}
updated: {YYYY-MM-DD}
tags: [agent, {especializacoes como tags}]
name: {nome}
personality: {personalidade em uma frase}
model: {modelo}
icon: "{emoji}"
default: false
---

[[Agents]]

## Personalidade
{descricao detalhada da personalidade}

## Instrucoes
- Registrar no Journal proprio (vault/Agents/{id}/Journal/)
- {instrucoes especificas do agente}

## Especializacoes
- {lista de especializacoes}
```

A primeira linha do body DEVE ser `[[Agents]]` (link para o index pai). Manter o body enxuto — nao adicionar links decorativos.

10. **Atualizar o index** — Editar `vault/Agents/Agents.md` e adicionar o novo agente na lista: `- [[{id}]] — {descricao curta}`

11. **Registrar no Journal global** — Appendar no journal do dia:
```
## HH:MM — Novo agente criado

- Criado agente [[{nome}]] ([[vault/Agents/{id}/agent.md|{nome}]])
- Especializacoes: {lista}
- Modelo: {modelo}

---
```

12. **Confirmar** — Informar ao usuario que o agente foi criado e como ativa-lo (`/agent {nome}`)

## Notas

- O agente vive dentro do vault e aparece no graph view do Obsidian como um no central
- O journal do agente eh separado do global — cada agente tem seu proprio historico
- Rotinas podem ser direcionadas a agentes com o campo `agent: {id}` no frontmatter
- O campo `default: true` faz o agente ser ativado automaticamente em novas sessoes
- Agentes podem referenciar skills, notas, e outras entidades do vault via wikilinks
