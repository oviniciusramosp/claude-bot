---
title: "Análise Técnica Cripto — 21:30"
description: "Pipeline diária de análise técnica do mercado cripto (BTC, alts, macro) com publicação no Notion e notificação Telegram às 21:30."
type: pipeline
created: 2026-04-08
updated: 2026-04-08
tags: [pipeline, crypto, bitcoin, análise-técnica, notion, daily]
schedule:
  times: ["21:30"]
  days: ["*"]
model: sonnet
agent: crypto-bro
enabled: true
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
    inactivity_timeout: 300

  - id: analyst
    name: "Análise técnica e macro"
    model: opus
    prompt_file: steps/analyst.md
    depends_on: [collector]
    timeout: 600
    inactivity_timeout: 300

  - id: cover
    name: "Geração de capa"
    model: sonnet
    prompt_file: steps/cover.md
    depends_on: [collector]
    timeout: 120
    inactivity_timeout: 60

  - id: writer
    name: "Redação do relatório"
    model: opus
    prompt_file: steps/writer.md
    depends_on: [analyst]
    timeout: 600
    inactivity_timeout: 300

  - id: reviewer
    name: "Revisão e validação"
    model: opus
    prompt_file: steps/reviewer.md
    depends_on: [writer]
    timeout: 300
    inactivity_timeout: 180

  - id: publisher
    name: "Publicação Notion + Telegram"
    model: sonnet
    prompt_file: steps/publisher.md
    depends_on: [reviewer, cover]
    timeout: 120
    inactivity_timeout: 60
    output: telegram
```
