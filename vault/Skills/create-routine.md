---
title: Criar ou Revisar Rotina
description: Skill para criar rotinas agendadas ou revisar rotinas existentes. Analisa proativamente se o caso do usuario funcionaria melhor como pipeline paralela.
type: skill
created: 2026-04-07
updated: 2026-04-09
trigger: "quando o usuario quiser criar, revisar, melhorar ou otimizar uma rotina, agendar uma tarefa recorrente, ou usar /routine"
tags: [skill, routine, automation, review]
---

# Criar ou Revisar Rotina

[[Skills]]

## Modos de operacao

Esta skill opera em dois modos:

1. **Criacao** — quando o usuario quer criar uma nova rotina
2. **Revisao** — quando o usuario quer revisar, melhorar ou otimizar rotinas existentes

Detectar o modo pelo contexto da conversa. Se ambiguo, perguntar.

---

## Modo Criacao

### Passo 0 — Triagem: rotina simples ou pipeline?

ANTES de criar qualquer coisa, analisar o objetivo do usuario para determinar se seria melhor como rotina simples ou como pipeline multi-agente.

**Sinais de que deveria ser pipeline (e nao rotina):**

- O objetivo envolve **multiplas etapas distintas** (coletar → analisar → escrever → publicar)
- Precisa buscar dados de **3+ fontes independentes** (APIs, sites, bancos de dados)
- Envolve verbos como "coletar e depois analisar", "buscar de varias fontes", "produzir relatorio"
- Tem uma etapa final de **publicacao** (Notion, Telegram, email, webhook)
- Etapas intermediarias poderiam usar **modelos diferentes** (haiku para coleta, opus para analise)
- O processo todo levaria **mais de 5 minutos** com um agente unico
- Partes do trabalho sao **independentes entre si** e poderiam rodar em paralelo

**Se detectar 2+ sinais de pipeline:**

Sugerir proativamente ao usuario:

> "Pelo que voce descreveu, isso funcionaria melhor como **pipeline** em vez de rotina simples. Pipelines permitem:
> - Quebrar em X steps paralelos (coleta mais rapida)
> - Usar modelos diferentes por etapa (haiku para coleta, opus para analise)
> - Retry automatico por step se uma fonte falhar
>
> Posso criar como pipeline? Ou prefere uma rotina simples mesmo?"

Se o usuario aceitar → ler e seguir a skill [[create-pipeline]] para o restante do fluxo.
Se preferir rotina simples → continuar com os passos abaixo.

**Exemplos de triagem:**

| Objetivo do usuario | Recomendacao | Motivo |
|---------------------|--------------|--------|
| "Me lembre de beber agua as 10h" | Rotina simples | Tarefa unica, sem etapas |
| "Relatorio diario do mercado cripto" | Pipeline | Coleta + analise + escrita + publicacao |
| "Resumo dos meus emails toda manha" | Rotina simples | Uma tarefa, uma fonte |
| "Comparar precos em 5 sites e gerar relatorio" | Pipeline | 5 fontes paralelas + analise |
| "Backup do journal todo domingo" | Rotina simples | Uma tarefa mecanica |
| "Newsletter semanal com pesquisa e redacao" | Pipeline | Pesquisa + redacao + revisao + envio |

### Passo 1 — Perguntar o objetivo

O que a rotina deve fazer? Pedir descricao clara do prompt.

#### Orientacao de prompt engineering

Ajudar o usuario a formular um prompt eficaz. Se o prompt fornecido for vago, sugerir melhorias antes de prosseguir.

**Bons prompts para rotinas:**

| Exemplo | Por que funciona |
|---------|-----------------|
| "Liste os 5 principais topicos do Hacker News com links. Formato: bullet list com titulo + URL. Se a API falhar, responda 'HN indisponivel — tentarei na proxima execucao'." | Formato de output claro, instrucao de fallback, escopo definido |
| "Verifique se ha commits novos no repo X desde ontem. Se houver, resuma as mudancas em 3 bullets. Se nao houver, responda NO_REPLY." | Condicional explicito, usa NO_REPLY para silencio, escopo temporal claro |
| "Leia o journal de ontem e gere 3 perguntas de reflexao baseadas nas decisoes tomadas. Formato: lista numerada." | Fonte de dados especifica, output estruturado, quantidade definida |

**Prompts problematicos (e como melhorar):**

| Prompt ruim | Problema | Versao melhorada |
|-------------|----------|-----------------|
| "Analise o mercado cripto" | Vago — qual aspecto? Qual output? | "Liste top 5 cryptos por market cap com variacao 24h. Formato: tabela markdown." |
| "Me atualize sobre noticias" | Sem fonte, sem formato, sem escopo | "Resuma as 3 noticias mais relevantes de tech do TechCrunch hoje. Formato: titulo + 1 frase cada." |
| "Faca um backup" | Backup de que? Para onde? | "Copie o conteudo de Journal/YYYY-MM-DD.md para Notes/backups/journal-YYYY-MM-DD.md" |

**Checklist de um bom prompt de rotina:**
- [ ] Escopo claro (o que fazer, de onde, ate onde)
- [ ] Formato de output definido (bullets, tabela, texto corrido)
- [ ] Instrucao de fallback (o que fazer se algo falhar)
- [ ] Quantidade/limite quando aplicavel (top 5, ultimos 3 dias)

### Passo 2 — Perguntar horarios

Em quais horarios deve rodar? Formato HH:MM (24h). Pode ser multiplos: "09:00 e 18:00".

### Passo 3 — Perguntar dias da semana

Em quais dias? Opcoes:
- Dias uteis (mon, tue, wed, thu, fri)
- Todos os dias (*)
- Dias especificos (ex: mon, wed, fri)
- Fim de semana (sat, sun)

### Passo 4 — Perguntar modelo

Qual modelo usar? Sugerir com base no tipo de tarefa:

| Tipo de tarefa | Modelo recomendado | Motivo |
|----------------|-------------------|--------|
| Lembrete, notificacao, backup, checagem simples | `haiku` | Rapido e barato — nao precisa de raciocinio profundo |
| Resumo, formatacao, coleta de dados, listagem | `sonnet` | Equilibrio entre qualidade e custo — default seguro |
| Analise profunda, escrita criativa, decisao complexa, sintese multi-fonte | `opus` | Melhor raciocinio e qualidade de output |

Se o usuario nao souber, usar `sonnet` como default.

### Passo 4.5 — Campos opcionais

Perguntar se o usuario precisa de algum destes campos adicionais:

**`context: minimal`** — Pula o system prompt do vault (Journal, Tooling, etc.). A rotina roda apenas com os CLAUDE.md da hierarquia. Usar quando:
- A rotina NAO precisa ler o vault (ex: buscar dados externos, gerar lembretes fixos)
- Economia de tokens e velocidade sao prioridade
- O prompt eh autocontido e nao depende de contexto do vault

**`voice: true`** — Alem da mensagem de texto, envia a resposta como audio TTS no Telegram. Usar quando:
- O usuario consome rotinas em movimento (ex: briefing matinal, resumo de noticias)
- O conteudo eh curto e faz sentido ouvir (nao tabelas ou listas longas)

**`agent: {id}`** — Roteia a execucao para o workspace de um agente especifico. Usar quando:
- A rotina pertence ao dominio de um agente existente (ex: agente de financas para rotina de mercado)
- O prompt depende do CLAUDE.md ou contexto do agente
- O agente tem ferramentas ou instrucoes especificas necessarias para a tarefa

Se nenhum campo opcional for necessario, seguir em frente sem adiciona-los.

### Passo 5 — Perguntar data limite

Ate quando a rotina deve rodar? Formato YYYY-MM-DD. Opcional (sem limite se omitido).

### Passo 6 — Gerar nome do arquivo

Converter o objetivo em kebab-case para o nome do arquivo. Ex: "relatorio matinal cripto" → `relatorio-matinal-cripto.md`

### Passo 7 — Criar o arquivo

Gerar em `vault/Routines/{nome}.md` com o seguinte formato:

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

### Passo 8 — Atualizar o index

Editar `vault/Routines/Routines.md` e adicionar o novo arquivo na lista de rotinas ativas: `- [[{nome}]] — descricao curta`

### Passo 9 — Registrar no Journal

Appendar no journal do dia:
```
## HH:MM — Nova rotina criada

- Criada rotina {nome-da-rotina}
- Horarios: {horarios}
- Dias: {dias}
- Modelo: {modelo}

---
```

### Passo 10 — Confirmar

Informar ao usuario que a rotina foi criada e quando sera a proxima execucao.

---

## Modo Revisao

Acionado quando o usuario pede para revisar, melhorar ou otimizar rotinas existentes.

### Passo 1 — Identificar escopo

- Se o usuario mencionou uma rotina especifica → revisar apenas essa
- Se pediu revisao geral → listar todas as rotinas em `vault/Routines/` e analisar cada uma

### Passo 2 — Analisar cada rotina

Para cada rotina com `type: routine`, ler o arquivo completo e avaliar:

**Checklist de revisao:**

1. **Deveria ser pipeline?** — O prompt faz multiplas tarefas sequenciais? Busca dados de varias fontes? Tem etapas que poderiam rodar em paralelo? Se sim, sugerir conversao para pipeline.

2. **Modelo adequado?** — Tarefas simples (lembrete, backup, notificacao) deveriam usar `haiku`. Tarefas de analise/escrita deveriam usar `opus` ou `sonnet`. O modelo esta superestimado ou subestimado?

3. **Contexto adequado?** — Rotinas que nao precisam ler o vault inteiro deveriam usar `context: minimal` para economizar tokens e rodar mais rapido.

4. **Prompt claro?** — O prompt e especifico o suficiente? Tem instrucoes ambiguas? Faltam instrucoes de output?

5. **Schedule adequado?** — O horario e a frequencia fazem sentido para o objetivo?

6. **Execucoes recentes** — Ler `~/.claude-bot/routines-state/` e localizar o JSON do dia atual (formato `YYYY-MM-DD.json`). Verificar:
   - A rotina esta executando com sucesso ou falhando?
   - Se falhando: qual o erro? Ha quanto tempo falha consecutivamente?
   - O tempo de execucao esta dentro do esperado ou estourando timeout?
   - Se a rotina nao aparece no state file, pode nunca ter executado (schedule errado? `enabled: false`?)

### Passo 3 — Apresentar recomendacoes

Para cada rotina analisada, apresentar:
```
### {nome-da-rotina}
Status: ✅ OK / ⚠️ Melhorias sugeridas

- [melhoria 1]: motivo e beneficio
- [melhoria 2]: motivo e beneficio
```

### Passo 4 — Executar melhorias aprovadas

Perguntar quais melhorias o usuario quer aplicar. Para cada aprovada:

- Se for conversao para pipeline → ler e seguir a skill [[create-pipeline]]
- Se for mudanca de modelo/contexto/schedule → editar o arquivo diretamente
- Se for melhoria de prompt → reescrever o prompt e mostrar diff ao usuario

### Passo 5 — Registrar no Journal

Appendar no journal do dia com as mudancas aplicadas.

---

## Notas

- O prompt da rotina pode referenciar skills pelo nome
- O prompt pode incluir instrucoes para consultar Tooling e .env
- Rotinas podem ser desabilitadas mudando `enabled: false` no frontmatter
- O scheduler do bot verifica rotinas a cada 60 segundos
- Rotinas que falham aparecem com icone vermelho no menu bar
- **Se o usuario quiser uma rotina com multiplos passos/agentes/steps, usar a skill [[create-pipeline]] em vez desta.** Pipelines tem `type: pipeline` e permitem orquestrar multiplos sub-agentes com dependencias, paralelismo e modelos diferentes por step.
