---
title: "Análise Técnica Cripto — 21:30"
description: "Pipeline diária de análise técnica do mercado cripto (BTC, alts, macro) com publicação no Notion e notificação Telegram às 21:30."
type: pipeline
created: 2026-04-08
updated: 2026-04-08
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
  - id: collector
    name: "Coleta de dados"
    model: haiku
    prompt_file: steps/collector.md
    timeout: 600

  - id: analyst
    name: "Análise técnica e macro"
    model: opus
    depends_on: [collector]
    prompt_file: steps/analyst.md
    timeout: 600

  - id: cover
    name: "Geração de capa"
    model: sonnet
    depends_on: [collector]
    prompt_file: steps/cover.md
    timeout: 120
    inactivity_timeout: 60

  - id: writer
    name: "Redação do relatório"
    model: opus
    depends_on: [analyst]
    prompt_file: steps/writer.md
    timeout: 600

  - id: reviewer
    name: "Revisão e validação"
    model: opus
    depends_on: [writer]
    prompt_file: steps/reviewer.md
    timeout: 300
    inactivity_timeout: 180

  - id: publisher
    name: "Publicação Notion + Telegram"
    model: sonnet
    depends_on: [reviewer, cover]
    prompt_file: steps/publisher.md
    timeout: 120
    inactivity_timeout: 60
    output: telegram

```
