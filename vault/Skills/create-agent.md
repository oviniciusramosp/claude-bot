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

[[Skills]]

## Dependencias

- [[Agents]] — destino dos agentes gerados por esta skill

## Passos

1. **Perguntar o nome** — Nome legivel do agente (ex: "Jarvis", "CryptoAnalyst", "Palmeiras Scout")

2. **Perguntar a personalidade** — Como o agente deve se comportar. Tom de voz, estilo de comunicacao.

3. **Perguntar a descricao** — Uma frase curta que explique o que o agente faz

4. **Perguntar especializacoes** — Areas de foco do agente.

5. **Perguntar o modelo padrao** — sonnet (rapido), opus (profundo), haiku (leve). Default: sonnet.

6. **Perguntar o icone** — Um emoji que representa o agente.

7. **Gerar ID** — Converter o nome em kebab-case. Ex: "CryptoAnalyst" -> `crypto-analyst`

8. **Criar a estrutura** — Gerar em `vault/Agents/{id}/`:

```
vault/Agents/{id}/
  agent.md       # Metadados (frontmatter parseado pelo bot)
  CLAUDE.md      # Instrucoes para o Claude Code (lido automaticamente como workspace)
  Journal/       # Diretorio para journal proprio
```

O `agent.md` contem metadados para o bot:

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
```

O `CLAUDE.md` contem instrucoes para o Claude Code (lido automaticamente quando o agente esta ativo):

```markdown
# {nome}

## Personalidade
{descricao detalhada da personalidade e tom de voz}

## Instrucoes
- Registrar conversas no Journal proprio: Journal/YYYY-MM-DD.md
- {instrucoes especificas do agente}

## Especializacoes
- {lista de especializacoes}
```

O CLAUDE.md do agente NAO precisa repetir regras do vault (frontmatter, wikilinks, etc.) — essas regras vem do CLAUDE.md pai em ~/claude-bot/ que eh carregado automaticamente pela hierarquia do Claude Code.

9. **Atualizar o index** — Editar `vault/Agents/Agents.md` e adicionar: `- [[{id}]] — {descricao curta}`

10. **Registrar no Journal global** — Appendar no journal do dia com [[link]] para o novo agente.

11. **Confirmar** — Informar ao usuario que o agente foi criado e como ativa-lo (`/agent {nome}`)

## Notas

- Cada agente tem seu proprio workspace: `vault/Agents/{id}/`
- O Claude Code le o CLAUDE.md do agente + o CLAUDE.md do projeto (hierarquia automatica)
- O journal do agente eh separado do global
- Rotinas podem ser direcionadas a agentes com o campo `agent: {id}` no frontmatter
