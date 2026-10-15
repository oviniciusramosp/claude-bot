"""Agent ↔ chat routing: topic bindings and who owns the General topic.

Regression context: an agent can only claim a *named* forum topic (frontmatter
``chat_id`` + ``thread_id``), so the General topic had no owner and simply kept
whichever agent its session was last switched to. Creating an agent from
General (``/agent new`` switches the creating context) was enough to leave a
specialist agent answering there for months. These tests pin the contract.
"""
import tempfile
import unittest
from pathlib import Path

from tests._botload import ensure_agent_layout
from tests.test_bot_integration import _BotFixture

FORUM = "-1009999"


def _write_agent(vault: Path, agent_id: str, *, default: bool = False,
                 chat_id: str = None, thread_id: int = None) -> Path:
    """Create an agent hub with the given routing frontmatter."""
    base = ensure_agent_layout(vault, agent_id)
    lines = [
        "---",
        f"title: {agent_id}",
        f"description: Test agent {agent_id}",
        "type: agent",
        f"name: {agent_id}",
        "model: sonnet",
        'icon: "🤖"',
    ]
    if default:
        lines.append("default: true")
    if chat_id:
        lines.append(f'chat_id: "{chat_id}"')
    if thread_id is not None:
        lines.append(f"thread_id: {thread_id}")
    lines += ["---", ""]
    (base / f"agent-{agent_id}.md").write_text("\n".join(lines), encoding="utf-8")
    return base


class _RoutingFixture:
    """Bot with a forum-shaped vault: default agent + one topic-bound agent."""

    def __init__(self, tmp_root: Path, *, mark_default: bool = True):
        self.fixture = _BotFixture(tmp_root)
        self.bot = self.fixture.bot
        self.module = self.fixture.bot_module
        self.vault = self.fixture.vault
        _write_agent(self.vault, "main", default=mark_default)
        _write_agent(self.vault, "chef", chat_id=FORUM, thread_id=11329)
        self.bot._refresh_agent_chat_map()

    def cleanup(self):
        self.fixture.cleanup()


class DefaultAgentResolution(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.f = _RoutingFixture(Path(self._td.name))

    def tearDown(self):
        self.f.cleanup()
        self._td.cleanup()

    def test_prefers_agent_marked_default(self):
        _write_agent(self.f.vault, "boss", default=True)
        # main is no longer the marked default
        _write_agent(self.f.vault, "main", default=False)
        self.assertEqual(self.f.module.default_agent()["_id"], "boss")

    def test_falls_back_to_main_when_none_marked(self):
        _write_agent(self.f.vault, "main", default=False)
        self.assertEqual(self.f.module.default_agent()["_id"], "main")


class GeneralTopicRouting(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.f = _RoutingFixture(Path(self._td.name))
        self.bot = self.f.bot

    def tearDown(self):
        self.f.cleanup()
        self._td.cleanup()

    def test_mapped_topic_resolves_to_its_agent(self):
        agent = self.bot._resolved_agent_for_chat(FORUM, 11329)
        self.assertEqual(agent["_id"], "chef")

    def test_general_topic_resolves_to_default_agent(self):
        agent = self.bot._resolved_agent_for_chat(FORUM, None)
        self.assertEqual(agent["_id"], "main")

    def test_unmapped_named_topic_stays_unresolved(self):
        # None keeps the "new topic → pick an agent" onboarding keyboard path.
        self.assertIsNone(self.bot._resolved_agent_for_chat(FORUM, 777))

    def test_plain_group_without_topic_agents_is_not_forced(self):
        # No agent claims a topic in this chat, so a manual /agent choice there
        # must keep standing.
        self.assertIsNone(self.bot._resolved_agent_for_chat("-100555", None))

    def test_secondary_chat_general_uses_its_own_default(self):
        self.bot.secondary_chats["-100777"] = {"default": "chef", "topics": {}}
        agent = self.bot._resolved_agent_for_chat("-100777", None)
        self.assertEqual(agent["_id"], "chef")

    def test_secondary_chat_never_falls_back_to_vault_default(self):
        # A secondary chat pointing at a missing agent must NOT inherit the
        # vault's default agent — that would expose Main's vault to a guest.
        self.bot.secondary_chats["-100888"] = {"default": "ghost", "topics": {}}
        self.assertIsNone(self.bot._resolved_agent_for_chat("-100888", None))


class StaleGeneralSessionHealing(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.f = _RoutingFixture(Path(self._td.name))
        self.bot = self.f.bot
        self.bot._ctx = self.bot._get_context(FORUM, None)

    def tearDown(self):
        self.f.cleanup()
        self._td.cleanup()

    def test_general_session_stuck_on_specialist_is_reclaimed(self):
        session = self.bot._get_session()
        session.agent = "chef"
        session.session_id = "stale-transcript"
        session.workspace = str(self.f.module.workspace_dir("chef"))

        agent = self.bot._resolved_agent_for_chat(FORUM, None)
        self.bot._auto_activate_agent(agent)

        session = self.bot._get_session()
        self.assertEqual(session.agent, "main")
        self.assertTrue(session.workspace.rstrip("/").endswith("main/.workspace")
                        or session.workspace.rstrip("/").endswith("main"))
        # Transcript was recorded under the old agent's cwd — must not be resumed.
        self.assertIsNone(session.session_id)

    def test_transcript_survives_when_agent_is_unchanged(self):
        session = self.bot._get_session()
        session.agent = "main"
        session.session_id = "keep-me"

        self.bot._auto_activate_agent(self.f.module.default_agent())

        self.assertEqual(self.bot._get_session().session_id, "keep-me")


if __name__ == "__main__":
    unittest.main()
