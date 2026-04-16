---
title: PinchTab Browse
description: Skill genérica para navegar com PinchTab, extrair conteúdo e garantir cleanup de abas. Use em rotinas/pipelines que precisam ler sites com sessão ativa.
type: skill
created: 2026-04-14
updated: 2026-04-14
tags: [skill, pinchtab, browsing, automation]
---

# PinchTab Browse

Skill para navegar com PinchTab de forma padronizada e com cleanup garantido.

## Uso

Chame esta skill sempre que precisar:
- Extrair texto de uma página que exige login (X, Threads, etc.)
- Capturar links via snapshot
- Executar qualquer operação de browsing que exige sessão ativa

## Parâmetros

- `url`: URL completa para navegar
- `port`: Porta do PinchTab (padrão: 9870)

## Comportamento

**1. Navegação:**
```bash
pinchtab nav "<url>" --port <port>
sleep 3
```

**2. Extração de texto:**
```bash
pinchtab text --port <port>
```

**3. Captura de links (opcional):**
```bash
pinchtab snap -i -c --port <port>
```

**4. Cleanup OBRIGATÓRIO:**
```bash
pinchtab tabs close --port <port>
```

## Regras

- **Sempre feche a aba ao final**, mesmo em casos de erro ou saída antecipada
- Se PinchTab estiver offline (porta indisponível), retorne erro sem tentar cleanup (não há aba aberta)
- Use sleep 3 após navegação para garantir carregamento da página
- A porta padrão é 9870, mas pode ser sobrescrita por parâmetro

## Exemplo de uso em rotinas

```
Use a skill PinchTab Browse para acessar:
- URL: https://x.com/i/lists/2043889597701062887
- Porta: 9870

Extraia o texto e capture os links via snapshot.
A skill fará o cleanup automaticamente.
```
