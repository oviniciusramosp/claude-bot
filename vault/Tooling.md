---
title: Tooling Preferences
description: Mapa de preferencias de ferramentas por tipo de tarefa. Consultar antes de escolher abordagem.
type: reference
created: 2026-04-07
updated: 2026-04-09
tags: [reference, tooling]
---

# Tooling Preferences

Qual ferramenta usar para cada tipo de tarefa. Consultar antes de escolher abordagem.

## Web browsing

- **PinchTab** — CLI para navegacao web com sessao logada (X, Threads). Preferir sobre urllib para evitar fingerprinting de bot.
- Repo/docs: https://github.com/pinchtab/pinchtab
- Porta padrao: `9870`
- Requer `PINCHTAB_ALLOW_EVALUATE=1` para submit via JavaScript (formularios do X e outros sites)

Comandos:
```
pinchtab nav <url> --port 9870       # navegar
pinchtab text --port 9870            # extrair texto
pinchtab snap -i -c --port 9870      # snapshot interativo
pinchtab click <ref> --port 9870     # clicar elemento
pinchtab fill <ref> "texto" --port 9870  # preencher campo
```
