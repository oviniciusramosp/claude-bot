"""Tests for scripts/youtube_rss.py — RSS XML parser.

We deliberately do NOT hit the live YouTube endpoint here; the fixture
at tests/fixtures/youtube-rss-sample.xml mirrors the real feed shape
(Atom + yt: + media: namespaces). The live-hint flag is checked on a
mix of normal/live titles.
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent
_MODULE_PATH = _REPO_ROOT / "scripts" / "youtube_rss.py"
_FIXTURE_PATH = _REPO_ROOT / "tests" / "fixtures" / "youtube-rss-sample.xml"


def _load_module():
    spec = importlib.util.spec_from_file_location("youtube_rss", _MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ParseRssXmlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = _load_module()
        cls.xml_bytes = _FIXTURE_PATH.read_bytes()

    def test_parses_all_entries(self):
        entries = self.mod.parse_rss_xml(self.xml_bytes)
        self.assertEqual(len(entries), 3)

    def test_entry_shape(self):
        entries = self.mod.parse_rss_xml(self.xml_bytes)
        e = entries[0]
        self.assertEqual(e["video_id"], "aaaaaaaaaaa")
        self.assertIn("Bastidores", e["title"])
        self.assertEqual(e["link"], "https://www.youtube.com/watch?v=aaaaaaaaaaa")
        self.assertTrue(e["thumbnail_url"].startswith("https://i.ytimg.com/vi/aaaaaaaaaaa/"))
        self.assertEqual(e["published_at"], "2026-05-26T18:30:00+00:00")
        self.assertIn("Verdão", e["description"])
        self.assertFalse(e["is_live_hint"])

    def test_live_hint_detected_case_and_accent_insensitive(self):
        entries = self.mod.parse_rss_xml(self.xml_bytes)
        # entry 2 = "AO VIVO: Coletiva ..." should be flagged
        # entry 3 = "AO VIVO: Treino aberto" also flagged
        self.assertTrue(entries[1]["is_live_hint"])
        self.assertTrue(entries[2]["is_live_hint"])

    def test_strip_accents_helper(self):
        self.assertEqual(self.mod._strip_accents("Coletiva"), "coletiva")
        self.assertEqual(self.mod._strip_accents("APRESENTAÇÃO"), "apresentacao")
        self.assertEqual(self.mod._strip_accents("anúncio"), "anuncio")


if __name__ == "__main__":
    unittest.main()
