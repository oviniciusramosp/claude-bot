"""Smoke test: every Python file in the project must compile cleanly.

This is the cheapest possible test — catches syntax errors before they hit
production. Run with: python3 -m unittest tests.test_smoke_compile
"""
import py_compile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Files that should compile. Globbed at runtime so new files are picked up.
# Note: mcp-server/ depends on the optional `mcp` SDK at runtime, but
# py_compile only parses — it does not execute imports — so it's safe to
# include here. This catches syntax errors in the MCP server before any
# user installs the optional dependency.
PYTHON_FILES = [
    REPO_ROOT / "claude-fallback-bot.py",
    REPO_ROOT / "claude-bot-menubar.py",
] + sorted((REPO_ROOT / "scripts").glob("*.py")) + sorted(
    (REPO_ROOT / "mcp-server").glob("*.py")
)


class CompilesCleanly(unittest.TestCase):
    def test_all_python_files_compile(self):
        for path in PYTHON_FILES:
            if not path.is_file():
                continue
            with self.subTest(file=path.relative_to(REPO_ROOT)):
                try:
                    py_compile.compile(str(path), doraise=True)
                except py_compile.PyCompileError as exc:
                    self.fail(f"{path.relative_to(REPO_ROOT)} failed to compile:\n{exc}")


class BotParsesUnderLaunchdInterpreter(unittest.TestCase):
    """launchd runs the bot as `/usr/bin/python3 claude-fallback-bot.py`.

    Python 3.9's script tokenizer (unlike py_compile, which parses from
    memory) reads long lines in chunks and rejects a multibyte char split
    across a chunk boundary: "Non-UTF-8 code starting with '\\xe2'". The
    BOT_VERSION changelog line grew past ~17KB and crash-looped the bot
    (v3.81.1). The coding cookie routes it through the codec reader.
    """

    BOT = REPO_ROOT / "claude-fallback-bot.py"
    LAUNCHD_PYTHON = Path("/usr/bin/python3")

    def test_coding_cookie_present(self):
        head = self.BOT.read_text(encoding="utf-8").splitlines()[:2]
        self.assertTrue(
            any("coding: utf-8" in line for line in head),
            "claude-fallback-bot.py must declare `# -*- coding: utf-8 -*-` "
            "in its first two lines (see class docstring)",
        )

    def test_script_path_parse(self):
        import subprocess
        import tempfile
        if not self.LAUNCHD_PYTHON.is_file():
            self.skipTest("/usr/bin/python3 not available")
        lines = self.BOT.read_text(encoding="utf-8").splitlines(keepends=True)
        # The whole file is parsed before the inserted line executes, so this exercises
        # the real tokenizer path with zero module side effects.
        cookie = next(i for i, l in enumerate(lines[:2]) if "coding: utf-8" in l)
        lines.insert(cookie + 1, "raise SystemExit(0)\n")
        with tempfile.TemporaryDirectory() as d:
            copy = Path(d) / "bot_parse_check.py"
            copy.write_text("".join(lines), encoding="utf-8")
            result = subprocess.run(
                [str(self.LAUNCHD_PYTHON), str(copy)],
                capture_output=True, text=True, timeout=60,
            )
        self.assertEqual(result.returncode, 0, result.stderr)


class ShellScriptsSyntaxOk(unittest.TestCase):
    """bash -n catches syntax errors in shell scripts."""

    def test_shell_scripts_parse(self):
        import subprocess
        scripts = sorted(REPO_ROOT.glob("*.sh"))
        scripts += sorted((REPO_ROOT / "scripts").glob("*.sh"))
        scripts += sorted((REPO_ROOT / "ClaudeBotManager").glob("*.sh"))
        for s in scripts:
            if not s.is_file():
                continue
            with self.subTest(script=s.relative_to(REPO_ROOT)):
                result = subprocess.run(
                    ["bash", "-n", str(s)],
                    capture_output=True, text=True,
                )
                self.assertEqual(
                    result.returncode, 0,
                    f"{s.name} has bash syntax error: {result.stderr}",
                )


if __name__ == "__main__":
    unittest.main()
