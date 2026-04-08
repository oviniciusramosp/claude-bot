---
title: "Update Check"
description: "Verifica diariamente se ha atualizacoes do Claude Code CLI ou do claude-bot repo. Notifica apenas quando ha algo para atualizar."
type: routine
created: 2026-04-08
updated: 2026-04-08
tags: [routine, maintenance, updates]
schedule:
  days: ["*"]
  times: ["10:00"]
model: haiku
context: minimal
enabled: true
---

[[Routines]]

Verifique se ha atualizacoes disponiveis para dois componentes. Execute os comandos abaixo e analise os resultados:

**1. Claude Code CLI:**
```
/opt/homebrew/bin/claude --version
```
```
/opt/homebrew/bin/brew outdated --cask --greedy 2>/dev/null | grep claude-code
```

Se `brew outdated` retornar uma linha com `claude-code`, ha update disponivel. Se nao retornar nada, esta atualizado.

**2. claude-bot repo:**
```
cd ~/claude-bot && git fetch origin main --quiet 2>/dev/null && git rev-list HEAD..origin/main --count
```

Se o count for > 0, ha commits novos no remoto. Use `git log HEAD..origin/main --oneline` para listar o que mudou.

**Regras de resposta:**

- Se AMBOS estiverem atualizados: responda exatamente `NO_REPLY` (nada mais)
- Se ALGUM precisar de update: envie uma mensagem via Telegram (chat_id: 6948798151) usando o token do bot (leia TELEGRAM_BOT_TOKEN de ~/claude-bot/.env) com o formato:

🔄 *Updates disponiveis*

{para cada item com update, inclua uma linha:}
- *Claude Code:* X.Y.Z → A.B.C (`brew upgrade claude-code`)
- *claude-bot:* N commits atras (`cd ~/claude-bot && git pull`)

Envie via urllib (sem pip). Apos enviar, responda `NO_REPLY`.
