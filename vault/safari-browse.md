---
title: Safari Browse
description: Skill genérica para navegar com o Safari do dono (scripts/safari.py), extrair conteúdo de sites com sessão ativa e garantir que só a janela aberta pela skill seja fechada. Use em rotinas/pipelines que precisam ler sites logados ou pesados em JS.
type: skill
created: 2026-11-16
updated: 2026-11-16
tags: [skill, safari, browsing, automation]
---

# Safari Browse

Skill para navegar com o Safari do dono de forma padronizada. O Safari deste Mac tem os logins do dono (X, Threads, bancos, Google…) e é controlado por `scripts/safari.py` (comandos rodam a partir da raiz do repo, `~/claude-bot`). Referência completa: seção "Web browsing" do `Tooling.md`.

## Uso

Chame esta skill sempre que precisar:
- Extrair texto de uma página que exige login (X, Threads, etc.)
- Extrair links e dados estruturados de feeds e listas
- Executar qualquer leitura que exige sessão ativa ou JavaScript

Para páginas públicas simples (artigos, docs, RSS), WebFetch/curl são mais rápidos — veja `main/Skills/fetch-web.md`.

## Parâmetros

- `url`: URL completa para abrir
- `settle`: segundos de espera depois do carregamento, para o JS renderizar (padrão: 2; use 3-4 em X/Threads)
- `scroll`: quantas vezes rolar até o fim antes de ler, para feeds infinitos (padrão: 0)

## Comportamento

Cada página abre na **sua própria janela do Safari** e só essa janela é fechada no fim — as abas do dono nunca são tocadas. Os comandos de uma linha já abrem, leem e fecham sozinhos.

**0. Verificar se o Safari aceita scripts (opcional, uma vez):**
```bash
python3 scripts/safari.py check
```

**1+2. Abrir e extrair texto:**
```bash
python3 scripts/safari.py text "<url>" --settle 3 [--scroll 3]
```

**3. Extração com JavaScript (resultado em JSON):**
```bash
python3 scripts/safari.py js "<url>" "<expressão JS>" --settle 3
```

**4. Fechamento:** automático nos comandos acima. Em Python, use `with safari.open_page(...) as page:` — a janela fecha ao sair do bloco, mesmo com erro:
```python
import sys
sys.path.insert(0, "/Users/viniciusramos/claude-bot/scripts")
import safari

with safari.open_page("<url>", settle=3) as page:
    page.scroll(passes=3, pause=2)   # opcional
    texto = page.text()
    dados = page.js("<expressão JS>")
```

## Extração estruturada via js (PREFERIR sobre text)

Para extrair dados estruturados (links, textos, timestamps) de feeds e listas, use `safari.py js` com seletores CSS. Isso é mais confiável que `text` (um bloco de texto sem os links dos posts).

**Exemplo — X list (posts com link, texto, timestamp):**
```bash
python3 scripts/safari.py js "https://x.com/i/lists/<id>" 'Array.from(document.querySelectorAll("article")).slice(0,10).map(a=>{const t=a.querySelector("a[href*=status]");const txt=a.querySelector("[data-testid=tweetText]");const timeEl=a.querySelector("time");return{link:t?t.href:"",time:timeEl?timeEl.getAttribute("datetime"):"",text:txt?txt.textContent.slice(0,300):""}})' --settle 4
```

**Exemplo — Threads custom feed (posts com link, user, texto):**
```bash
python3 scripts/safari.py js "<url do feed>" 'Array.from(document.querySelectorAll("a[href*=\"/post/\"]")).filter(a=>!a.href.includes("/media")).map(a=>{const postBlock=a.closest("div");let node=postBlock;for(let i=0;i<5;i++){if(node)node=node.parentElement}let text="";if(node){const spans=node.querySelectorAll("span[dir=auto]");if(spans.length>1)text=Array.from(spans).map(s=>s.textContent).join(" ").slice(0,300)}return{link:a.href,user:a.href.split("/post/")[0].replace("https://www.threads.com/",""),time:a.textContent.trim(),text:text}}).filter((p,i,arr)=>arr.findIndex(x=>x.link===p.link)===i).slice(0,8)' --settle 4
```

**Nota:** o argumento é uma *expressão* JS. Para um bloco com várias instruções, embrulhe: `"(() => { ...; return x; })()"`. Para feeds que carregam ao rolar, use Python com `page.scroll(...)` antes do `page.js(...)`.

## Regras

- **Nunca digite senhas.** Se a página cair numa tela de login, diga claramente ("o Safari não está logado no X") e pare — o dono entra uma vez no Safari.
- Se o `safari.py` der erro (`SafariError`), repasse a mensagem ao dono — ela diz qual chave ligar (Develop ▸ "Allow JavaScript from Apple Events" ou a permissão de Automação). Nunca pule em silêncio.
- Use `--settle 3-4` em sites pesados (X, Threads) para dar tempo do JS renderizar.
- Evite abrir muitas janelas em paralelo: cada uma é uma página real no Safari do dono, e X/Threads desconfiam de rajadas da mesma conta.
- **Prefira `safari.py js` com seletores CSS** sobre `text` para extração de feeds — retorna dados estruturados com links reais.
- Chats de convidados (secundários) nunca usam o Safari do dono.
- Plano B: se o Safari não conseguir, o dono pode ativar o Chrome com a extensão do Claude — pergunte antes de contar com isso.

## Exemplo de uso em rotinas

```
Use a skill Safari Browse para acessar:
- URL: https://x.com/i/lists/2043889597701062887
- settle: 4

Extraia os posts com link, horário e texto via safari.py js.
A janela é fechada automaticamente.
```
