"""Tests for the reply-capture helpers _load_published_post and _record_post_reply.

These exercise the module-level helpers added to claude-fallback-bot.py for the
reply-capture feedback loop (vault/<agent>/.workspace/published-index.jsonl ->
post-replies.jsonl).
"""
import json
import tempfile
import unittest
from pathlib import Path

from tests._botload import ensure_agent_layout, load_bot_module


class PostReplyHandlerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp_home = Path(tempfile.mkdtemp(prefix="post-reply-test-"))
        cls.vault = cls.tmp_home / "vault"
        cls.vault.mkdir(parents=True, exist_ok=True)
        ensure_agent_layout(cls.vault, "parmeirense")
        ensure_agent_layout(cls.vault, "main")
        cls.bot = load_bot_module(tmp_home=cls.tmp_home, vault_dir=cls.vault)

        # Drop a published-index.jsonl under parmeirense with one entry, plus
        # a malformed line to exercise the tolerance path.
        idx = cls.vault / "parmeirense" / ".workspace" / "published-index.jsonl"
        idx.write_text(
            "{ this is not json\n"
            + json.dumps({
                "post_id": "abc123",
                "agent_id": "parmeirense",
                "pipeline": "palmeiras-feed-v2",
                "telegram": {"chat_id": -1001234567890, "thread_id": 17, "message_id": 12345},
            }) + "\n"
            + json.dumps({
                "post_id": "def456",
                "pipeline": "palmeiras-feed-v2",
                "telegram": {"chat_id": -1001234567890, "message_id": 99},
            }) + "\n",
            encoding="utf-8",
        )

    def test_load_published_post_match(self):
        entry = self.bot._load_published_post(-1001234567890, 12345)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["post_id"], "abc123")
        self.assertEqual(entry["agent_id"], "parmeirense")

    def test_load_published_post_fills_agent_id_from_folder(self):
        # The second entry has no explicit agent_id; folder name should fill it.
        entry = self.bot._load_published_post(-1001234567890, 99)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["post_id"], "def456")
        self.assertEqual(entry["agent_id"], "parmeirense")

    def test_load_published_post_no_match(self):
        self.assertIsNone(self.bot._load_published_post(-1001234567890, 7777))
        self.assertIsNone(self.bot._load_published_post(0, 12345))

    def test_record_post_reply_appends_jsonl(self):
        post_entry = {"post_id": "abc123", "agent_id": "parmeirense"}
        msg = {
            "message_id": 99999,
            "text": "Segue meu Pal! Bora!",
            "from": {"id": 42, "username": "vinizeira", "first_name": "Vinicius"},
            "chat": {"id": -1001234567890, "type": "supergroup"},
            "reply_to_message": {"message_id": 12345},
        }
        self.bot._record_post_reply(post_entry, msg)

        out = self.vault / "parmeirense" / ".workspace" / "post-replies.jsonl"
        self.assertTrue(out.is_file())
        lines = [ln for ln in out.read_text(encoding="utf-8").splitlines() if ln.strip()]
        self.assertEqual(len(lines), 1)
        rec = json.loads(lines[0])
        self.assertEqual(rec["post_id"], "abc123")
        self.assertEqual(rec["agent_id"], "parmeirense")
        self.assertEqual(rec["reply_text"], "Segue meu Pal! Bora!")
        self.assertEqual(rec["user"]["username"], "vinizeira")
        self.assertEqual(rec["user"]["id"], 42)
        self.assertEqual(rec["telegram"]["chat_id"], -1001234567890)
        self.assertEqual(rec["telegram"]["message_id"], 99999)
        self.assertEqual(rec["telegram"]["reply_to_message_id"], 12345)
        self.assertIn("received_at", rec)
        # ISO 8601 with timezone offset — basic sanity check
        self.assertRegex(rec["received_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

        # Second call should append, not overwrite.
        self.bot._record_post_reply(post_entry, msg)
        lines2 = [ln for ln in out.read_text(encoding="utf-8").splitlines() if ln.strip()]
        self.assertEqual(len(lines2), 2)

    def test_record_post_reply_missing_agent_id_is_noop(self):
        # No agent_id -> log warning, do not create file.
        out_dir = self.vault / "ghost" / ".workspace"
        post_entry = {"post_id": "xyz"}
        msg = {"message_id": 1, "text": "x", "from": {}, "chat": {"id": 0}, "reply_to_message": {}}
        self.bot._record_post_reply(post_entry, msg)
        self.assertFalse((out_dir / "post-replies.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
