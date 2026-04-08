---
title: Criar Nova Rotina
description: Skill interativa para criar rotinas agendadas. Guia o usuario com perguntas sobre horario, dias, modelo e prompt, e gera o arquivo .md em vault/Routines/.
type: skill
created: 2026-04-07
updated: 2026-04-07
trigger: "quando o usuario quiser criar uma nova rotina, agendar uma tarefa recorrente, ou usar /routine"
tags: [skill, routine, automation]
---

# Criar Nova Rotina

[[Skills]]

## Objetivo

Ajudar o usuario a criar uma rotina agendada que executa automaticamente um prompt no Claude Code em horarios definidos.

## Dependencias

- Routines/ — destino dos arquivos gerados por esta skill

## Passos

1. **Perguntar o objetivo** — O que a rotina deve fazer? Pedir descricao clara do prompt.

2. **Perguntar horarios** — Em quais horarios deve rodar? Formato HH:MM (24h). Pode ser multiplos: "09:00 e 18:00".

3. **Perguntar dias da semana** — Em quais dias? Opcoes:
   - Dias uteis (mon, tue, wed, thu, fri)
   - Todos os dias (*)
   - Dias especificos (ex: mon, wed, fri)
   - Fim de semana (sat, sun)

4. **Perguntar modelo** — Qual modelo usar? Default: sonnet. Opcoes: sonnet, opus, haiku.

5. **Perguntar data limite** — Ate quando a rotina deve rodar? Formato YYYY-MM-DD. Opcional (sem limite se omitido).

6. **Gerar nome do arquivo** — Converter o objetivo em kebab-case para o nome do arquivo. Ex: "relatorio matinal cripto" → `relatorio-matinal-cripto.md`

7. **Criar o arquivo** — Gerar em `vault/Routines/{nome}.md` com o seguinte formato:

```yaml
---
title: {titulo descritivo}
description: {frase curta sobre o que a rotina faz e quando roda}
type: routine
created: {YYYY-MM-DD}
updated: {YYYY-MM-DD}
tags: [routine, {categorias relevantes}]
schedule:
  times: ["{HH:MM}", "{HH:MM}"]
  days: [{dias}]
  until: "{YYYY-MM-DD}"
model: {modelo}
enabled: true
---

[[Routines]]

{Prompt completo que sera enviado ao Claude Code}
```

A primeira linha do body DEVE ser `[[Routines]]` (link para o index pai).

8. **Atualizar o index** — Editar `vault/Routines/Routines.md` e adicionar o novo arquivo na lista de rotinas ativas: `- [[{nome}]] — descricao curta`

9. **Registrar no Journal** — Appendar no journal do dia:
```
## HH:MM — Nova rotina criada

- Criada rotina [[{nome-da-rotina}]]
- Horarios: {horarios}
- Dias: {dias}
- Modelo: {modelo}

---
```

10. **Confirmar** — Informar ao usuario que a rotina foi criada e quando sera a proxima execucao.

## Notas

- O prompt da rotina pode referenciar skills pelo nome
- O prompt pode incluir instrucoes para consultar Tooling e .env
- Rotinas podem ser desabilitadas mudando `enabled: false` no frontmatter
- O scheduler do bot verifica rotinas a cada 60 segundos
- Rotinas que falham aparecem com icone vermelho no menu bar
