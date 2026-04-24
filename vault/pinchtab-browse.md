---
title: PinchTab Browse
description: Skill genérica para navegar com PinchTab, extrair conteúdo e garantir cleanup de abas. Use em rotinas/pipelines que precisam ler sites com sessão ativa.
type: skill
created: 2026-04-14
updated: 2026-04-16
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
- `port`: Porta do PinchTab (padrão: 9867)

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

## Extração estruturada via eval (PREFERIR sobre text+snap)

Para extrair dados estruturados (links, textos, timestamps) de feeds e listas, use `pinchtab eval` com seletores CSS. Isso é mais confiável que `text` (blob) ou `snap` (sem links de posts).

**Exemplo — X list (posts com link, texto, timestamp):**
```bash
pinchtab eval 'Array.from(document.querySelectorAll("article")).slice(0,10).map(a=>{const t=a.querySelector("a[href*=status]");const txt=a.querySelector("[data-testid=tweetText]");const timeEl=a.querySelector("time");return{link:t?t.href:"",time:timeEl?timeEl.getAttribute("datetime"):"",text:txt?txt.textContent.slice(0,300):""}})'
```

**Exemplo — Threads custom feed (posts com link, user, texto):**
```bash
pinchtab eval 'Array.from(document.querySelectorAll("a[href*=\"/post/\"]")).filter(a=>!a.href.includes("/media")).map(a=>{const postBlock=a.closest("div");let node=postBlock;for(let i=0;i<5;i++){if(node)node=node.parentElement}let text="";if(node){const spans=node.querySelectorAll("span[dir=auto]");if(spans.length>1)text=Array.from(spans).map(s=>s.textContent).join(" ").slice(0,300)}return{link:a.href,user:a.href.split("/post/")[0].replace("https://www.threads.com/",""),time:a.textContent.trim(),text:text}}).filter((p,i,arr)=>arr.findIndex(x=>x.link===p.link)===i).slice(0,8)'
```

**Nota:** O `pinchtab eval` não aceita `--port` — conecta sempre na porta padrão (9867). Requer `PINCHTAB_ALLOW_EVALUATE=1`.

## Regras

- **Sempre feche a aba ao final**, mesmo em casos de erro ou saída antecipada
- Se PinchTab estiver offline (porta indisponível), retorne erro sem tentar cleanup (não há aba aberta)
- Use sleep 3-4 após navegação para garantir carregamento da página
- A porta padrão é 9867, mas pode ser sobrescrita por parâmetro
- **Prefira `pinchtab eval` com seletores CSS** sobre `text`+`snap` para extração de feeds — retorna dados estruturados com links reais

## Exemplo de uso em rotinas

```
Use a skill PinchTab Browse para acessar:
- URL: https://x.com/i/lists/2043889597701062887
- Porta: 9867

Extraia o texto e capture os links via snapshot.
A skill fará o cleanup automaticamente.
```
