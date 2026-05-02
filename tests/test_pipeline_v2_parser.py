"""Tests for Pipeline v2 parser additions (Commit 1 of Phase 1).

Validates that:
- StepType enum normalizes YAML values correctly
- New PipelineStep fields (type, command, validates, publishes, sink, etc.)
  parse with safe defaults
- pipeline_version frontmatter field parses correctly
- v1 pipelines (no type:, no pipeline_version) parse identically to before
- accepts_overrides parses as dict
- Q15 warning fires when type:script + non-default engine

This commit is purely additive — the executor doesn't read any of these new
fields yet (that lands in Commits 3-6). These tests guard the parse contract.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _botload import load_bot_module, ensure_agent_layout


PIPELINE_BODY_MINIMAL = """```pipeline
steps:
  - id: foo
    name: Foo
    model: sonnet
    prompt: hello world
```"""

PIPELINE_BODY_WITH_TYPE = """```pipeline
steps:
  - id: foo
    name: Foo
    model: sonnet
    prompt: hello
    type: script
    command: python3 scripts/foo.py
    accepts_overrides:
      focus_asset:
        type: string
        default: BTC
```"""

PIPELINE_BODY_INVALID_TYPE = """```pipeline
steps:
  - id: foo
    name: Foo
    model: sonnet
    prompt: hello
    type: bogus
```"""

PIPELINE_BODY_VALIDATE_STEP = """```pipeline
steps:
  - id: writer
    name: Writer
    model: sonnet
    prompt: write
  - id: writer-check
    name: Check Writer
    model: sonnet
    prompt: stub
    type: validate
    validates: writer
    on_failure: feedback
    command: python3 scripts/check.py
```"""


class StepTypeFromYamlTests(unittest.TestCase):
    """StepType.from_yaml normalization (Q12 + back-compat contract)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="pv2-stype-"))
        cls.bot = load_bot_module(tmp_home=cls.tmp)

    def test_default_when_none(self):
        self.assertEqual(self.bot.StepType.from_yaml(None), self.bot.StepType.LLM)

    def test_default_when_empty_string(self):
        self.assertEqual(self.bot.StepType.from_yaml(""), self.bot.StepType.LLM)

    def test_explicit_script(self):
        self.assertEqual(self.bot.StepType.from_yaml("script"), self.bot.StepType.SCRIPT)

    def test_explicit_validate(self):
        self.assertEqual(self.bot.StepType.from_yaml("validate"), self.bot.StepType.VALIDATE)

    def test_explicit_publish(self):
        self.assertEqual(self.bot.StepType.from_yaml("publish"), self.bot.StepType.PUBLISH)

    def test_explicit_gate(self):
        self.assertEqual(self.bot.StepType.from_yaml("gate"), self.bot.StepType.GATE)

    def test_uppercase_normalized(self):
        self.assertEqual(self.bot.StepType.from_yaml("SCRIPT"), self.bot.StepType.SCRIPT)

    def test_whitespace_stripped(self):
        self.assertEqual(self.bot.StepType.from_yaml("  script  "), self.bot.StepType.SCRIPT)

    def test_unknown_falls_back_to_llm_with_warning(self):
        with self.assertLogs("claude-bot", level="WARNING") as cm:
            result = self.bot.StepType.from_yaml("bogus")
        self.assertEqual(result, self.bot.StepType.LLM)
        self.assertTrue(any("bogus" in msg for msg in cm.output))

    def test_str_enum_equality(self):
        """StepType inherits from str, so members compare equal to their values.

        This is important for the dispatcher in _execute_step (commit 3) which
        will do `step.type == StepType.SCRIPT.value` style comparisons.
        """
        self.assertEqual(self.bot.StepType.LLM, "llm")
        self.assertEqual(self.bot.StepType.SCRIPT.value, "script")


class PipelineV2ParserTests(unittest.TestCase):
    """_parse_pipeline_task picks up the new YAML fields with safe defaults."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="pv2-parse-"))
        cls.bot = load_bot_module(tmp_home=cls.tmp)
        ensure_agent_layout(cls.bot.VAULT_DIR, "main")
        cls.routines = cls.bot.VAULT_DIR / "main" / "Routines"
        cls.routines.mkdir(parents=True, exist_ok=True)

    def _parse(self, fm: dict, body: str, name: str = "test-pipeline"):
        md_file = self.routines / f"{name}.md"
        md_file.write_text("---\n# stub\n---\n" + body, encoding="utf-8")
        return self.bot._parse_pipeline_task(md_file, fm, body, name, "sonnet", "00:00")

    def test_v1_pipeline_step_type_defaults_to_llm(self):
        task = self._parse({}, PIPELINE_BODY_MINIMAL)
        self.assertIsNotNone(task)
        step = task.steps[0]
        self.assertEqual(step.type, "llm")
        self.assertEqual(step.command, "")
        self.assertEqual(step.accepts_overrides, {})
        self.assertIsNone(step.validates)
        self.assertIsNone(step.publishes)
        self.assertIsNone(step.reviews)
        self.assertIsNone(step.sink)
        self.assertEqual(step.sink_config, {})
        self.assertEqual(step.on_failure, "fail")

    def test_v1_pipeline_pipeline_version_defaults_to_1(self):
        task = self._parse({}, PIPELINE_BODY_MINIMAL)
        self.assertIsNotNone(task)
        self.assertEqual(task.pipeline_version, 1)
        self.assertEqual(task.applied_overrides, {})

    def test_explicit_type_script_with_command(self):
        task = self._parse({}, PIPELINE_BODY_WITH_TYPE)
        self.assertIsNotNone(task)
        step = task.steps[0]
        self.assertEqual(step.type, "script")
        self.assertEqual(step.command, "python3 scripts/foo.py")
        self.assertIn("focus_asset", step.accepts_overrides)
        self.assertEqual(step.accepts_overrides["focus_asset"]["default"], "BTC")

    def test_unknown_type_falls_back_with_warning(self):
        with self.assertLogs("claude-bot", level="WARNING") as cm:
            task = self._parse({}, PIPELINE_BODY_INVALID_TYPE)
        self.assertEqual(task.steps[0].type, "llm")
        self.assertTrue(any("bogus" in msg.lower() for msg in cm.output))

    def test_validate_step_fields(self):
        task = self._parse({}, PIPELINE_BODY_VALIDATE_STEP)
        self.assertIsNotNone(task)
        validate_step = next(s for s in task.steps if s.id == "writer-check")
        self.assertEqual(validate_step.type, "validate")
        self.assertEqual(validate_step.validates, "writer")
        self.assertEqual(validate_step.on_failure, "feedback")
        self.assertEqual(validate_step.command, "python3 scripts/check.py")

    def test_pipeline_version_2_with_flag_off_logs_warning(self):
        # Tests run with PIPELINE_V2_ENABLED unset → False
        self.assertFalse(self.bot.PIPELINE_V2_ENABLED)
        with self.assertLogs("claude-bot", level="WARNING") as cm:
            task = self._parse({"pipeline_version": 2}, PIPELINE_BODY_MINIMAL)
        self.assertEqual(task.pipeline_version, 2)
        joined = "\n".join(cm.output)
        self.assertIn("PIPELINE_V2_ENABLED", joined)
        self.assertIn("v1 code path", joined)

    def test_pipeline_version_invalid_falls_back(self):
        with self.assertLogs("claude-bot", level="WARNING") as cm:
            task = self._parse({"pipeline_version": "bogus"}, PIPELINE_BODY_MINIMAL)
        self.assertEqual(task.pipeline_version, 1)
        self.assertTrue(any("invalid pipeline_version" in msg.lower() for msg in cm.output))

    def test_accepts_overrides_non_dict_logged_and_ignored(self):
        body = """```pipeline
steps:
  - id: foo
    name: Foo
    model: sonnet
    prompt: hello
    accepts_overrides: not-a-dict
```"""
        with self.assertLogs("claude-bot", level="WARNING") as cm:
            task = self._parse({}, body)
        self.assertEqual(task.steps[0].accepts_overrides, {})
        self.assertTrue(any("accepts_overrides must be a dict" in msg for msg in cm.output))

    def test_engine_warning_for_non_llm_step(self):
        """Q15: engine field only meaningful for type:llm."""
        body = """```pipeline
steps:
  - id: foo
    name: Foo
    model: sonnet
    prompt: hello
    type: script
    command: echo hi
    engine: codex
```"""
        with self.assertLogs("claude-bot", level="WARNING") as cm:
            task = self._parse({}, body)
        self.assertEqual(task.steps[0].type, "script")
        self.assertTrue(any("engine is only meaningful for type:llm" in msg for msg in cm.output))

    def test_invalid_on_failure_falls_back_to_fail(self):
        body = """```pipeline
steps:
  - id: foo
    name: Foo
    model: sonnet
    prompt: hello
    type: validate
    validates: foo
    on_failure: bogus
    command: echo hi
```"""
        with self.assertLogs("claude-bot", level="WARNING") as cm:
            task = self._parse({}, body)
        self.assertEqual(task.steps[0].on_failure, "fail")
        self.assertTrue(any("unknown on_failure" in msg.lower() for msg in cm.output))


class PipelineV2BackcompatTests(unittest.TestCase):
    """A v1 pipeline (no type:, no pipeline_version) parses identically to before."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="pv2-bc-"))
        cls.bot = load_bot_module(tmp_home=cls.tmp)
        ensure_agent_layout(cls.bot.VAULT_DIR, "main")

    def test_existing_v1_pipeline_fields_preserved(self):
        """All pre-existing PipelineStep fields keep working — adding new fields
        with defaults must not break the existing ones."""
        body = """```pipeline
steps:
  - id: collect
    name: Collect
    model: haiku
    prompt: collect data
    timeout: 300
    inactivity_timeout: 120
    retry: 1
    output: file
  - id: analyze
    name: Analyze
    model: opus
    prompt: analyze
    depends_on: [collect]
    timeout: 900
```"""
        routines = self.bot.VAULT_DIR / "main" / "Routines"
        routines.mkdir(parents=True, exist_ok=True)
        md = routines / "v1-pipeline.md"
        md.write_text("---\nfoo: bar\n---\n" + body, encoding="utf-8")
        task = self.bot._parse_pipeline_task(md, {}, body, "v1-pipeline", "sonnet", "12:00")
        self.assertIsNotNone(task)
        self.assertEqual(len(task.steps), 2)
        # Existing fields unchanged
        self.assertEqual(task.steps[0].timeout, 300)
        self.assertEqual(task.steps[0].inactivity_timeout, 120)
        self.assertEqual(task.steps[0].retry, 1)
        self.assertEqual(task.steps[0].output_type, "file")
        self.assertEqual(task.steps[1].depends_on, ["collect"])
        self.assertEqual(task.steps[1].model, "opus")
        # New fields all default
        for step in task.steps:
            self.assertEqual(step.type, "llm")
            self.assertEqual(step.command, "")
            self.assertEqual(step.accepts_overrides, {})
            self.assertIsNone(step.sink)
        # Pipeline-level new fields default
        self.assertEqual(task.pipeline_version, 1)
        self.assertEqual(task.applied_overrides, {})


if __name__ == "__main__":
    unittest.main()
