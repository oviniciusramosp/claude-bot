---
title: Claude Bot Vault
description: Indice central do vault. Hub raiz do grafo que conecta todas as areas.
type: index
created: 2026-04-07
updated: 2026-04-07
tags: [index, vault]
---

# Claude Bot Vault

Grafo de conhecimento persistente. Alimentado pelo Claude Code, navegavel no Obsidian.

## Areas

- [[Journal]] — Registro diario de conversas, decisoes e acoes
- [[Notes]] — Conhecimento duravel e incremental
- [[Skills]] — Tarefas recorrentes e estruturadas
- [[Routines]] — Rotinas agendadas com execucao automatica
- [[Agents]] — Agentes especializados com personalidade e journal proprio
- [[Tooling]] — Preferencias de ferramentas por tipo de tarefa

## Credenciais

- `.env` — API keys e tokens (gitignored)

## Regras

1. **Frontmatter obrigatorio** — Todo `.md` tem `title`, `description`, `type`, `created`, `updated`, `tags`
2. **Grafo em arvore** — README → Indexes → Folhas. Sem atalhos, sem links decorativos
3. **README linka APENAS indexes + Tooling** — Nunca linka diretamente para folhas
4. **Indexes listam APENAS seus filhos** — Sem secao "Relacionados" entre indexes
5. **Folhas linkam seu index pai** — Primeira linha do body = `[[IndexPai]]`
6. **Cross-links somente reais** — Somente quando um arquivo depende/cria/modifica outro
7. **Append-only** — Journal nunca eh sobrescrito. Notes crescem, nunca encolhem
8. **Atomicidade** — Uma nota por conceito
9. **Nomes estaveis** — Nomes de arquivo sao permalinks
