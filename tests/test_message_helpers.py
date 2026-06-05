"""Unit tests for message-formatting helpers on ClaudeTelegramBot.

These are all @staticmethod, so we can call them directly without
instantiating the bot — which avoids needing real Telegram credentials.
"""
import unittest

from tests._botload import load_bot_module


class SplitMessage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()
        cls.split = staticmethod(cls.bot.ClaudeTelegramBot._split_message)
        cls.MAX = cls.bot.MAX_MESSAGE_LENGTH

    def test_short_message_returned_as_one(self):
        chunks = self.split("hello")
        self.assertEqual(chunks, ["hello"])

    def test_exactly_at_limit(self):
        text = "a" * self.MAX
        chunks = self.split(text)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], text)

    def test_split_at_paragraph(self):
        para = "x" * (self.MAX // 2 + 100)
        text = para + "\n\n" + para
        chunks = self.split(text)
        self.assertGreater(len(chunks), 1)
        # Concatenation should reproduce the original (allowing for boundary trim)
        joined = "".join(chunks)
        self.assertGreaterEqual(len(joined), len(text) - 4)

    def test_does_not_split_inside_code_block(self):
        # Construct a long string ending inside a code block
        prose = "intro\n\n"
        code = "```python\n" + ("# comment line\n" * 200) + "```"
        text = prose + code
        chunks = self.split(text)
        # Each chunk's ``` count must be even (no chunk leaves a code block open
        # unless it spans the whole block).
        for chunk in chunks:
            self.assertEqual(
                chunk.count("```") % 2,
                0,
                f"Chunk leaves code block unbalanced: {chunk[:80]!r}",
            )

    def test_hard_split_for_pathological_input(self):
        # No newlines anywhere — must still split (hard split path)
        text = "x" * (self.MAX * 3)
        chunks = self.split(text)
        self.assertGreaterEqual(len(chunks), 3)
        for c in chunks:
            self.assertLessEqual(len(c), self.MAX)


class StripMarkdown(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()
        cls.strip = staticmethod(cls.bot.ClaudeTelegramBot._strip_markdown)

    def test_removes_emoji(self):
        # Saved feedback memory: TTS must not include emoji
        out = self.strip("Hello 👍 world ❌ done")
        self.assertNotIn("👍", out)
        self.assertNotIn("❌", out)
        self.assertIn("Hello", out)
        self.assertIn("world", out)

    def test_strips_code_blocks(self):
        out = self.strip("Before\n```python\nprint('hi')\n```\nAfter")
        self.assertNotIn("print", out)
        self.assertIn("Before", out)
        self.assertIn("After", out)

    def test_strips_inline_code(self):
        out = self.strip("use `foo()` to call")
        self.assertIn("foo()", out)
        self.assertNotIn("`", out)

    def test_strips_bold_italic(self):
        out = self.strip("**bold** and *italic* and __under__")
        self.assertIn("bold", out)
        self.assertIn("italic", out)
        self.assertIn("under", out)
        self.assertNotIn("**", out)
        self.assertNotIn("*", out)
        self.assertNotIn("__", out)

    def test_strips_links_keeps_text(self):
        out = self.strip("see [docs](https://x.com/y)")
        self.assertIn("docs", out)
        self.assertNotIn("https", out)

    def test_strips_headings(self):
        out = self.strip("# H1\n## H2\nbody")
        self.assertIn("H1", out)
        self.assertIn("H2", out)
        self.assertNotIn("#", out)

    def test_strips_bullet_markers(self):
        out = self.strip("- one\n- two\n- three")
        self.assertNotIn("- ", out)
        self.assertIn("one", out)

    def test_strips_cost_line(self):
        out = self.strip("Done.\n\n💰 $0.0123 (250 tokens)")
        self.assertNotIn("0.0123", out)
        self.assertIn("Done", out)

    def test_collapses_blank_lines(self):
        out = self.strip("a\n\n\n\nb")
        self.assertNotIn("\n\n", out)


class ExtractCopyableCode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()
        cls.extract = staticmethod(cls.bot.ClaudeTelegramBot._extract_copyable_code)

    def test_no_blocks_returns_none(self):
        self.assertIsNone(self.extract("just prose"))

    def test_two_blocks_returns_none(self):
        text = "```\na\n```\nmiddle\n```\nb\n```"
        self.assertIsNone(self.extract(text))

    def test_dominant_block_extracted(self):
        code = "def foo():\n    return 42\n" * 5
        text = "Here it is:\n```python\n" + code + "```"
        out = self.extract(text)
        self.assertIsNotNone(out)
        self.assertIn("def foo", out)

    def test_too_short_returns_none(self):
        text = "```\nx\n```"
        self.assertIsNone(self.extract(text))

    def test_too_much_prose_returns_none(self):
        prose = "x" * 1000
        small_code = "```\nfn()\n```"
        text = prose + small_code
        self.assertIsNone(self.extract(text))


class SanitizeMarkdownV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()
        cls.sanitize = staticmethod(cls.bot.ClaudeTelegramBot._sanitize_markdown_v2)

    def test_balances_code_blocks(self):
        # Unbalanced ``` should get a closing one appended
        text = "intro\n```\ncode here"
        out = self.sanitize(text)
        self.assertEqual(out.count("```") % 2, 0)

    def test_escapes_special_chars_in_prose(self):
        # MDv2 requires escaping of . ! - = etc.
        out = self.sanitize("Hello world. How are you?")
        # The . should be escaped as \.
        self.assertIn("\\.", out)

    def test_preserves_code_block_contents(self):
        text = "```\ndef f(): pass\n```"
        out = self.sanitize(text)
        self.assertIn("def f(): pass", out)

    def test_preserves_inline_code(self):
        out = self.sanitize("call `foo.bar()` now.")
        # Inside backticks should not be escaped
        self.assertIn("`foo.bar()`", out)

    def test_link_text_escaped_url_preserved(self):
        out = self.sanitize("see [docs.io](https://example.com/x.y)")
        self.assertIn("https://example.com/x.y", out)


class UnescapeMdv2(unittest.TestCase):
    """`_unescape_mdv2` reverses the escaping applied by `_sanitize_markdown_v2`.

    Used as the retry fallback when Telegram rejects a MarkdownV2 message.
    Without the reverse step, users see raw backslashes in their chat (e.g.
    `@foo\\_bar comentou\\.`) which looks like garbage.
    """

    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()
        cls.sanitize = staticmethod(cls.bot.ClaudeTelegramBot._sanitize_markdown_v2)
        cls.unescape = staticmethod(cls.bot.ClaudeTelegramBot._unescape_mdv2)

    def test_roundtrip_restores_plain_text(self):
        original = "Hello world. How are you?"
        sanitized = self.sanitize(original)
        self.assertIn("\\.", sanitized)  # confirm the escape was added
        self.assertEqual(self.unescape(sanitized), original)

    def test_roundtrip_preserves_mentions(self):
        original = "O @foo_bar disse algo interessante."
        sanitized = self.sanitize(original)
        self.assertEqual(self.unescape(sanitized), original)

    def test_roundtrip_preserves_urls(self):
        original = "Veja https://threads.com/@user_name/post/abc_def"
        sanitized = self.sanitize(original)
        self.assertEqual(self.unescape(sanitized), original)

    def test_roundtrip_preserves_code_blocks(self):
        original = "intro\n```python\nx = foo.bar(1.2)\n```\nend."
        sanitized = self.sanitize(original)
        unescaped = self.unescape(sanitized)
        # Code block contents untouched; prose outside restored
        self.assertIn("x = foo.bar(1.2)", unescaped)
        self.assertIn("end.", unescaped)
        self.assertNotIn("\\.", unescaped)

    def test_does_not_touch_already_clean_text(self):
        clean = "Nothing to escape here"
        self.assertEqual(self.unescape(clean), clean)


class SanitizeMarkdownV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()
        cls.sanitize = staticmethod(cls.bot.ClaudeTelegramBot._sanitize_markdown)

    def test_balances_triple_backticks(self):
        out = self.sanitize("```\ncode without close")
        self.assertEqual(out.count("```") % 2, 0)

    def test_balances_inline_backticks(self):
        out = self.sanitize("missing `close")
        self.assertEqual(out.count("`") % 2, 0)

    def test_balanced_input_unchanged(self):
        text = "all `good` here"
        self.assertEqual(self.sanitize(text), text)


def _html_is_telegram_valid(html_txt: str) -> bool:
    """Mirror Telegram's HTML constraints: tags balanced, properly nested, and
    no identical tag nested inside itself (all 400 the real API)."""
    import re
    stack = []
    for m in re.finditer(r"<\s*(/?)\s*([a-zA-Z][a-zA-Z0-9-]*)[^>]*>", html_txt):
        name = m.group(2).lower()
        if m.group(1) == "/":
            if not stack or stack[-1] != name:
                return False
            stack.pop()
        else:
            if name in stack:
                return False  # nested identical tag
            stack.append(name)
    return not stack


class MarkdownToHtml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()
        cls.html = staticmethod(cls.bot.ClaudeTelegramBot._markdown_to_html)

    def test_h2_becomes_bold(self):
        self.assertEqual(self.html("## Resumo"), "<b>Resumo</b>")

    def test_heading_does_not_leak_hashes(self):
        for src in ("## Título", "### Sub", "#### Quatro", "  ## Indentado"):
            self.assertNotIn("#", self.html(src), src)

    def test_heading_with_bold_no_nested_tags(self):
        # The classic 400-trigger: ## **X** used to make <b><b>X</b></b>.
        out = self.html("### **Pontos Chave**")
        self.assertEqual(out, "<b>Pontos Chave</b>")
        self.assertTrue(_html_is_telegram_valid(out))

    def test_atx_closed_heading(self):
        self.assertEqual(self.html("## Título ##"), "<b>Título</b>")

    def test_double_star_bold(self):
        self.assertEqual(self.html("**negrito**"), "<b>negrito</b>")

    def test_mixed_star_levels_stay_valid(self):
        out = self.html("**bold com *enfase* dentro**")
        self.assertTrue(_html_is_telegram_valid(out))

    def test_inline_code_and_special_chars_escaped(self):
        out = self.html("use `a < b && c > d`")
        self.assertIn("<code>", out)
        self.assertIn("&lt;", out)
        self.assertIn("&amp;", out)

    def test_raw_angle_brackets_are_escaped_not_tags(self):
        # Model emitting literal HTML must be shown as text, never interpreted.
        out = self.html("<script>alert(1)</script>")
        self.assertNotIn("<script>", out)
        self.assertIn("&lt;script&gt;", out)

    def test_code_fence_to_pre(self):
        out = self.html("```py\nprint(1)\n```")
        self.assertIn('<pre><code class="language-py">', out)
        self.assertTrue(_html_is_telegram_valid(out))

    def test_links(self):
        out = self.html("[site](https://x.com)")
        self.assertIn('<a href="https://x.com">site</a>', out)

    def test_realistic_message_is_valid(self):
        src = ("## Análise\n\n**Resumo:** o `bot` está ok.\n\n"
               "- Ponto A\n- Ponto B\n\n### Conclusão\n\nFim com *ênfase*.")
        out = self.html(src)
        self.assertTrue(_html_is_telegram_valid(out))
        self.assertNotIn("##", out)
        self.assertNotIn("**", out)


class SanitizeTelegramHtml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()
        cls.san = staticmethod(cls.bot.ClaudeTelegramBot._sanitize_telegram_html)

    def test_collapses_nested_same_tag(self):
        self.assertEqual(self.san("<b><b>x</b></b>"), "<b>x</b>")

    def test_closes_unclosed_tag(self):
        out = self.san("<b>unterminated")
        self.assertEqual(out, "<b>unterminated</b>")
        self.assertTrue(_html_is_telegram_valid(out))

    def test_drops_stray_close(self):
        self.assertEqual(self.san("plain</b> text"), "plain text")

    def test_drops_unsupported_tag(self):
        self.assertEqual(self.san("<div>x</div>"), "x")

    def test_keeps_link_attributes(self):
        text = '<a href="https://x.com">y</a>'
        self.assertEqual(self.san(text), text)

    def test_idempotent_on_valid(self):
        text = "<b>a</b> and <i>b</i>"
        self.assertEqual(self.san(text), text)

    def test_nested_different_tags_preserved(self):
        text = "<b>bold <i>italic</i></b>"
        self.assertEqual(self.san(text), text)


class RebalanceHtmlChunks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()
        cls.reb = staticmethod(cls.bot.ClaudeTelegramBot._rebalance_html_chunks)

    def test_reopens_tag_across_split(self):
        # Simulate a split that cut between <b> and </b>.
        chunks = ["start <b>bold text", "more bold</b> end"]
        out = self.reb(chunks)
        self.assertTrue(all(_html_is_telegram_valid(c) for c in out))
        self.assertTrue(out[0].endswith("</b>"))
        self.assertTrue(out[1].startswith("<b>"))

    def test_valid_chunks_unchanged_count(self):
        chunks = ["<b>one</b>", "<i>two</i>"]
        out = self.reb(chunks)
        self.assertEqual(len(out), 2)
        self.assertTrue(all(_html_is_telegram_valid(c) for c in out))

    def test_long_bold_split_stays_valid(self):
        bot = self.bot
        # One bold span far larger than MAX_MESSAGE_LENGTH so the split lands
        # inside it, cutting between <b> and </b>.
        reps = (bot.MAX_MESSAGE_LENGTH // 5) + 500
        big = bot.ClaudeTelegramBot._markdown_to_html("**" + ("word " * reps) + "**")
        chunks = bot.ClaudeTelegramBot._split_message(big)
        out = self.reb(chunks)
        self.assertGreater(len(out), 1)
        self.assertTrue(all(_html_is_telegram_valid(c) for c in out))


if __name__ == "__main__":
    unittest.main()
