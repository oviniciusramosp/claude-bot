# methodology — Claude Code plugin

Three methodology skills distilled from the [claude-bot](https://github.com/viniciusramos/claude-bot) project, packaged as a standalone Claude Code plugin. Enforces root-cause investigation, Red-Green-Refactor, and evidence-before-claims across any codebase.

## Skills

| Skill | Purpose |
|---|---|
| `/methodology:systematic-debugging` | Four-phase root cause methodology. Enforces investigation before fixes. Use when debugging any bug, test failure, or unexpected behavior — BEFORE proposing a fix. |
| `/methodology:test-driven-development` | Red-Green-Refactor cycle. Write the test first, watch it fail, then write minimal code to pass. |
| `/methodology:verify-before-completion` | Gate function that requires fresh verification evidence before claiming any work is done. Use before committing, pushing, or reporting work as complete. |

All three skills are **model-invocable** — Claude will load them automatically when the context matches. You can also invoke them explicitly with the slash-command form above.

## Installation

### Local (development / testing)

Clone or copy this directory, then point Claude Code at it:

```bash
claude --plugin-dir /path/to/claude-bot/plugins/methodology
```

You can load multiple plugins by passing `--plugin-dir` multiple times.

### Via marketplace (future)

Once submitted to the [official Anthropic plugin marketplace](https://docs.claude.com/en/docs/claude-code/plugin-marketplaces), installation will be:

```text
/plugin install methodology
```

## Verification

With the plugin loaded, run `/help` inside Claude Code and confirm the three skills appear under the `methodology:` namespace. Invoke one directly to smoke-test:

```text
/methodology:verify-before-completion
```

Claude should respond with the full skill content (the verification gate function) and apply it to your current task.

## Origin

These skills live in their original form inside the claude-bot vault at `vault/main/Skills/`:
- `systematic-debugging.md`
- `test-driven-development.md`
- `verify-before-completion.md`

The plugin copies are generalized: references to claude-bot internals (`claude-fallback-bot.py`, `BOT_VERSION`, `~/.claude-bot/`, `vault/`, etc.) are replaced with generic terms so the skills apply to any project.

Both sources ultimately adapt patterns from [obra/superpowers](https://github.com/obra/superpowers).

## License

MIT. See the root of the claude-bot repository for the full license text.
