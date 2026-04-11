"""Tests for the hot-cache per-agent rolling context (Phase 6).

Covers the deterministic helpers — no LLM calls. The end-to-end flow
(LLM produces structured snapshot → bot writes .context.md + promotes
durable concepts to Notes/) is exercised here by feeding canned LLM-shaped
responses to the parsing helpers.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests._botload import load_bot_module


class HotCacheReadWriteTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.home = self.tmp / "home"
        self.vault = self.tmp / "vault"
        self.home.mkdir()
        self.bot = load_bot_module(tmp_home=self.home, vault_dir=self.vault)

    def tearDown(self):
        self._td.cleanup()

    def test_read_returns_empty_when_missing(self):
        self.assertEqual(self.bot._read_agent_context("crypto-bro"), "")

    def test_read_returns_empty_for_no_agent_id(self):
        self.assertEqual(self.bot._read_agent_context(None), "")
        self.assertEqual(self.bot._read_agent_context(""), "")

    def test_write_then_read_round_trip(self):
        body = "## Active topics\n- topic 1\n- topic 2\n\n## Recent decisions\n- d1"
        self.bot._write_agent_context("crypto-bro", body)
        path = self.vault / "Agents" / "crypto-bro" / ".context.md"
        self.assertTrue(path.is_file())
        text = path.read_text()
        self.assertIn("type: context", text)
        self.assertIn("title: \"Context — crypto-bro\"", text)
        # Read back
        read_back = self.bot._read_agent_context("crypto-bro")
        self.assertIn("topic 1", read_back)
        self.assertIn("d1", read_back)

    def test_write_preserves_created_date(self):
        body1 = "## Active topics\n- old"
        self.bot._write_agent_context("crypto-bro", body1)
        path = self.vault / "Agents" / "crypto-bro" / ".context.md"
        first_text = path.read_text()
        # Manually patch the created date to a known older value
        first_text = first_text.replace("created: ", "created: 2020-01-01\n# original: ")
        path.write_text(first_text)
        # Re-read original to make sure our patch is parseable
        body2 = "## Active topics\n- new"
        self.bot._write_agent_context("crypto-bro", body2)
        second_text = path.read_text()
        self.assertIn("created: 2020-01-01", second_text)

    def test_truncates_oversized_body(self):
        big = "x" * (self.bot.HOT_CACHE_MAX_CHARS + 1000)
        self.bot._write_agent_context("agent-x", big)
        result = self.bot._read_agent_context("agent-x")
        # Read should also enforce the cap
        self.assertLessEqual(
            len(result), self.bot.HOT_CACHE_MAX_CHARS + len("\n…(truncated)")
        )


class DurableConceptExtractionTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.home = self.tmp / "home"
        self.vault = self.tmp / "vault"
        self.home.mkdir()
        self.bot = load_bot_module(tmp_home=self.home, vault_dir=self.vault)

    def tearDown(self):
        self._td.cleanup()

    def test_extracts_well_formed_concepts(self):
        text = """## Active topics
- focus

## Durable concepts
- crypto-cycles | high | Bitcoin halving cycles last ~4 years
- pump-and-dump | medium | Common scheme in meme coins
- noise | low | something
"""
        concepts = self.bot._extract_durable_concepts(text)
        self.assertEqual(len(concepts), 3)
        slugs = [c["slug"] for c in concepts]
        self.assertIn("crypto-cycles", slugs)
        self.assertIn("pump-and-dump", slugs)
        confidences = [c["confidence"] for c in concepts]
        self.assertEqual(confidences, ["high", "medium", "low"])

    def test_ignores_concepts_outside_section(self):
        text = """## Active topics
- crypto-cycles | high | not in durable section

## Recent decisions
- nothing | high | also not in durable section
"""
        self.assertEqual(self.bot._extract_durable_concepts(text), [])

    def test_empty_durable_section(self):
        text = """## Active topics
- a

## Durable concepts
"""
        self.assertEqual(self.bot._extract_durable_concepts(text), [])

    def test_strip_durable_concepts_section(self):
        text = """## Active topics
- a

## Durable concepts
- crypto-cycles | high | summary

## Open threads
- t1
"""
        stripped = self.bot._strip_durable_concepts_section(text)
        self.assertNotIn("Durable concepts", stripped)
        self.assertNotIn("crypto-cycles", stripped)
        self.assertIn("Active topics", stripped)
        self.assertIn("Open threads", stripped)


class NotesPromotionTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.home = self.tmp / "home"
        self.vault = self.tmp / "vault"
        self.home.mkdir()
        self.bot = load_bot_module(tmp_home=self.home, vault_dir=self.vault)

    def tearDown(self):
        self._td.cleanup()

    def test_high_confidence_creates_note(self):
        c = {"slug": "halving", "confidence": "high", "summary": "Bitcoin halving"}
        path = self.bot._promote_durable_concept_to_notes(c, "crypto-bro")
        self.assertIsNotNone(path)
        text = path.read_text()
        self.assertIn("type: note", text)
        self.assertIn("title: \"halving\"", text)
        self.assertIn("crypto-bro", text)
        self.assertIn("[[Notes]]", text)

    def test_medium_confidence_skipped(self):
        c = {"slug": "noise", "confidence": "medium", "summary": "..."}
        self.assertIsNone(self.bot._promote_durable_concept_to_notes(c, "crypto-bro"))

    def test_low_confidence_skipped(self):
        c = {"slug": "noise", "confidence": "low", "summary": "..."}
        self.assertIsNone(self.bot._promote_durable_concept_to_notes(c, "crypto-bro"))

    def test_existing_note_appends_update(self):
        c1 = {"slug": "halving", "confidence": "high", "summary": "Original definition"}
        c2 = {"slug": "halving", "confidence": "high", "summary": "Updated definition"}
        self.bot._promote_durable_concept_to_notes(c1, "crypto-bro")
        path = self.bot._promote_durable_concept_to_notes(c2, "crypto-bro")
        text = path.read_text()
        self.assertIn("Original definition", text)
        self.assertIn("## Update ", text)
        self.assertIn("Updated definition", text)

    def test_promoted_note_is_queryable(self):
        import sys
        sys.path.insert(0, str(Path(self.bot.__file__).resolve().parent / "scripts"))
        from vault_query import load_vault

        c = {"slug": "halving", "confidence": "high", "summary": "Bitcoin halving"}
        self.bot._promote_durable_concept_to_notes(c, "crypto-bro")
        vi = load_vault(self.vault)
        notes = vi.find(type="note")
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].path.stem, "halving")
        self.assertIn("auto-extracted", notes[0].tags)


class FrozenContextInjectionTest(unittest.TestCase):
    """Verify that _build_frozen_context picks up the agent .context.md."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.home = self.tmp / "home"
        self.vault = self.tmp / "vault"
        self.home.mkdir()
        self.bot = load_bot_module(tmp_home=self.home, vault_dir=self.vault)
        # Seed an agent CLAUDE.md and .context.md
        agent_dir = self.vault / "Agents" / "alpha"
        agent_dir.mkdir(parents=True)
        (agent_dir / "CLAUDE.md").write_text("# Alpha\n\nInstructions.\n")
        self.bot._write_agent_context("alpha", "## Active topics\n- the test scenario")

    def tearDown(self):
        self._td.cleanup()

    def test_frozen_context_contains_hot_cache(self):
        # Use the bot's instance via _BotFixture-style construction would be
        # heavy; instead build a Session-shaped object that the method needs.
        sess = self.bot.Session(name="test", session_id="x", model="sonnet",
                                workspace=str(self.vault), agent="alpha")
        # The bot needs a journal path getter — use a real bot-like object
        from unittest.mock import MagicMock
        bot_like = MagicMock()
        bot_like._get_journal_path = lambda: str(self.vault / "Journal" / "today.md")
        # Bind the unbound method
        ctx, _mtime = self.bot.ClaudeTelegramBot._build_frozen_context(bot_like, sess)
        self.assertIn("Continuity (alpha)", ctx)
        self.assertIn("the test scenario", ctx)
        self.assertIn("Agent Instructions (alpha)", ctx)


if __name__ == "__main__":
    unittest.main()
