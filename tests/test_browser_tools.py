"""v3.84 — browser tools for agents (Playwright MCP over CDP) and the
PinchTab health check.

No browser is started: the CDP probe, npx lookup and launchctl are patched.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests._botload import load_bot_module


def _mock_proc():
    proc = MagicMock()
    proc.stdout = iter([])
    proc.stderr = MagicMock()
    proc.stderr.read.return_value = ""
    proc.stdin = MagicMock()
    proc.wait.return_value = 0
    proc.returncode = 0
    proc.pid = 4321
    return proc


class BrowserMcpConfig(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.m = load_bot_module(tmp_home=Path(self._td.name))
        self.m.BROWSER_MCP_CONFIG = Path(self._td.name) / "browser-mcp.json"
        self.m.BROWSER_MCP_ENABLED = True
        self._p = [patch.object(self.m, "_npx_path", lambda: "/usr/local/bin/npx")]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()
        self._td.cleanup()

    def test_config_points_playwright_at_cdp(self):
        with patch.object(self.m, "browser_cdp_alive", return_value=True):
            path = self.m.browser_mcp_config_path()
        server = json.loads(path.read_text())["mcpServers"]["browser"]
        self.assertEqual(server["command"], "/usr/local/bin/npx")
        self.assertIn(self.m.BROWSER_MCP_PACKAGE, server["args"])
        self.assertNotIn("latest", self.m.BROWSER_MCP_PACKAGE)
        self.assertEqual(server["args"][-2:], ["--cdp-endpoint", self.m.BROWSER_CDP_URL])
        self.assertTrue(server["env"]["PATH"].startswith("/usr/local/bin"))

    def test_no_config_when_chrome_down_npx_missing_or_disabled(self):
        with patch.object(self.m, "browser_cdp_alive", return_value=False):
            self.assertIsNone(self.m.browser_mcp_config_path())
        with patch.object(self.m, "browser_cdp_alive", return_value=True), \
                patch.object(self.m, "_npx_path", lambda: None):
            self.assertIsNone(self.m.browser_mcp_config_path())
        self.m.BROWSER_MCP_ENABLED = False
        with patch.object(self.m, "browser_cdp_alive", return_value=True):
            self.assertIsNone(self.m.browser_mcp_config_path())

    def test_cdp_probe_is_cached(self):
        calls = []
        with patch.object(self.m, "_http_alive", side_effect=lambda *a, **k: calls.append(a) or True):
            self.m._browser_cdp_state.update(ts=0.0, ok=False)
            self.assertTrue(self.m.browser_cdp_alive())
            self.assertTrue(self.m.browser_cdp_alive())
            self.assertEqual(len(calls), 1)
            self.m.browser_cdp_alive(force=True)
            self.assertEqual(len(calls), 2)

    def _cmd(self, model="sonnet", restricted=False):
        with tempfile.TemporaryDirectory() as ws, \
                patch.object(self.m, "browser_cdp_alive", return_value=True), \
                patch.object(self.m, "_ensure_agent_settings", return_value=Path(ws) / "s.json"), \
                patch.object(self.m.subprocess, "Popen", return_value=_mock_proc()) as popen:
            self.m.ClaudeRunner().run(prompt="hi", model=model, workspace=ws, system_prompt=None,
                                      agent_id="main", restricted=restricted)
        return popen.call_args.args[0]

    def test_cli_gets_mcp_config_in_owner_runs(self):
        cmd = self._cmd()
        self.assertIn("--mcp-config", cmd)
        self.assertEqual(cmd[cmd.index("--mcp-config") + 1], str(self.m.BROWSER_MCP_CONFIG))

    def test_guest_runs_never_get_the_browser(self):
        cmd = self._cmd(restricted=True)
        self.assertIn("dontAsk", cmd)
        self.assertNotIn("--mcp-config", cmd)


class BrowserHealthCheck(unittest.TestCase):
    def setUp(self):
        self.m = load_bot_module()
        self.m.BROWSER_MCP_ENABLED = True
        bot = self.m.ClaudeTelegramBot.__new__(self.m.ClaudeTelegramBot)
        bot.primary_chat_ids = {"111"}
        self.sent = []
        bot.send_message = lambda text, **kw: self.sent.append((kw.get("chat_id"), text)) or 1
        self.bot = bot
        self.healthy = True
        self._p = [
            patch.object(self.m, "pinchtab_installed", return_value=True),
            patch.object(self.m, "_http_alive", side_effect=lambda *a, **k: self.healthy),
            patch.object(self.m, "browser_cdp_alive", side_effect=lambda force=False: self.healthy),
            patch.object(self.m, "pinchtab_launchd_exit_codes",
                         return_value={"com.pinchtab.server": "78", "com.chromecdp.pinchtab": "78"}),
        ]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()

    def test_alerts_once_after_two_failures_then_recovers(self):
        self.healthy = False
        self.bot._check_browser_health()
        self.assertEqual(self.sent, [])  # one failure may be a restart in progress
        self.bot._check_browser_health()
        self.bot._check_browser_health()
        self.assertEqual(len(self.sent), 1)
        chat, text = self.sent[0]
        self.assertEqual(chat, "111")
        self.assertIn("exit 78", text)
        self.assertIn("Permitir em Segundo Plano", text)
        self.healthy = True
        self.bot._check_browser_health()
        self.assertEqual(len(self.sent), 2)
        self.assertIn("voltou", self.sent[1][1])
        self.bot._check_browser_health()
        self.assertEqual(len(self.sent), 2)

    def test_silent_when_pinchtab_not_installed(self):
        self.healthy = False
        with patch.object(self.m, "pinchtab_installed", return_value=False):
            for _ in range(3):
                self.bot._check_browser_health()
        self.assertEqual(self.sent, [])


class LaunchdExitCodes(unittest.TestCase):
    def test_parses_only_pinchtab_labels(self):
        m = load_bot_module()
        out = ("PID\tStatus\tLabel\n-\t78\tcom.pinchtab.server\n123\t0\tcom.chromecdp.pinchtab\n"
               "-\t0\tcom.other\n")
        with patch.object(m.subprocess, "run", return_value=MagicMock(stdout=out)):
            codes = m.pinchtab_launchd_exit_codes()
        self.assertEqual(codes, {"com.pinchtab.server": "78", "com.chromecdp.pinchtab": "0"})

if __name__ == "__main__":
    unittest.main()
