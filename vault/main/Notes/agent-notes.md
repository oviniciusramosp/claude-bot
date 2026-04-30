---
title: Notes
description: Notes belonging to the main agent.
type: index
created: 2026-04-11
updated: 2026-04-11
tags: [index, notes]
---

# Notes (main)

<!-- vault-query:start filter="type=note" scope="main/Notes" sort="title" format="- [[{link}|{stem}]] — {description}" -->
- [[main/Notes/agent-detection-rule|agent-detection-rule]] — A vault directory is an agent iff it contains `agent-<dirname>.md`
- [[main/Notes/agentid-required-in-cron|agentid-required-in-cron]] — Missing agentId in cron job payload silently routes execution to main/Jarvis instead of the intended agent.
- [[main/Notes/auto-compact-silent-error-fix|auto-compact-silent-error-fix]] — `_auto_compact._worker()` must call `self.send_message()` on exception, not just `logger.error()` — asymmetry with `cmd_compact` was a bug
- [[main/Notes/btc-preco-matinal|btc-preco-matinal]] — Only active routine: Bitcoin price check daily at 08:30
- [[main/Notes/btc-preco-matinal-routine|btc-preco-matinal-routine]] — Daily 8:30 BTC price alert at `~/claude-bot/vault/Routines/btc-preco-matinal.md`, sends to chat_id 6948798151 via Claudinho bot
- [[main/Notes/concurrent-context-writes|concurrent-context-writes]] — `.context.md` is written by multiple parallel sessions; re-read before write is insufficient under high contention — deliver inline and let 
- [[main/Notes/context-file-write-conflict|context-file-write-conflict]] — Background bot process modifies .context.md between Read and Write; use Bash heredoc to force-overwrite instead of Edit/Write tools
- [[main/Notes/control-server-auth|control-server-auth]] — Control server uses `X-Bot-Token` header (not `Authorization: Bearer`) for all API calls to `127.0.0.1:27182`
- [[main/Notes/create-agent-skill-location|create-agent-skill-location]] — Skill instructions live at `vault/main/Skills/create-agent.md`
- [[main/Notes/cron-agentid-null-routing|cron-agentid-null-routing]] — null agentId in cron jobs routes to main/Jarvis — always set explicit agentId per pipeline
- [[main/Notes/cron-agentid-required|cron-agentid-required]] — Jobs sem agentId roteiam silenciosamente para main/Jarvis — sempre declarar agentId explícito
- [[main/Notes/crypto-forbidden-terms|crypto-forbidden-terms]] — 7 termos proibidos: `halving`, `histórico`, `sem precedentes`, `hawkish`, `dovish`, `bear case`, superlativos não verificados
- [[main/Notes/crypto-pipeline-model-split|crypto-pipeline-model-split]] — Manager=Opus, Buscador=Sonnet, Analista=Opus, Escritor=Sonnet, Revisor=Sonnet
- [[main/Notes/crypto-pipeline-spawn-models|crypto-pipeline-spawn-models]] — Researcher=Sonnet, Analista=Opus, Escritor=Sonnet (pré-digerido)
- [[main/Notes/crypto-workflow-skill|crypto-workflow-skill]] — Full pipeline context skill at `~/.openclaw/workspace/skills/crypto-workflow/SKILL.md`; self-updates on 10 defined triggers.
- [[main/Notes/dashboard-launchagent|dashboard-launchagent]] — LaunchAgent at `~/Library/LaunchAgents/com.jarvis.dashboard.plist` keeps server alive; always use `launchctl stop/start` to restart
- [[main/Notes/dashboard-static-ip|dashboard-static-ip]] — Mac mini Wi-Fi set to static `192.168.68.125/24` gw `192.168.68.1` via `networksetup -setmanual`.
- [[main/Notes/enospc-tmp-fix|enospc-tmp-fix]] — Claude Code temp output lives in `/private/tmp/claude-501/`; delete it to recover from ENOSPC on `/tmp`
- [[main/Notes/forbidden-terms-7|forbidden-terms-7]] — Seven banned terms: halving, histórico, sem precedentes, hawkish, dovish, bear case, unverified superlatives.
- [[main/Notes/forbidden-terms-cripto|forbidden-terms-cripto]] — 7 termos proibidos: halving, histórico, sem precedentes, hawkish, dovish, bear case, unverified superlatives
- [[main/Notes/forbidden-terms-list|forbidden-terms-list]] — 7 banned terms in TA posts: halving, histórico, sem precedentes, hawkish, dovish, bear case, unverified superlatives
- [[main/Notes/framer-csr-seo|framer-csr-seo]] — Framer renders via JS (CSR); Google crawlers may not index content properly — always verify with Google Search Console URL Inspection tool
- [[main/Notes/glm-parallel-rate-limit-risk|glm-parallel-rate-limit-risk]] — Simultaneous GLM-5.1 sessions (e.g. Contador + Digests routines) exhaust z.AI quota; global backoff coordination is an open candidate fix
- [[main/Notes/glm-thinking-disabled|glm-thinking-disabled]] — Always pass `thinking: {type: "disabled"}` via `extra_body` for glm-5.1 to avoid burning tokens on reasoning_content
- [[main/Notes/glm-thinking-leak|glm-thinking-leak]] — Z.ai payloads must suppress thinking tokens via `params.thinking: "off"` in model catalog
- [[main/Notes/homebridge-auth-endpoint|homebridge-auth-endpoint]] — Correct login endpoint is `/api/auth/login` (not `/api/sign-in`); credentials in `~/.homebridge/auth.json`
- [[main/Notes/homebridge-hap-cache|homebridge-hap-cache]] — `/api/accessories` returns `[]` until HAP scan runs; use `/api/accessories/layout` as immediate fallback
- [[main/Notes/homebridge-service-grouping|homebridge-service-grouping]] — HomeBridge exposes each HomeKit service separately; backend must group by `name` field to map to physical devices
- [[main/Notes/instruction-files-are-skills|instruction-files-are-skills]] — Markdown instruction files define sub-agent behavior; scripts handle mechanics only — never replace instructions with Python.
- [[main/Notes/jarvis-dashboard-stack|jarvis-dashboard-stack]] — Vue 3 + TypeScript + Vite frontend (`jarvis-dashboard/client/`), Express backend (`jarvis-dashboard/server.js`), Transmission RPC at localho
- [[main/Notes/jellyfin-dashboard-stack|jellyfin-dashboard-stack]] — Vue 3 + Vite frontend at `jarvis-dashboard/client/`, Express backend at `jarvis-dashboard/server.js`, served on port 4000
- [[main/Notes/jellyfin-freeze-pattern|jellyfin-freeze-pattern]] — Three consecutive tool timeouts investigating Jellyfin — avoid long-running subagent chains for this task; use direct Bash commands instead
- [[main/Notes/jellyfin-mblink|jellyfin-mblink]] — `.mblink` files map Jellyfin virtual library folders to actual filesystem paths (one path per line)
- [[main/Notes/jellyfin-media-path|jellyfin-media-path]] — Series library at /Volumes/SSD_VR4/Media/series/, movies at /Volumes/SSD_VR4/Media/movies/
- [[main/Notes/jellyfin-naming|jellyfin-naming]] — Jellyfin TV series naming: `Show Name (Year)/Season XX/SxxExx.ext`
- [[main/Notes/jellyfin-subagent-freeze|jellyfin-subagent-freeze]] — Subagente chains travam (~40min) ao investigar Jellyfin; usar apenas Bash direto para este problema
- [[main/Notes/jellyfin-superstore-freeze|jellyfin-superstore-freeze]] — Subagent chains travam nesta tarefa; usar Bash direto
- [[main/Notes/jellyfin-superstore-unresolved|jellyfin-superstore-unresolved]] — Superstore not recognized by Jellyfin; cause unknown; investigation never completed across 3+ sessions
- [[main/Notes/jellyfin-torrent-title-mismatch|jellyfin-torrent-title-mismatch]] — TMDB PT-BR titles differ from disk folder names; pass multiple title candidates to subtitle counter
- [[main/Notes/launchagent-process-ownership|launchagent-process-ownership]] — `com.jarvis.dashboard` LaunchAgent owns the server process; use `launchctl stop/start` not manual `node server.js`
- [[main/Notes/launchd-authoritative|launchd-authoritative]] — `com.vr.claude-bot-menubar` LaunchAgent is the sole process manager; never start manually via nohup
- [[main/Notes/launchd-is-authoritative|launchd-is-authoritative]] — `com.vr.claude-bot-menubar` LaunchAgent owns the menubar process — manual launches cause duplicate instances
- [[main/Notes/launchd-menubar|launchd-menubar]] — launchd plist `com.vr.claude-bot-menubar` is the only process manager for the menubar app — never start manually with nohup
- [[main/Notes/menubar-app-path|menubar-app-path]] — Menubar app at `~/claude-bot/claude-bot-menubar.py`; managed exclusively by launchd `com.vr.claude-bot-menubar`
- [[main/Notes/menubar-launchd-only|menubar-launchd-only]] — Only launchd (`com.vr.claude-bot-menubar`) should manage the menubar process — manual launches create duplicates
- [[main/Notes/menubar-python|menubar-python]] — rumps requires Python 3.9 from CLI tools, not Homebrew Python
- [[main/Notes/menubar-python-path|menubar-python-path]] — `rumps` is installed under Python 3.9 CLI tools path, not Homebrew — must use `/Library/Developer/CommandLineTools/Library/Frameworks/Python
- [[main/Notes/notion-tags-10|notion-tags-10]] — Exactly 10 valid tags: Bitcoin, Notícias, Análises, Altcoins, ETH, SOL, XRP, LTC, Stablecoins, DeFi — no additions ever.
- [[main/Notes/notion-tags-constraint|notion-tags-constraint]] — Exatamente 10 tags válidas; Adoção e Regulação removidas de todos os instruction files
- [[main/Notes/notion-valid-tags|notion-valid-tags]] — Exactly 10 valid tags; Adoção and Regulação removed from all instruction files
- [[main/Notes/oc-agentid-null|oc-agentid-null]] — missing agentId in cron jobs silently routes to main/Jarvis agent instead of intended agent
- [[main/Notes/oc-agentid-routing|oc-agentid-routing]] — cron jobs without agentId silently route to main/Jarvis instead of intended agent
- [[main/Notes/oc-default-model|oc-default-model]] — OC primary model is `zai/glm-5.1`; fallback chain: codex → opus → flash → jarvis-local
- [[main/Notes/oc-gateway-openai-compat|oc-gateway-openai-compat]] — OC Gateway exposes OpenAI-compatible `/v1/chat/completions` on port 18789 with bearer token auth and SSE streaming
- [[main/Notes/oc-glm-thinking|oc-glm-thinking]] — glm-5.1 and glm-4.5-flash reason by default — always pass thinking:{type:"disabled"} via extra_body
- [[main/Notes/oc-lightcontext|oc-lightcontext]] — `lightContext: true` in cron payload skips full agent bootstrap, saves tokens on frequent/simple runs
- [[main/Notes/oc-model-precedence|oc-model-precedence]] — spawn-level model > cron payload model > agent model > agents.defaults — innermost wins
- [[main/Notes/oc-primary-model|oc-primary-model]] — OC default model is `anthropic/claude-sonnet-4-6`; first fallback is `anthropic/claude-opus-4-6`
- [[main/Notes/oc-spawn-model-precedence|oc-spawn-model-precedence]] — sessions_spawn model > cron payload model > agent config model > agents.defaults
- [[main/Notes/oc-telegram-polling-conflict|oc-telegram-polling-conflict]] — Only one process can call Telegram `getUpdates` per bot token; `claude-fallback-bot.py` and OC gateway share the same token, causing 409 err
- [[main/Notes/openclaw-session-warmth|openclaw-session-warmth]] — Research notes on OpenClaw PR #69679 (keep Claude CLI sessions warm) — persistent stdio process per session, 10-min idle cleanup, resume via session id. Assess applicability to claude-bot.
- [[main/Notes/oss-watchlist|oss-watchlist]] — External PRs and commits flagged by OSS Radar for monitoring. Daily oss-radar routine checks state changes and surfaces updates when watched items merge, close, or gain major activity.
- [[main/Notes/palmeiras-daily-single-agent|palmeiras-daily-single-agent]] — Palmeiras daily is single-agent (no spawns); model must be set in cron payload, not spawn call
- [[main/Notes/palmeiras-pipeline-model-split|palmeiras-pipeline-model-split]] — Scout=Haiku, Escritor=Opus, Editor=Sonnet, Revisor=Sonnet; Opus needed because Escritor does raw web_fetch
- [[main/Notes/palmeiras-pipeline-spawn-models|palmeiras-pipeline-spawn-models]] — Scout=Haiku, Escritor=Opus, Editor=Sonnet, Revisor=Sonnet, Publisher=Sonnet
- [[main/Notes/phantom-session-consolidation|phantom-session-consolidation]] — Agents created via /onboard and auto-activated immediately have no CLI conversation history; background consolidation will always fail with 
- [[main/Notes/python-rumps-path|python-rumps-path]] — rumps requires Python 3.9 at `/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/Resources/Python.app/Con
- [[main/Notes/python39-for-rumps|python39-for-rumps]] — rumps requires Python 3.9 from CLI tools: `/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/Resources/P
- [[main/Notes/run-routine-sh|run-routine-sh]] — `bash scripts/run-routine.sh <name>` lets any Claude subprocess trigger a bot routine via the control server at port 27182 using `~/.claude-
- [[main/Notes/sessions-spawn-model-precedence|sessions-spawn-model-precedence]] — spawn-level model > cron payload model > agent model > agents.defaults — most granular wins
- [[main/Notes/sf-symbols-appkit|sf-symbols-appkit]] — Set menu bar icon via `self._status_item.button().setImage_()` and menu item icons via `item._menuitem.setImage_()` using `NSImage.imageWith
- [[main/Notes/subagent-freeze-pattern|subagent-freeze-pattern]] — Tarefas de investigação Jellyfin via subagentes travam ~40min sem output; usar Bash direto obrigatoriamente
- [[main/Notes/subtitle-count-logic|subtitle-count-logic]] — `countSubtitlesForTitle(...titles)` walks MEDIA_DIRS for `.pt-BR.srt`, accepts multiple title candidates, result capped at `videosTotal`
- [[main/Notes/ta-post-non-repetition|ta-post-non-repetition]] — Each TA H2 section must contain only information not already stated in prior sections.
- [[main/Notes/ta-post-section-limits|ta-post-section-limits]] — Cenário Pessimista: 6-8 frases (no bull repeat); O Que Monitorar: 6-9 frases (no prior-section repeat)
- [[main/Notes/ta-section-limits|ta-section-limits]] — Cenário Pessimista 6-8 frases, O Que Monitorar 6-9 frases — sem repetição de seções anteriores
- [[main/Notes/telegram-polling-exclusivity|telegram-polling-exclusivity]] — Only one process can call `getUpdates` per bot token; concurrent pollers cause 409 Conflict
- [[main/Notes/telegram-privacy-mode|telegram-privacy-mode]] — BotFather privacy mode must be disabled AND bot re-added to group for it to receive all non-command messages
- [[main/Notes/telegram-thread-ids|telegram-thread-ids]] — Telegram group `-1003358574607` threads: 1=AI/Tech, 2=Palmeiras, 3=Crypto reports, 5=Pessoal, 183=Mercados preditivos, 894=Social Media
- [[main/Notes/tmp-dir-enospc|tmp-dir-enospc]] — Claude Code Bash tool output goes to `/private/tmp/claude-501/`; if full, Bash breaks — fix: `rm -rf /private/tmp/claude-501/`
- [[main/Notes/tmp-enospc-fix|tmp-enospc-fix]] — `rm -rf /private/tmp/claude-501/` clears ENOSPC that breaks Claude Code Bash tool on macOS.
- [[main/Notes/tmp-enospc-pattern|tmp-enospc-pattern]] — Claude Code writes Bash output to `/private/tmp/claude-501/`; when `/tmp` fills up, delete that dir to recover
- [[main/Notes/transmission-files-api|transmission-files-api]] — `/api/transmission/files/:id` calls Transmission RPC `torrent-get` with `files` field; `videosTotal`/`videosCompleted` computed server-side,
- [[main/Notes/transmission-rpc-files|transmission-rpc-files]] — `torrent-get` with `files` field returns per-file `bytesCompleted`/`length` for episode progress tracking
- [[main/Notes/vault-agent-detection|vault-agent-detection]] — Agent directories detected solely by presence of `agent-<dirname>.md` file
- [[main/Notes/vault-agent-isolation|vault-agent-isolation]] — Agent dirs detected by presence of `agent-<dirname>.md`; no cross-agent inheritance
- [[main/Notes/vault-routine-index|vault-routine-index]] — `vault/Routines/Routines.md` is the single index of all active routines
- [[main/Notes/zai-glm51-thinking|zai-glm51-thinking]] — GLM 5.1 reasons by default — always pass `{"thinking":{"type":"disabled"}}` via `extra_body` to avoid token burn
- [[main/Notes/zai-glm51-thinking-disabled|zai-glm51-thinking-disabled]] — glm-5.1 reasons by default; always pass {"thinking":{"type":"disabled"}} via extra_body unless deep reasoning needed
- [[main/Notes/zai-thinking-disabled|zai-thinking-disabled]] — GLM 5.1 must always receive `{"thinking":{"type":"disabled"}}` via `extra_body` or it burns tokens on reasoning_content.
<!-- vault-query:end -->
