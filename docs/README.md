# Claude Bot -- Documentation

A macOS Telegram bot that bridges [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) to Telegram, giving you remote access to Claude from your phone. Includes a native macOS menu bar app, session persistence, scheduled routines, voice transcription, and an Obsidian-compatible knowledge vault that grows across every conversation.

## Getting Started

- [Installation Guide](installation.md) -- Prerequisites, setup, and service management
- [Configuration Reference](configuration.md) -- Environment variables, .env files, and runtime settings

## Architecture

- [System Architecture](architecture.md) -- Components, threading model, data flow, and key classes
- [Vault Structure](vault-structure.md) -- Knowledge base layout, frontmatter rules, and Obsidian integration

## User Guides

- [Sessions & Agents](sessions-and-agents.md) -- Session lifecycle, agent creation, group topics
- [Routines & Pipelines](routines-and-pipelines.md) -- Scheduled tasks, pipeline DAGs, and cron-like execution
- [Audio & Images](audio-and-images.md) -- Voice transcription, image analysis, and media handling

## Reference

- [API Reference](api-reference.md) -- Control server HTTP API and internal interfaces
- [Troubleshooting](troubleshooting.md) -- Common issues, log locations, and diagnostic steps
- [Development Guide](development.md) -- Contributing, adding commands, versioning, and code conventions
