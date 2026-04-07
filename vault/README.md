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

1. **Frontmatter obrigatorio** — Todo `.md` tem `title`, `description`, `type`, `created`, `tags`
2. **Zero orfaos** — Todo arquivo deve ter outlinks E ser linkado por ao menos 1 outro arquivo
3. **Index files** — Cada pasta tem um arquivo index (MOC) que conecta seus filhos ao grafo
4. **Description como indice** — Claude le descriptions antes de abrir arquivos
5. **Append-only** — Journal nunca eh sobrescrito. Notes crescem, nunca encolhem
6. **Wikilinks** — Conectar notas entre si com wikilinks
7. **Atomicidade** — Uma nota por conceito
8. **Nomes estaveis** — Nomes de arquivo sao permalinks
