"""Tests for scripts/published_index.py — JSONL-backed publish index."""
from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import os
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "published_index.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "published_index_under_test", str(SCRIPT_PATH)
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["published_index_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


pi = _load_module()


class _BaseCase(unittest.TestCase):
    """Common scaffolding: every test gets a throwaway vault root."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.vault_root = Path(self._tmp.name)
        self.agent = "testagent"

    def _idx(self) -> "pi.PublishedIndex":
        return pi.PublishedIndex(agent_id=self.agent, vault_root=self.vault_root)


class AddAndGet(_BaseCase):
    def test_add_returns_post_id(self) -> None:
        idx = self._idx()
        pid = idx.add(
            pipeline="palmeiras-feed-v2",
            topic_key="news:abc",
            title="Hello",
            source_urls=["https://example.com/x"],
        )
        self.assertTrue(pid)
        self.assertEqual(len(pid), 32, "uuid4 hex is 32 chars")

    def test_add_custom_post_id(self) -> None:
        idx = self._idx()
        pid = idx.add(pipeline="p", post_id="custom-id-1")
        self.assertEqual(pid, "custom-id-1")
        row = idx.get(post_id="custom-id-1")
        self.assertIsNotNone(row)
        self.assertEqual(row["pipeline"], "p")
        self.assertEqual(row["agent_id"], "testagent")

    def test_get_unknown_returns_none(self) -> None:
        self.assertIsNone(self._idx().get(post_id="nope"))

    def test_missing_file_treated_as_empty(self) -> None:
        idx = self._idx()
        self.assertFalse(idx.has(topic_key="anything"))
        self.assertEqual(list(idx.query()), [])
        self.assertIsNone(idx.get(post_id="x"))


class HasFiltering(_BaseCase):
    def test_has_true_and_false(self) -> None:
        idx = self._idx()
        idx.add(pipeline="p", topic_key="news:a")
        self.assertTrue(idx.has(topic_key="news:a"))
        self.assertFalse(idx.has(topic_key="news:b"))

    def test_within_days_respected(self) -> None:
        idx = self._idx()
        brt = _dt.timezone(_dt.timedelta(hours=-3))
        old = (_dt.datetime.now(brt) - _dt.timedelta(days=45)).isoformat(timespec="seconds")
        recent = (_dt.datetime.now(brt) - _dt.timedelta(days=5)).isoformat(timespec="seconds")
        idx.add(pipeline="p", topic_key="news:old", published_at=old)
        idx.add(pipeline="p", topic_key="news:recent", published_at=recent)

        self.assertTrue(idx.has(topic_key="news:old"))  # unbounded
        self.assertFalse(idx.has(topic_key="news:old", within_days=30))
        self.assertTrue(idx.has(topic_key="news:recent", within_days=30))


class QueryFiltering(_BaseCase):
    def test_query_by_pipeline_and_since(self) -> None:
        idx = self._idx()
        brt = _dt.timezone(_dt.timedelta(hours=-3))
        old = (_dt.datetime.now(brt) - _dt.timedelta(days=10)).isoformat(timespec="seconds")
        new = (_dt.datetime.now(brt) - _dt.timedelta(days=1)).isoformat(timespec="seconds")
        idx.add(pipeline="feed", topic_key="news:1", published_at=old)
        idx.add(pipeline="feed", topic_key="news:2", published_at=new)
        idx.add(pipeline="other", topic_key="news:3", published_at=new)

        all_feed = list(idx.query(pipeline="feed"))
        self.assertEqual({r["topic_key"] for r in all_feed}, {"news:1", "news:2"})

        since = (_dt.datetime.now(brt) - _dt.timedelta(days=5)).isoformat(timespec="seconds")
        recent_feed = list(idx.query(pipeline="feed", since=since))
        self.assertEqual([r["topic_key"] for r in recent_feed], ["news:2"])

        by_topic = list(idx.query(topic_key="news:3"))
        self.assertEqual(len(by_topic), 1)
        self.assertEqual(by_topic[0]["pipeline"], "other")


class TelegramUpdate(_BaseCase):
    def test_update_telegram_message_id_rewrites_line(self) -> None:
        idx = self._idx()
        pid1 = idx.add(pipeline="p", title="one",
                       telegram={"chat_id": -100, "thread_id": 1})
        pid2 = idx.add(pipeline="p", title="two",
                       telegram={"chat_id": -100, "thread_id": 1})

        ok = idx.update_telegram_message_id(pid1, 9999)
        self.assertTrue(ok)

        row1 = idx.get(post_id=pid1)
        row2 = idx.get(post_id=pid2)
        self.assertEqual(row1["telegram"]["message_id"], 9999)
        self.assertEqual(row1["telegram"]["chat_id"], -100)
        self.assertNotIn("message_id", row2["telegram"])

        # File still has exactly two lines, both valid JSON.
        lines = idx.path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        for ln in lines:
            json.loads(ln)  # raises on corruption

    def test_update_unknown_post_returns_false(self) -> None:
        idx = self._idx()
        idx.add(pipeline="p")
        self.assertFalse(idx.update_telegram_message_id("ghost", 1))


class Concurrency(_BaseCase):
    def test_concurrent_threaded_writes_dont_corrupt(self) -> None:
        idx = self._idx()
        N_THREADS = 8
        PER_THREAD = 25
        errors: list = []

        def worker(tid: int) -> None:
            try:
                local = self._idx()  # fresh handle, same path
                for i in range(PER_THREAD):
                    local.add(
                        pipeline="concurrent",
                        topic_key=f"t{tid}:{i}",
                        title=f"thread {tid} item {i}",
                    )
            except Exception as exc:  # pragma: no cover - surfaces failures
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])

        # Every line must be valid JSON; total count must match.
        rows = list(idx.query())
        self.assertEqual(len(rows), N_THREADS * PER_THREAD)
        self.assertEqual(len({r["post_id"] for r in rows}), N_THREADS * PER_THREAD)
        # Every line in the file must parse independently.
        raw_lines = [ln for ln in idx.path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        self.assertEqual(len(raw_lines), N_THREADS * PER_THREAD)
        for ln in raw_lines:
            json.loads(ln)

    def test_concurrent_subprocess_writes_dont_corrupt(self) -> None:
        """Two processes hammering ``add`` via the CLI must not interleave bytes."""
        env = os.environ.copy()
        env["CLAUDE_BOT_VAULT_ROOT"] = str(self.vault_root)

        def spawn(prefix: str, n: int) -> subprocess.Popen:
            # Each subprocess writes n entries with distinct topic_keys.
            script = (
                "import os, sys;"
                "sys.path.insert(0, %r);"
                "from published_index import PublishedIndex;"
                "idx = PublishedIndex(agent_id='testagent');"
                "[idx.add(pipeline='p', topic_key=f'%s:{i}', title='x') for i in range(%d)]"
                % (str(SCRIPT_PATH.parent), prefix, n)
            )
            return subprocess.Popen(
                [sys.executable, "-c", script],
                env=env,
            )

        N = 50
        p1 = spawn("a", N)
        p2 = spawn("b", N)
        self.assertEqual(p1.wait(timeout=30), 0)
        self.assertEqual(p2.wait(timeout=30), 0)

        idx = self._idx()
        rows = list(idx.query())
        self.assertEqual(len(rows), 2 * N)
        keys = {r["topic_key"] for r in rows}
        self.assertEqual(len(keys), 2 * N)


class CliSmoke(_BaseCase):
    def _run(self, *args: str) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["CLAUDE_BOT_VAULT_ROOT"] = str(self.vault_root)
        return subprocess.run(
            [sys.executable, str(SCRIPT_PATH), *args],
            env=env,
            capture_output=True,
            text=True,
        )

    def test_cli_add_has_query_get_update(self) -> None:
        r = self._run(
            "add",
            "--agent", self.agent,
            "--pipeline", "feed",
            "--topic-key", "news:cli",
            "--title", "CLI Title",
            "--source-url", "https://e.com/1",
            "--source-url", "https://e.com/2",
            "--telegram-chat-id", "-100",
            "--telegram-thread-id", "17",
            "--features", '{"tone": "exaltado"}',
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        pid = r.stdout.strip()
        self.assertEqual(len(pid), 32)

        # has — exit 0
        r = self._run("has", "--agent", self.agent, "--topic-key", "news:cli")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stderr, "")

        # has — exit 1
        r = self._run("has", "--agent", self.agent, "--topic-key", "missing")
        self.assertEqual(r.returncode, 1)

        # query
        r = self._run("query", "--agent", self.agent, "--pipeline", "feed")
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = [json.loads(ln) for ln in r.stdout.strip().splitlines() if ln]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "CLI Title")
        self.assertEqual(rows[0]["features"], {"tone": "exaltado"})

        # update message id
        r = self._run(
            "update-telegram-message-id",
            "--agent", self.agent,
            "--post-id", pid,
            "--message-id", "424242",
        )
        self.assertEqual(r.returncode, 0, r.stderr)

        # get
        r = self._run("get", "--agent", self.agent, "--post-id", pid)
        self.assertEqual(r.returncode, 0, r.stderr)
        row = json.loads(r.stdout.strip())
        self.assertEqual(row["telegram"]["message_id"], 424242)
        self.assertEqual(row["telegram"]["chat_id"], -100)


if __name__ == "__main__":
    unittest.main()
