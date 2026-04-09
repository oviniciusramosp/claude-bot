---
title: Vault Graph Update
description: Regenera o knowledge graph lightweight do vault a partir de frontmatter e wikilinks. Sem custo de LLM.
type: routine
created: 2026-04-09
updated: 2026-04-09
tags: [routine, vault, graph, maintenance]
schedule:
  times: ["04:00"]
  days: ["*"]
model: haiku
enabled: true
context: minimal
---

[[Routines]]

Regenere o knowledge graph do vault executando o script Python abaixo. Este script extrai relacionamentos a partir de frontmatter YAML e wikilinks — sem LLM, custo zero.

```bash
python3 /Users/viniciusramos/claude-bot/scripts/vault-graph-builder.py
```

Após a execução:
1. Verifique se `vault/.graphs/graph.json` foi gerado/atualizado
2. Se houver erros, reporte o erro específico
3. Se sucesso, responda com `NO_REPLY`
