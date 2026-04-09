---
title: Extract Knowledge
description: Extrai conceitos duráveis de outputs de pipelines ou conversas e cria/atualiza notas em Notes/. Automatiza a população da knowledge base.
type: skill
trigger: "ao final de um pipeline ou quando o usuario pedir para registrar conhecimento aprendido"
created: 2026-04-09
updated: 2026-04-09
tags: [skill, knowledge, extraction, notes]
---

## Objetivo

Transformar outputs brutos (de pipelines, conversas, ou análises) em notas duráveis na pasta `Notes/`. Cada nota captura um conceito atômico com frontmatter completo, links corretos, e campo `related` para relacionamentos semânticos.

## Quando usar

- Ao final de pipelines que geram análises (ex: `crypto-ta-analise`)
- Quando o usuário menciona algo que deveria virar conhecimento durável
- Quando um padrão ou insight se repete em múltiplas conversas
- Manualmente via `/extract` ou "extraia conhecimento de X"

## Passos

1. **Identificar conceitos extraíveis** — Leia o material fonte (output de pipeline em `/tmp/claude-pipeline-*/data/`, mensagem do usuário, ou arquivo indicado). Identifique conceitos que são:
   - Duráveis (não efêmeros — válidos além de hoje)
   - Atômicos (um conceito por nota)
   - Não redundantes (verifique se já existe nota similar em `Notes/`)

2. **Verificar duplicatas** — Glob `Notes/*.md`, ler frontmatters. Se já existir nota sobre o mesmo conceito, ATUALIZAR em vez de criar nova. Adicionar seção `## Atualização YYYY-MM-DD` ao final.

3. **Criar nota** — Para cada conceito novo:

   ```yaml
   ---
   title: Nome do Conceito
   description: Frase que explica o conceito e quando é relevante consultá-lo.
   type: note
   created: YYYY-MM-DD
   updated: YYYY-MM-DD
   tags: [dominio, subtopico]
   source: "pipeline:crypto-ta-analise" | "conversa" | "manual"
   confidence: extracted | inferred
   related:
     - file: "arquivo-relacionado"
       type: extracted | inferred
       reason: "motivo da relação"
   ---

   [[Notes]]

   ## Conteúdo

   [Explicação concisa do conceito — máximo 3 parágrafos]

   ## Contexto

   - Fonte: [de onde veio este conhecimento]
   - Data da observação: YYYY-MM-DD
   - Condições: [em que contexto isso é verdade]
   ```

4. **Atualizar index** — Adicionar `- [[nome-da-nota]] — descrição` em `Notes/Notes.md`

5. **Registrar no Journal** — Entrada: `Nota criada/atualizada: nome-da-nota (fonte: X)`

## Critérios de qualidade

- `description` deve ser suficiente para decidir se a nota merece leitura sem abri-la
- Tags devem permitir filtragem eficiente (domínio + subtópico)
- Campo `related` conecta semanticamente sem poluir o Graph View
- `confidence: extracted` = fato direto da fonte; `inferred` = conclusão derivada
- Notas NÃO devem conter dados efêmeros (preços do dia, valores pontuais)

## Exemplos de extração

**De pipeline crypto-ta-analise:**
- ✅ "BTC historicamente respeita EMA 200w como suporte em bear markets" → nota durável
- ✅ "Funding rate negativo prolongado precede reversões de alta em 70% dos casos" → nota durável
- ❌ "BTC está a $84,500 hoje" → efêmero, não extrair
- ❌ "Fear & Greed está em 45" → efêmero, não extrair

**De conversa:**
- ✅ "O usuário prefere análises com gráficos embutidos" → nota sobre preferências
- ✅ "A API do Binance tem rate limit de 1200 req/min" → nota de referência técnica
- ❌ "O usuário perguntou sobre o preço do ETH" → não durável

## Notas

- Priorize qualidade sobre quantidade — 1 nota boa > 5 notas fracas
- Se não há conceito durável a extrair, não force. Retorne "Nenhum conceito durável identificado."
- O campo `source` permite rastrear a proveniência do conhecimento
- Ao atualizar nota existente, incrementar `updated` e adicionar seção de atualização ao final
