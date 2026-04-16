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
- [[main/Notes/btc-preco-matinal|btc-preco-matinal]] — Only active routine: Bitcoin price check daily at 08:30
- [[main/Notes/btc-preco-matinal-routine|btc-preco-matinal-routine]] — Daily 8:30 BTC price alert at `~/claude-bot/vault/Routines/btc-preco-matinal.md`, sends to chat_id 6948798151 via Claudinho bot
- [[main/Notes/create-agent-skill-location|create-agent-skill-location]] — Skill instructions live at `vault/main/Skills/create-agent.md`
- [[main/Notes/cron-agentid-null-routing|cron-agentid-null-routing]] — null agentId in cron jobs routes to main/Jarvis — always set explicit agentId per pipeline
- [[main/Notes/crypto-pipeline-model-split|crypto-pipeline-model-split]] — Manager=Opus, Buscador=Sonnet, Analista=Opus, Escritor=Sonnet, Revisor=Sonnet
- [[main/Notes/enospc-tmp-fix|enospc-tmp-fix]] — Claude Code temp output lives in `/private/tmp/claude-501/`; delete it to recover from ENOSPC on `/tmp`
- [[main/Notes/framer-csr-seo|framer-csr-seo]] — Framer renders via JS (CSR); Google crawlers may not index content properly — always verify with Google Search Console URL Inspection tool
- [[main/Notes/glm-thinking-leak|glm-thinking-leak]] — Z.ai payloads must suppress thinking tokens via `params.thinking: "off"` in model catalog
- [[main/Notes/jellyfin-freeze-pattern|jellyfin-freeze-pattern]] — Three consecutive tool timeouts investigating Jellyfin — avoid long-running subagent chains for this task; use direct Bash commands instead
- [[main/Notes/jellyfin-media-path|jellyfin-media-path]] — Series library at /Volumes/SSD_VR4/Media/series/, movies at /Volumes/SSD_VR4/Media/movies/
- [[main/Notes/jellyfin-superstore-unresolved|jellyfin-superstore-unresolved]] — Superstore not recognized by Jellyfin; cause unknown; investigation never completed across 3+ sessions
- [[main/Notes/launchd-is-authoritative|launchd-is-authoritative]] — `com.vr.claude-bot-menubar` LaunchAgent owns the menubar process — manual launches cause duplicate instances
- [[main/Notes/menubar-python-path|menubar-python-path]] — `rumps` is installed under Python 3.9 CLI tools path, not Homebrew — must use `/Library/Developer/CommandLineTools/Library/Frameworks/Python
- [[main/Notes/oc-agentid-null|oc-agentid-null]] — missing agentId in cron jobs silently routes to main/Jarvis agent instead of intended agent
- [[main/Notes/oc-lightcontext|oc-lightcontext]] — `lightContext: true` in cron payload skips full agent bootstrap, saves tokens on frequent/simple runs
- [[main/Notes/oc-model-precedence|oc-model-precedence]] — spawn-level model > cron payload model > agent model > agents.defaults — innermost wins
- [[main/Notes/oc-telegram-polling-conflict|oc-telegram-polling-conflict]] — Only one process can call Telegram `getUpdates` per bot token; `claude-fallback-bot.py` and OC gateway share the same token, causing 409 err
- [[main/Notes/palmeiras-daily-single-agent|palmeiras-daily-single-agent]] — Palmeiras daily is single-agent (no spawns); model must be set in cron payload, not spawn call
- [[main/Notes/palmeiras-pipeline-model-split|palmeiras-pipeline-model-split]] — Scout=Haiku, Escritor=Opus, Editor=Sonnet, Revisor=Sonnet; Opus needed because Escritor does raw web_fetch
- [[main/Notes/sessions-spawn-model-precedence|sessions-spawn-model-precedence]] — spawn-level model > cron payload model > agent model > agents.defaults — most granular wins
- [[main/Notes/sf-symbols-appkit|sf-symbols-appkit]] — Set menu bar icon via `self._status_item.button().setImage_()` and menu item icons via `item._menuitem.setImage_()` using `NSImage.imageWith
- [[main/Notes/telegram-polling-exclusivity|telegram-polling-exclusivity]] — Only one process can call `getUpdates` per bot token; concurrent pollers cause 409 Conflict
- [[main/Notes/telegram-privacy-mode|telegram-privacy-mode]] — BotFather privacy mode must be disabled AND bot re-added to group for it to receive all non-command messages
- [[main/Notes/tmp-enospc-pattern|tmp-enospc-pattern]] — Claude Code writes Bash output to `/private/tmp/claude-501/`; when `/tmp` fills up, delete that dir to recover
- [[main/Notes/vault-agent-isolation|vault-agent-isolation]] — Agent dirs detected by presence of `agent-<dirname>.md`; no cross-agent inheritance
- [[main/Notes/zai-glm51-thinking|zai-glm51-thinking]] — GLM 5.1 reasons by default — always pass `{"thinking":{"type":"disabled"}}` via `extra_body` to avoid token burn
- [[main/Notes/zai-glm51-thinking-disabled|zai-glm51-thinking-disabled]] — glm-5.1 reasons by default; always pass {"thinking":{"type":"disabled"}} via extra_body unless deep reasoning needed
<!-- vault-query:end -->
