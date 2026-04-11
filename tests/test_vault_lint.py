"""Tests for scripts/vault_lint.py.

Each lint category gets a synthetic vault fixture and verifies the issue
is detected (and that a clean fixture is reported clean).
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import vault_lint as vl  # noqa: E402


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_clean_vault(tmp: Path) -> Path:
    """Build a minimally valid vault that passes every lint pass."""
    v = tmp / "vault"
    today = date.today().isoformat()
    _write(
        v / "Routines" / "Routines.md",
        f"""---
title: "Routines"
description: "Index."
type: index
created: {today}
updated: {today}
tags: [index, routines]
---

# Routines

- [[clean-routine]] — clean
""",
    )
    _write(
        v / "Routines" / "clean-routine.md",
        f"""---
title: "Clean Routine"
description: "A clean routine."
type: routine
created: {today}
updated: {today}
tags: [routine]
schedule:
  times: ["09:00"]
  days: ["*"]
model: sonnet
enabled: true
---

[[Routines]]

Body.
""",
    )
    return v


class CleanVaultTest(unittest.TestCase):
    def test_clean_vault_no_issues(self):
        with tempfile.TemporaryDirectory() as td:
            v = _make_clean_vault(Path(td))
            report = vl.lint_vault(v)
            self.assertTrue(
                report.is_clean,
                f"Expected clean, got: {[i.message for i in report.issues]}",
            )


class MissingFrontmatterTest(unittest.TestCase):
    def test_detects_missing_required_keys(self):
        with tempfile.TemporaryDirectory() as td:
            v = _make_clean_vault(Path(td))
            _write(
                v / "Skills" / "broken.md",
                """---
title: "Broken"
type: skill
---

body
""",
            )
            report = vl.lint_vault(v, categories=[1])
            self.assertEqual(len(report.issues), 1)
            self.assertEqual(report.issues[0].category, 1)
            self.assertIn("description", report.issues[0].message)
            self.assertIn("created", report.issues[0].message)


class BrokenWikilinksTest(unittest.TestCase):
    def test_detects_broken_wikilinks(self):
        with tempfile.TemporaryDirectory() as td:
            v = _make_clean_vault(Path(td))
            today = date.today().isoformat()
            _write(
                v / "Notes" / "with-broken-link.md",
                f"""---
title: "Bad Link"
description: "x"
type: note
created: {today}
updated: {today}
tags: [note]
---

This points to [[nonexistent-target]].
""",
            )
            report = vl.lint_vault(v, categories=[2])
            self.assertEqual(len(report.issues), 1)
            self.assertIn("nonexistent-target", report.issues[0].message)


class BrokenPromptFileTest(unittest.TestCase):
    def test_detects_missing_prompt_file(self):
        with tempfile.TemporaryDirectory() as td:
            v = _make_clean_vault(Path(td))
            today = date.today().isoformat()
            _write(
                v / "Routines" / "missing-prompt.md",
                f"""---
title: "Missing Prompt"
description: "x"
type: pipeline
created: {today}
updated: {today}
tags: [pipeline]
schedule:
  times: ["09:00"]
  days: ["*"]
model: sonnet
enabled: true
---

[[Routines]]

```pipeline
steps:
  - id: step1
    name: "Step 1"
    model: sonnet
    prompt_file: steps/nonexistent.md
```
""",
            )
            report = vl.lint_vault(v, categories=[4])
            self.assertEqual(len(report.issues), 1)
            self.assertEqual(report.issues[0].category, 4)
            self.assertIn("nonexistent.md", report.issues[0].message)


class StepFileLeakageTest(unittest.TestCase):
    def test_step_file_with_frontmatter_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            v = _make_clean_vault(Path(td))
            _write(
                v / "Routines" / "leaky" / "steps" / "scout.md",
                """---
title: "Scout"
type: step
---

Scout body.
""",
            )
            report = vl.lint_vault(v, categories=[6])
            self.assertEqual(len(report.issues), 1)
            self.assertIn("frontmatter", report.issues[0].message)

    def test_step_file_with_wikilink_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            v = _make_clean_vault(Path(td))
            _write(
                v / "Routines" / "leaky" / "steps" / "scout.md",
                "Scout body with a [[wikilink]].\n",
            )
            report = vl.lint_vault(v, categories=[6])
            self.assertEqual(len(report.issues), 1)
            self.assertIn("wikilinks", report.issues[0].message)

    def test_clean_step_file_passes(self):
        with tempfile.TemporaryDirectory() as td:
            v = _make_clean_vault(Path(td))
            _write(
                v / "Routines" / "clean" / "steps" / "scout.md",
                "Scout body.\nNo frontmatter, no wikilinks.\n",
            )
            report = vl.lint_vault(v, categories=[6])
            self.assertEqual(len(report.issues), 0)


class IndexDriftTest(unittest.TestCase):
    def test_index_pointing_to_missing_child(self):
        with tempfile.TemporaryDirectory() as td:
            v = _make_clean_vault(Path(td))
            today = date.today().isoformat()
            _write(
                v / "Routines" / "Routines.md",
                f"""---
title: "Routines"
description: "Index."
type: index
created: {today}
updated: {today}
tags: [index]
---

# Routines

- [[clean-routine]] — clean
- [[ghost-routine]] — does not exist
""",
            )
            report = vl.lint_vault(v, categories=[7])
            self.assertEqual(len(report.issues), 1)
            self.assertIn("ghost-routine", report.issues[0].message)


class ScheduleSanityTest(unittest.TestCase):
    def test_both_times_and_interval(self):
        with tempfile.TemporaryDirectory() as td:
            v = _make_clean_vault(Path(td))
            today = date.today().isoformat()
            _write(
                v / "Routines" / "double.md",
                f"""---
title: "Double"
description: "x"
type: routine
created: {today}
updated: {today}
tags: [routine]
schedule:
  times: ["09:00"]
  interval: "1h"
  days: ["*"]
model: sonnet
enabled: true
---

[[Routines]]
""",
            )
            report = vl.lint_vault(v, categories=[8])
            issues = [i for i in report.issues if "double.md" in i.file]
            self.assertTrue(any("mutually exclusive" in i.message for i in issues))

    def test_until_in_past(self):
        with tempfile.TemporaryDirectory() as td:
            v = _make_clean_vault(Path(td))
            today = date.today().isoformat()
            past = (date.today() - timedelta(days=30)).isoformat()
            _write(
                v / "Routines" / "expired.md",
                f"""---
title: "Expired"
description: "x"
type: routine
created: {today}
updated: {today}
tags: [routine]
schedule:
  times: ["09:00"]
  days: ["*"]
  until: {past}
model: sonnet
enabled: true
---

[[Routines]]
""",
            )
            report = vl.lint_vault(v, categories=[8])
            issues = [i for i in report.issues if "expired.md" in i.file]
            self.assertTrue(any("in the past" in i.message for i in issues))


class StaleRoutineTest(unittest.TestCase):
    def test_stale_routine_detected(self):
        with tempfile.TemporaryDirectory() as td:
            v = _make_clean_vault(Path(td))
            today = date.today().isoformat()
            stale_date = (date.today() - timedelta(days=30)).isoformat()
            # History rollup recording an old run
            _write(
                v / "Routines" / ".history" / "2026-03.md",
                f"""---
title: "History 2026-03"
description: "Execution history"
type: history
created: {today}
updated: {today}
tags: [history]
---

## {stale_date} 09:00 — clean-routine
- status: completed
""",
            )
            report = vl.lint_vault(v, categories=[5], stale_days=14)
            issues = [i for i in report.issues if "clean-routine" in i.file]
            self.assertEqual(len(issues), 1)
            self.assertIn("days", issues[0].message)


class OrphanTest(unittest.TestCase):
    def test_orphan_note_detected(self):
        with tempfile.TemporaryDirectory() as td:
            v = _make_clean_vault(Path(td))
            today = date.today().isoformat()
            _write(
                v / "Notes" / "lonely.md",
                f"""---
title: "Lonely"
description: "Nobody links to me."
type: note
created: {today}
updated: {today}
tags: [note]
---

Body without anyone linking here.
""",
            )
            report = vl.lint_vault(v, categories=[3])
            issues = [i for i in report.issues if "lonely.md" in i.file]
            self.assertEqual(len(issues), 1)


if __name__ == "__main__":
    unittest.main()
