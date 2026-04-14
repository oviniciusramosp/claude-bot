"""Tests for scripts/telegram_notify.py agent auto-detection."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Import the script as a module
_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "telegram_notify.py"
import importlib.util
_spec = importlib.util.spec_from_file_location("telegram_notify", _SCRIPT)
tn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tn)


class DetectAgentFromEnv(unittest.TestCase):
    """AGENT_ID env var detection."""

    def test_env_var_used_when_set(self):
        with patch.dict(os.environ, {"AGENT_ID": "crypto-bro"}):
            result = tn.detect_agent(explicit=None)
        self.assertEqual(result, "crypto-bro")

    def test_env_var_stripped(self):
        with patch.dict(os.environ, {"AGENT_ID": "  parmeirense  "}):
            result = tn.detect_agent(explicit=None)
        self.assertEqual(result, "parmeirense")

    def test_empty_env_var_ignored(self):
        with patch.dict(os.environ, {"AGENT_ID": ""}):
            with patch.object(tn, "_detect_agent_from_cwd", return_value=None):
                with self.assertRaises(ValueError):
                    tn.detect_agent(explicit=None)


class DetectAgentExplicit(unittest.TestCase):
    """Explicit --agent flag takes highest priority."""

    def test_explicit_overrides_env(self):
        with patch.dict(os.environ, {"AGENT_ID": "crypto-bro"}):
            result = tn.detect_agent(explicit="parmeirense")
        self.assertEqual(result, "parmeirense")

    def test_explicit_overrides_cwd(self):
        with patch.object(tn, "_detect_agent_from_cwd", return_value="main"):
            result = tn.detect_agent(explicit="digests")
        self.assertEqual(result, "digests")


class DetectAgentFromCwd(unittest.TestCase):
    """CWD-based agent detection."""

    def test_cwd_inside_agent_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            agent_dir = vault / "crypto-bro" / "workspace"
            agent_dir.mkdir(parents=True)
            # Patch VAULT_DIR and cwd
            with patch.object(tn, "VAULT_DIR", vault):
                with patch("pathlib.Path.cwd", return_value=agent_dir):
                    result = tn._detect_agent_from_cwd()
        self.assertEqual(result, "crypto-bro")

    def test_cwd_at_agent_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            agent_dir = vault / "main"
            agent_dir.mkdir(parents=True)
            with patch.object(tn, "VAULT_DIR", vault):
                with patch("pathlib.Path.cwd", return_value=agent_dir):
                    result = tn._detect_agent_from_cwd()
        self.assertEqual(result, "main")

    def test_cwd_outside_vault_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            vault.mkdir()
            outside = Path(tmp) / "other"
            outside.mkdir()
            with patch.object(tn, "VAULT_DIR", vault):
                with patch("pathlib.Path.cwd", return_value=outside):
                    result = tn._detect_agent_from_cwd()
        self.assertIsNone(result)


class DetectAgentPriorityChain(unittest.TestCase):
    """Full priority chain: explicit > env > CWD."""

    def test_no_source_raises(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AGENT_ID", None)
            with patch.object(tn, "_detect_agent_from_cwd", return_value=None):
                with self.assertRaises(ValueError) as ctx:
                    tn.detect_agent(explicit=None)
                self.assertIn("Cannot determine agent", str(ctx.exception))

    def test_env_before_cwd(self):
        with patch.dict(os.environ, {"AGENT_ID": "from-env"}):
            with patch.object(tn, "_detect_agent_from_cwd", return_value="from-cwd"):
                result = tn.detect_agent(explicit=None)
        self.assertEqual(result, "from-env")

    def test_cwd_fallback_when_no_env(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AGENT_ID", None)
            with patch.object(tn, "_detect_agent_from_cwd", return_value="from-cwd"):
                result = tn.detect_agent(explicit=None)
        self.assertEqual(result, "from-cwd")


class FindAgentFile(unittest.TestCase):
    """Agent file lookup with fallback to agent-info.md."""

    def test_primary_agent_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            (vault / "myagent").mkdir()
            primary = vault / "myagent" / "agent-myagent.md"
            primary.write_text("---\nname: Test\n---\n")
            with patch.object(tn, "VAULT_DIR", vault):
                result = tn._find_agent_file("myagent")
            self.assertEqual(result, primary)

    def test_fallback_agent_info(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            (vault / "myagent").mkdir()
            fallback = vault / "myagent" / "agent-info.md"
            fallback.write_text("---\nname: Test\n---\n")
            with patch.object(tn, "VAULT_DIR", vault):
                result = tn._find_agent_file("myagent")
            self.assertEqual(result, fallback)

    def test_no_file_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            (vault / "myagent").mkdir()
            with patch.object(tn, "VAULT_DIR", vault):
                with self.assertRaises(FileNotFoundError):
                    tn._find_agent_file("myagent")


class ResolveAgentRouting(unittest.TestCase):
    """Routing extraction from agent frontmatter."""

    def test_routing_from_frontmatter(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            (vault / "test").mkdir()
            f = vault / "test" / "agent-test.md"
            f.write_text("---\nchat_id: -100123\nthread_id: 42\n---\n")
            with patch.object(tn, "VAULT_DIR", vault):
                chat, thread = tn.resolve_agent_routing("test")
        self.assertEqual(chat, "-100123")
        self.assertEqual(thread, 42)

    def test_missing_chat_id_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            (vault / "test").mkdir()
            f = vault / "test" / "agent-test.md"
            f.write_text("---\nname: Test\n---\n")
            with patch.object(tn, "VAULT_DIR", vault):
                with self.assertRaises(ValueError):
                    tn.resolve_agent_routing("test")

    def test_thread_id_optional(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            (vault / "test").mkdir()
            f = vault / "test" / "agent-test.md"
            f.write_text("---\nchat_id: -100123\n---\n")
            with patch.object(tn, "VAULT_DIR", vault):
                chat, thread = tn.resolve_agent_routing("test")
        self.assertEqual(chat, "-100123")
        self.assertIsNone(thread)


if __name__ == "__main__":
    unittest.main()
