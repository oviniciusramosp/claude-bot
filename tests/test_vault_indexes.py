"""Tests for scripts/vault_indexes.py."""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import vault_indexes as vi_mod  # noqa: E402


def _write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _vault_with_routines(tmp: Path) -> Path:
    today = date.today().isoformat()
    v = tmp / "vault"
    _write(
        v / "Routines" / "alpha.md",
        f"""---
title: "Alpha"
description: "First routine"
type: routine
created: {today}
updated: {today}
tags: [routine]
schedule:
  times: ["09:00"]
  days: ["*"]
model: sonnet
agent: a-agent
enabled: true
---

[[Routines]]
""",
    )
    _write(
        v / "Routines" / "bravo.md",
        f"""---
title: "Bravo"
description: "Second routine"
type: routine
created: {today}
updated: {today}
tags: [routine]
schedule:
  times: ["10:00"]
  days: ["*"]
model: opus
agent: b-agent
enabled: false
---

[[Routines]]
""",
    )
    _write(
        v / "Skills" / "charlie.md",
        f"""---
title: "Charlie"
description: "A skill"
type: skill
created: {today}
updated: {today}
tags: [skill]
trigger: "when needed"
---

Body.
""",
    )
    return v


class RenderBlockTest(unittest.TestCase):
    def test_basic_filter_and_render(self):
        with tempfile.TemporaryDirectory() as td:
            v = _vault_with_routines(Path(td))
            _write(
                v / "Routines" / "Routines.md",
                """---
title: Routines
description: Index
type: index
created: 2026-04-11
updated: 2026-04-11
tags: [index]
---

# Routines

Manual intro that must be preserved.

<!-- vault-query:start filter="type=routine" sort="title" -->
(stale content)
<!-- vault-query:end -->

Trailing content also preserved.
""",
            )
            changed, scanned = vi_mod.regenerate_vault(v)
            self.assertEqual(len(scanned), 1)
            self.assertEqual(len(changed), 1)
            text = (v / "Routines" / "Routines.md").read_text()
            # Manual content preserved
            self.assertIn("Manual intro that must be preserved.", text)
            self.assertIn("Trailing content also preserved.", text)
            # Stale content gone
            self.assertNotIn("(stale content)", text)
            # Both routines listed in alpha order
            alpha_idx = text.find("alpha")
            bravo_idx = text.find("bravo")
            self.assertGreater(alpha_idx, 0)
            self.assertGreater(bravo_idx, alpha_idx)

    def test_filter_enabled_only(self):
        with tempfile.TemporaryDirectory() as td:
            v = _vault_with_routines(Path(td))
            _write(
                v / "Routines" / "Active.md",
                """---
title: Active
description: x
type: index
created: 2026-04-11
updated: 2026-04-11
tags: [index]
---

<!-- vault-query:start filter="type=routine enabled=true" -->
<!-- vault-query:end -->
""",
            )
            changed, _ = vi_mod.regenerate_vault(v)
            text = (v / "Routines" / "Active.md").read_text()
            self.assertIn("alpha", text)
            self.assertNotIn("bravo", text)  # disabled

    def test_custom_format_string(self):
        with tempfile.TemporaryDirectory() as td:
            v = _vault_with_routines(Path(td))
            _write(
                v / "Custom.md",
                """---
title: Custom
description: x
type: index
created: 2026-04-11
updated: 2026-04-11
tags: [index]
---

<!-- vault-query:start filter="type=routine" format="* {title} ({model}) — {description}" sort="title" -->
<!-- vault-query:end -->
""",
            )
            vi_mod.regenerate_vault(v)
            text = (v / "Custom.md").read_text()
            self.assertIn("* Alpha (sonnet) — First routine", text)
            self.assertIn("* Bravo (opus) — Second routine", text)

    def test_group_by(self):
        with tempfile.TemporaryDirectory() as td:
            v = _vault_with_routines(Path(td))
            _write(
                v / "Grouped.md",
                """---
title: Grouped
description: x
type: index
created: 2026-04-11
updated: 2026-04-11
tags: [index]
---

<!-- vault-query:start filter="type=routine" group_by="agent" sort="title" -->
<!-- vault-query:end -->
""",
            )
            vi_mod.regenerate_vault(v)
            text = (v / "Grouped.md").read_text()
            self.assertIn("### agent: a-agent", text)
            self.assertIn("### agent: b-agent", text)

    def test_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            v = _vault_with_routines(Path(td))
            _write(
                v / "Routines" / "Routines.md",
                """---
title: Routines
description: x
type: index
created: 2026-04-11
updated: 2026-04-11
tags: [index]
---

<!-- vault-query:start filter="type=routine" sort="title" -->
<!-- vault-query:end -->
""",
            )
            vi_mod.regenerate_vault(v)
            first = (v / "Routines" / "Routines.md").read_text()
            changed_2nd, _ = vi_mod.regenerate_vault(v)
            second = (v / "Routines" / "Routines.md").read_text()
            self.assertEqual(first, second)
            self.assertEqual(len(changed_2nd), 0)

    def test_check_mode_does_not_write(self):
        with tempfile.TemporaryDirectory() as td:
            v = _vault_with_routines(Path(td))
            _write(
                v / "Routines" / "Routines.md",
                """---
title: Routines
description: x
type: index
created: 2026-04-11
updated: 2026-04-11
tags: [index]
---

<!-- vault-query:start filter="type=routine" -->
(stale)
<!-- vault-query:end -->
""",
            )
            before = (v / "Routines" / "Routines.md").read_text()
            changed, _ = vi_mod.regenerate_vault(v, check_only=True)
            after = (v / "Routines" / "Routines.md").read_text()
            self.assertEqual(len(changed), 1)
            self.assertEqual(before, after)  # not written
            self.assertIn("(stale)", after)  # stale still there

    def test_parent_placeholder(self):
        """`{parent}` should resolve to the file's containing directory name —
        useful for files like Agents/{id}/agent.md where the link target is the
        agent id, not the stem `agent`."""
        with tempfile.TemporaryDirectory() as td:
            v = _vault_with_routines(Path(td))
            today = date.today().isoformat()
            _write(
                v / "Agents" / "alpha-bot" / "agent.md",
                f"""---
title: Alpha Bot
description: Alpha bot.
type: agent
created: {today}
updated: {today}
tags: [agent]
---
""",
            )
            _write(
                v / "Agents" / "beta-bot" / "agent.md",
                f"""---
title: Beta Bot
description: Beta bot.
type: agent
created: {today}
updated: {today}
tags: [agent]
---
""",
            )
            _write(
                v / "Agents" / "Agents.md",
                """---
title: Agents
description: x
type: index
created: 2026-04-11
updated: 2026-04-11
tags: [index]
---

<!-- vault-query:start filter="type=agent" sort="title" format="- [[{parent}]] — {description}" -->
<!-- vault-query:end -->
""",
            )
            vi_mod.regenerate_vault(v)
            text = (v / "Agents" / "Agents.md").read_text()
            self.assertIn("[[alpha-bot]] — Alpha bot.", text)
            self.assertIn("[[beta-bot]] — Beta bot.", text)
            self.assertNotIn("[[agent]]", text)

    def test_empty_results(self):
        with tempfile.TemporaryDirectory() as td:
            v = _vault_with_routines(Path(td))
            _write(
                v / "EmptyIndex.md",
                """---
title: Empty
description: x
type: index
created: 2026-04-11
updated: 2026-04-11
tags: [index]
---

<!-- vault-query:start filter="type=note" empty="(no notes yet)" -->
<!-- vault-query:end -->
""",
            )
            vi_mod.regenerate_vault(v)
            text = (v / "EmptyIndex.md").read_text()
            self.assertIn("(no notes yet)", text)


if __name__ == "__main__":
    unittest.main()
