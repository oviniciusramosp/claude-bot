"""Agent topics inside the owner's private chat with the bot (v3.87).

Bot API 9.3/9.4 lets a bot create forum topics in a private chat once topics
are enabled for it in @BotFather (`getMe.has_topics_enabled`). `/agent topicos`
creates one topic per agent there and binds it via frontmatter
`private_chat_id` + `private_thread_id` — a second binding next to the group
topic (`chat_id` + `thread_id`), which keeps working.
"""
import tempfile
import unittest
from pathlib import Path

from tests.test_agent_routing import FORUM, _write_agent
from tests.test_bot_integration import _BotFixture

OWNER = "123456789"  # the fixture's primary private chat


class _Fixture:
    def __init__(self, topics_enabled=True, fail_for=()):
        self._td = tempfile.TemporaryDirectory()
        self.fx = _BotFixture(Path(self._td.name))
        self.bot, self.m, self.vault = self.fx.bot, self.fx.bot_module, self.fx.vault
        _write_agent(self.vault, "main", default=True)
        _write_agent(self.vault, "chef", chat_id=FORUM, thread_id=11329)
        self.bot.primary_chat_ids.add(OWNER)
        self.calls = []
        self.next_tid = 900
        topics = topics_enabled

        def fake(method, data=None, timeout=15):
            data = dict(data or {})
            self.calls.append((method, data))
            if method == "getMe":
                return {"ok": True, "result": {"username": "testbot", "has_topics_enabled": topics}}
            if method == "createForumTopic":
                if any(name in data["name"] for name in fail_for):
                    return None
                self.next_tid += 1
                return {"ok": True, "result": {"message_thread_id": self.next_tid, "name": data["name"]}}
            return {"ok": True, "result": {"message_id": len(self.calls)}}
        self.bot.tg_request = fake
        self.bot._refresh_agent_chat_map()

    def sent_texts(self):
        return [d.get("text", "") for m, d in self.calls if m == "sendMessage"]

    def cleanup(self):
        self.fx.cleanup()
        self._td.cleanup()


class FrontmatterWriter(unittest.TestCase):
    def setUp(self):
        self.f = _Fixture()
        self.addCleanup(self.f.cleanup)

    def test_appends_and_replaces_keeping_the_rest(self):
        hub = self.f.vault / "chef" / "agent-chef.md"
        before = hub.read_text(encoding="utf-8")
        self.assertTrue(self.f.m.set_agent_frontmatter_fields(
            "chef", {"private_chat_id": OWNER, "private_thread_id": 7}))
        self.assertTrue(self.f.m.set_agent_frontmatter_fields("chef", {"private_thread_id": 8}))
        after = hub.read_text(encoding="utf-8")
        for line in before.split("---")[1].strip().split("\n"):
            self.assertIn(line, after)
        agent = self.f.m.load_agent("chef")
        self.assertEqual(str(agent["private_chat_id"]), OWNER)
        self.assertEqual(int(agent["private_thread_id"]), 8)
        self.assertEqual(after.count("private_thread_id"), 1)

    def test_missing_hub_returns_false(self):
        with self.assertLogs(self.f.m.logger, level="ERROR"):
            self.assertFalse(self.f.m.set_agent_frontmatter_fields("nope", {"x": 1}))


class PrivateTopicRouting(unittest.TestCase):
    def setUp(self):
        self.f = _Fixture()
        self.addCleanup(self.f.cleanup)

    def test_private_topic_and_group_topic_both_route_to_agent(self):
        self.f.m.set_agent_frontmatter_fields("chef", {"private_chat_id": OWNER, "private_thread_id": 42})
        self.f.bot._refresh_agent_chat_map()
        self.assertEqual(self.f.bot._resolved_agent_for_chat(OWNER, 42)["_id"], "chef")
        self.assertEqual(self.f.bot._resolved_agent_for_chat(FORUM, 11329)["_id"], "chef")

    def test_private_chat_outside_topics_goes_to_default_agent(self):
        self.f.m.set_agent_frontmatter_fields("chef", {"private_chat_id": OWNER, "private_thread_id": 42})
        self.f.bot._refresh_agent_chat_map()
        self.assertEqual(self.f.bot._resolved_agent_for_chat(OWNER, None)["_id"], "main")

    def test_invalid_private_thread_is_ignored_loudly(self):
        self.f.m.set_agent_frontmatter_fields("chef", {"private_chat_id": OWNER, "private_thread_id": "x"})
        with self.assertLogs(self.f.m.logger, level="ERROR"):
            self.f.bot._refresh_agent_chat_map()
        self.assertIsNone(self.f.bot._find_agent_for_chat(OWNER, 42))


class AgentTopicsCommand(unittest.TestCase):
    def test_topics_disabled_explains_how_to_enable(self):
        f = _Fixture(topics_enabled=False)
        self.addCleanup(f.cleanup)
        f.bot.cmd_agent("topicos")
        self.assertFalse(any(m == "createForumTopic" for m, _ in f.calls))
        self.assertIn("BotFather", f.sent_texts()[-1])

    def test_creates_one_topic_per_agent_and_binds_it(self):
        f = _Fixture()
        self.addCleanup(f.cleanup)
        f.bot.cmd_agent("topicos")
        created = [d for m, d in f.calls if m == "createForumTopic"]
        self.assertEqual(len(created), 2)
        self.assertTrue(all(d["chat_id"] == OWNER for d in created))
        self.assertIn("main", created[0]["name"])  # default agent first
        chef = f.m.load_agent("chef")
        self.assertEqual(str(chef["private_chat_id"]), OWNER)
        tid = int(chef["private_thread_id"])
        self.assertEqual(f.bot._resolved_agent_for_chat(OWNER, tid)["_id"], "chef")
        # group binding untouched
        self.assertEqual(int(chef["thread_id"]), 11329)
        # a hello inside each new topic, and a summary with links
        hellos = [d for m, d in f.calls if m == "sendMessage" and d.get("message_thread_id")]
        self.assertEqual(len(hellos), 2)
        self.assertIn(f"https://t.me/testbot/{tid}", f.sent_texts()[-1])

    def test_second_run_skips_existing_topics(self):
        f = _Fixture()
        self.addCleanup(f.cleanup)
        f.bot.cmd_agent("topicos")
        f.calls.clear()
        f.bot.cmd_agent("topicos")
        self.assertFalse(any(m == "createForumTopic" for m, _ in f.calls))
        self.assertIn("Já existiam", f.sent_texts()[-1])

    def test_failure_is_reported_and_others_continue(self):
        f = _Fixture(fail_for=("chef",))
        self.addCleanup(f.cleanup)
        with self.assertLogs(f.m.logger, level="ERROR"):
            f.bot.cmd_agent("topicos")
        self.assertIsNone(f.m.load_agent("chef").get("private_thread_id"))
        self.assertIsNotNone(f.m.load_agent("main").get("private_thread_id"))
        self.assertIn("Não deu certo", f.sent_texts()[-1])


if __name__ == "__main__":
    unittest.main()
