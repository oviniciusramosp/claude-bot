---
title: Journal Sweep
description: Varredura noturna que consolida sessoes do dia que nao foram registradas no Journal.
type: routine
created: 2026-04-08
updated: 2026-04-09
tags: [routine, journal, maintenance, daily]
schedule:
  days: ["*"]
  times: [23:45]
model: sonnet
enabled: true
---

[[Routines]]

Voce esta executando a varredura noturna de Journal. Sua tarefa eh garantir que todas as sessoes do dia tenham registro no Journal.

## Passos

1. Leia o arquivo `~/.claude-bot/sessions.json` para ver todas as sessoes
2. Identifique sessoes com `message_count > 0` e `session_id` != null (sessoes que tiveram atividade)
3. Para cada sessao identificada:
   - Determine o Journal correto: se a sessao tem campo `agent`, use `vault/Agents/{agent}/Journal/YYYY-MM-DD.md`; senao, use `vault/Journal/YYYY-MM-DD.md`
   - Verifique se o Journal do dia ja existe e se ja tem entrada para essa sessao (procure pelo nome da sessao no conteudo)
   - Se NAO tiver entrada, use o comando bash: `claude --print --session-id <session_id> -p "Resuma brevemente esta conversa em 3-5 bullets: topicos discutidos, decisoes tomadas, acoes realizadas. Seja conciso."` para obter um resumo
   - Appende o resumo no Journal correto usando o formato padrao:

```markdown
## HH:MM — Consolidacao automatica: {nome-da-sessao}

- bullet 1
- bullet 2
- ...

---
```

4. Se o arquivo Journal do dia nao existir, crie-o com frontmatter YAML:

```yaml
---
title: "Journal YYYY-MM-DD"
description: Registro do dia YYYY-MM-DD.
type: journal
created: YYYY-MM-DD
updated: YYYY-MM-DD
tags: [journal]
---

[[Journal]]
```

Para journals de agentes, use `[[{agent-id}/Journal|Journal]]` em vez de `[[Journal]]` e adicione o tag do agente.

5. Ao final, registre no Journal principal (vault/Journal/YYYY-MM-DD.md) uma entrada de sweep:

```markdown
## 23:45 — Journal Sweep

- Sessoes verificadas: N
- Sessoes consolidadas: N (listar nomes)
- Sessoes ja registradas: N

---
```

Responda NO_REPLY ao concluir.
