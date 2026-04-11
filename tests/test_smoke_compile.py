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
