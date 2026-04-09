---
title: "Análise Técnica Cripto — 21:30"
description: "Pipeline diária de análise técnica do mercado cripto (BTC, alts, macro) com publicação no Notion e notificação Telegram às 21:30."
type: pipeline
created: 2026-04-08
updated: 2026-04-09
tags: [pipeline, crypto, bitcoin, "análise-técnica", notion, daily]
schedule:
  days: ["*"]
  times: [21:30]
model: sonnet
enabled: true
agent: crypto-bro
notify: final
---

[[Routines]]

```pipeline
steps:
  # Wave 1 — coleta paralela (4 agentes simultâneos)
  - id: collect-binance
    name: "Coleta Binance (spot + futures)"
    model: haiku
    prompt_file: steps/collect-binance.md
    timeout: 300
    inactivity_timeout: 120
    retry: 1

  - id: collect-sentiment
    name: "Coleta sentimento (FnG + CoinGecko)"
    model: haiku
    prompt_file: steps/collect-sentiment.md
    timeout: 180
    inactivity_timeout: 120
    retry: 1

  - id: collect-macro
    name: "Coleta macro (Yahoo Finance)"
    model: haiku
    prompt_file: steps/collect-macro.md
    timeout: 180
    inactivity_timeout: 120
    retry: 1

  - id: collect-github
    name: "Coleta GitHub (CSVs históricos)"
    model: haiku
    prompt_file: steps/collect-github.md
    timeout: 180
    inactivity_timeout: 120
    retry: 1

  # Wave 2 — análise + capa (paralelos entre si)
  - id: analyst
    name: "Análise técnica e macro"
    model: opus
    depends_on: [collect-binance, collect-sentiment, collect-macro, collect-github]
    prompt_file: steps/analyst.md
    timeout: 900
    inactivity_timeout: 300

  - id: cover
    name: "Geração de capa"
    model: sonnet
    depends_on: [collect-binance]
    prompt_file: steps/cover.md
    timeout: 120
    inactivity_timeout: 60

  # Wave 3 — redação
  - id: writer
    name: "Redação do relatório"
    model: opus
    depends_on: [analyst]
    prompt_file: steps/writer.md
    timeout: 900
    inactivity_timeout: 300

  # Wave 4 — revisão
  - id: reviewer
    name: "Revisão e validação"
    model: opus
    depends_on: [writer]
    prompt_file: steps/reviewer.md
    timeout: 300
    inactivity_timeout: 180

  # Wave 5 — publicação
  - id: publisher
    name: "Publicação Notion + Telegram"
    model: sonnet
    depends_on: [reviewer, cover]
    prompt_file: steps/publisher.md
    timeout: 120
    inactivity_timeout: 60
    output: telegram

```
