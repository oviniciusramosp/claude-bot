"""🧠 reasoning panel on the streaming message (v3.88).

The panel was the last 1500 raw chars of thinking under a separate tool log,
cut at any byte: mid-word, mid-**bold**, or inside a ``` fence — which closed
the quote early (HTML) and leaked raw ``>`` markers into a code block. It is
now one chronological timeline cut only between steps or at a word, with the
markup that cannot live inside a quote removed.
"""
import threading
import unittest

from tests._botload import load_bot_module


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_bot_module()

    def setUp(self):
        cls = self.m.ClaudeTelegramBot
        self.bot = cls.__new__(cls)
        self.bot._ctx_local = threading.local()
        self.r = self.m.ClaudeRunner()

    def think(self, text):
        self.r._handle_event({"type": "assistant", "message": {"content": [
            {"type": "thinking", "thinking": text}]}})

    def tool(self, cmd):
        self.r._handle_event({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": cmd}}]}})

    def display(self, snapshot="resposta"):
        return self.bot._build_stream_display(snapshot, self.r, 1, 5, True)


class Timeline(_Base):
    def test_thoughts_and_tools_keep_their_order(self):
        self.think("primeiro penso")
        self.tool("ls vault")
        self.think("depois decido")
        d = self.display()
        self.assertLess(d.index("primeiro penso"), d.index("ls vault"))
        self.assertLess(d.index("ls vault"), d.index("depois decido"))
        self.assertIn("💭 primeiro penso", d)

    def test_reset_between_runs_and_retry(self):
        self.think("velho")
        self.r._reset_for_retry()
        self.assertEqual(self.r.get_reasoning_entries(), [])

    def test_header_is_plain_text(self):
        self.think("x")
        self.assertTrue(self.display().startswith("**> 🧠 Raciocínio\n"))


class SafeInsideQuote(_Base):
    def test_code_fence_in_thinking_does_not_break_the_quote(self):
        self.think("Plano:\n```py\nx = 1\n```\nfim")
        d = self.display()
        self.assertNotIn("```", d.split("\n\nresposta")[0])
        html = self.bot._markdown_to_html(d)
        self.assertEqual(html.count("<blockquote"), 1)
        self.assertNotIn("&gt;", html)
        self.assertIn("x = 1", html)

    def test_headings_and_nested_quotes_are_flattened(self):
        self.think("## Plano\n> citado\ntexto")
        panel = self.m._clean_reasoning_text("## Plano\n> citado\ntexto")
        self.assertEqual(panel, "Plano\ncitado\ntexto")

    def test_unbalanced_markup_is_dropped(self):
        self.assertEqual(self.m._clean_reasoning_text("isso **é importante"), "isso é importante")
        self.assertEqual(self.m._clean_reasoning_text("rodei `ls"), "rodei ls")
        self.assertEqual(self.m._clean_reasoning_text("ok **sim** `a`"), "ok **sim** `a`")


class Cutting(_Base):
    def test_long_history_drops_whole_old_steps_and_says_so(self):
        for i in range(60):
            self.think(f"passo número {i} com bastante texto para ocupar espaço no painel. " * 2)
        d = self.display()
        self.assertIn("passos anteriores", d)
        self.assertIn("passo número 59", d)
        self.assertNotIn("passo número 0 ", d)

    def test_cut_happens_at_a_word(self):
        out = self.m._cut_head_at_word("palavra " * 100, 50)
        self.assertTrue(out.startswith("…palavra"))

    def test_html_display_fits_telegram_limit(self):
        for i in range(200):
            self.think("raciocínio longo " * 30)
        d = self.display("r" * 10000)
        self.assertLessEqual(len(d), self.m.MAX_MESSAGE_LENGTH)
        self.assertTrue(d.startswith("**> 🧠"))  # header never sliced off


class PreviewTail(_Base):
    def test_cut_inside_code_block_reopens_it(self):
        text = "Intro\n```python\n" + "\n".join(f"x{i} = {i}" for i in range(500)) + "\n```\nfim"
        out = self.m._trim_preview_tail(text, 600)
        self.assertTrue(out.startswith("…\n```python\n"))
        self.assertTrue(out.endswith("fim"))

    def test_cut_outside_code_starts_at_a_line(self):
        text = "\n".join(f"linha {i} de texto" for i in range(300))
        out = self.m._trim_preview_tail(text, 300)
        self.assertTrue(out.startswith("…\nlinha "))
        self.assertNotIn("```", out)

    def test_short_text_untouched(self):
        self.assertEqual(self.m._trim_preview_tail("oi", 100), "oi")


if __name__ == "__main__":
    unittest.main()
