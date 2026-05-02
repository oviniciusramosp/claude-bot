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


class OverrideValidationTests(unittest.TestCase):
    """validate_overrides() + helpers (Commit 2 of Phase 1).

    Tests the runtime override validator that will be called by /run --overrides
    and the agent NL parser in Commit 9.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="pv2-overrides-"))
        cls.bot = load_bot_module(tmp_home=cls.tmp)
        ensure_agent_layout(cls.bot.VAULT_DIR, "main")
        cls.routines = cls.bot.VAULT_DIR / "main" / "Routines"
        cls.routines.mkdir(parents=True, exist_ok=True)

    def _build_task_with_schema(self, schema_yaml: str, name="ovr-test"):
        body = (
            "```pipeline\n"
            "steps:\n"
            "  - id: analyst\n"
            "    name: Analyst\n"
            "    model: sonnet\n"
            "    prompt: do analysis\n"
            f"{schema_yaml}"
            "  - id: writer\n"
            "    name: Writer\n"
            "    model: sonnet\n"
            "    prompt: do writing\n"
            "```"
        )
        md_file = self.routines / f"{name}.md"
        md_file.write_text("---\nfoo: bar\n---\n" + body, encoding="utf-8")
        return self.bot._parse_pipeline_task(md_file, {}, body, name, "sonnet", "00:00")

    def test_empty_overrides_returns_defaults_only(self):
        schema = (
            "    accepts_overrides:\n"
            "      focus_asset:\n"
            "        type: string\n"
            "        default: BTC\n"
        )
        task = self._build_task_with_schema(schema)
        result = self.bot.validate_overrides(task, None)
        self.assertEqual(result, {"analyst": {"focus_asset": "BTC"}})

    def test_none_overrides_returns_defaults(self):
        schema = (
            "    accepts_overrides:\n"
            "      depth:\n"
            "        type: string\n"
            "        default: normal\n"
        )
        task = self._build_task_with_schema(schema)
        self.assertEqual(self.bot.validate_overrides(task, None),
                         {"analyst": {"depth": "normal"}})

    def test_user_override_replaces_default(self):
        schema = (
            "    accepts_overrides:\n"
            "      focus_asset:\n"
            "        type: string\n"
            "        default: BTC\n"
        )
        task = self._build_task_with_schema(schema)
        result = self.bot.validate_overrides(task, {"analyst": {"focus_asset": "ETH"}})
        self.assertEqual(result, {"analyst": {"focus_asset": "ETH"}})

    def test_per_step_isolation_q2(self):
        """Q2: defaults from one step do NOT propagate to another step.

        Even if step.writer has no `focus_asset` schema, it must not inherit
        analyst's `focus_asset` value.
        """
        schema = (
            "    accepts_overrides:\n"
            "      focus_asset:\n"
            "        type: string\n"
            "        default: BTC\n"
        )
        task = self._build_task_with_schema(schema)
        result = self.bot.validate_overrides(task, {"analyst": {"focus_asset": "ETH"}})
        # writer is absent from result (no schema, no overrides)
        self.assertNotIn("writer", result)

    def test_unknown_step_id_raises(self):
        schema = "    accepts_overrides:\n      x:\n        type: string\n"
        task = self._build_task_with_schema(schema)
        with self.assertRaises(self.bot.OverrideValidationError) as cm:
            self.bot.validate_overrides(task, {"bogus_step": {"x": "y"}})
        self.assertIn("unknown step id", str(cm.exception))
        self.assertIn("bogus_step", str(cm.exception))

    def test_unknown_attr_raises(self):
        schema = "    accepts_overrides:\n      focus_asset:\n        type: string\n"
        task = self._build_task_with_schema(schema)
        with self.assertRaises(self.bot.OverrideValidationError) as cm:
            self.bot.validate_overrides(task, {"analyst": {"unknown_attr": "x"}})
        self.assertIn("unknown_attr", str(cm.exception))
        self.assertIn("not in", str(cm.exception).lower())

    def test_wrong_type_string_vs_integer_raises(self):
        schema = (
            "    accepts_overrides:\n"
            "      retries:\n"
            "        type: integer\n"
        )
        task = self._build_task_with_schema(schema)
        with self.assertRaises(self.bot.OverrideValidationError) as cm:
            self.bot.validate_overrides(task, {"analyst": {"retries": "not-a-number"}})
        self.assertIn("expected type", str(cm.exception))
        self.assertIn("integer", str(cm.exception))

    def test_enum_violation_raises(self):
        schema = (
            "    accepts_overrides:\n"
            "      focus_asset:\n"
            "        type: string\n"
            "        enum: [BTC, ETH, SOL]\n"
        )
        task = self._build_task_with_schema(schema)
        with self.assertRaises(self.bot.OverrideValidationError) as cm:
            self.bot.validate_overrides(task, {"analyst": {"focus_asset": "DOGE"}})
        self.assertIn("not in enum", str(cm.exception))

    def test_enum_accepts_valid_value(self):
        schema = (
            "    accepts_overrides:\n"
            "      focus_asset:\n"
            "        type: string\n"
            "        enum: [BTC, ETH, SOL]\n"
        )
        task = self._build_task_with_schema(schema)
        result = self.bot.validate_overrides(task, {"analyst": {"focus_asset": "ETH"}})
        self.assertEqual(result["analyst"]["focus_asset"], "ETH")

    def test_oversized_string_rejected(self):
        schema = "    accepts_overrides:\n      blob:\n        type: string\n"
        task = self._build_task_with_schema(schema)
        huge = "x" * 5000
        with self.assertRaises(self.bot.OverrideValidationError) as cm:
            self.bot.validate_overrides(task, {"analyst": {"blob": huge}})
        self.assertIn("too long", str(cm.exception))

    def test_nan_rejected(self):
        schema = "    accepts_overrides:\n      ratio:\n        type: number\n"
        task = self._build_task_with_schema(schema)
        with self.assertRaises(self.bot.OverrideValidationError) as cm:
            self.bot.validate_overrides(task, {"analyst": {"ratio": float("nan")}})
        self.assertIn("NaN", str(cm.exception))

    def test_infinity_rejected(self):
        schema = "    accepts_overrides:\n      ratio:\n        type: number\n"
        task = self._build_task_with_schema(schema)
        with self.assertRaises(self.bot.OverrideValidationError) as cm:
            self.bot.validate_overrides(task, {"analyst": {"ratio": float("inf")}})
        self.assertIn("Infinity", str(cm.exception))

    def test_overrides_must_be_dict(self):
        schema = "    accepts_overrides:\n      x:\n        type: string\n"
        task = self._build_task_with_schema(schema)
        with self.assertRaises(self.bot.OverrideValidationError):
            self.bot.validate_overrides(task, "not a dict")

    def test_step_overrides_must_be_dict(self):
        schema = "    accepts_overrides:\n      x:\n        type: string\n"
        task = self._build_task_with_schema(schema)
        with self.assertRaises(self.bot.OverrideValidationError):
            self.bot.validate_overrides(task, {"analyst": "not-a-dict"})


class OverrideHelpersTests(unittest.TestCase):
    """_merge_overrides_for_step and _overrides_to_env_vars."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="pv2-helpers-"))
        cls.bot = load_bot_module(tmp_home=cls.tmp)

    def _make_step(self, sid="foo"):
        return self.bot.PipelineStep(id=sid, name=sid, model="sonnet", prompt="x")

    def test_merge_returns_empty_when_no_overrides(self):
        step = self._make_step()
        self.assertEqual(self.bot._merge_overrides_for_step(step, None), {})
        self.assertEqual(self.bot._merge_overrides_for_step(step, {}), {})

    def test_merge_returns_step_dict(self):
        step = self._make_step("analyst")
        applied = {"analyst": {"focus_asset": "ETH"}, "writer": {"x": 1}}
        self.assertEqual(self.bot._merge_overrides_for_step(step, applied),
                         {"focus_asset": "ETH"})

    def test_merge_returns_empty_for_step_not_in_overrides(self):
        step = self._make_step("absent")
        applied = {"analyst": {"focus_asset": "ETH"}}
        self.assertEqual(self.bot._merge_overrides_for_step(step, applied), {})

    def test_env_vars_string_unquoted(self):
        env = self.bot._overrides_to_env_vars({"focus_asset": "ETH"})
        self.assertEqual(env, {"STEP_OVERRIDE_FOCUS_ASSET": "ETH"})

    def test_env_vars_boolean_lowercase(self):
        env = self.bot._overrides_to_env_vars({"verbose": True, "dry_run": False})
        self.assertEqual(env["STEP_OVERRIDE_VERBOSE"], "true")
        self.assertEqual(env["STEP_OVERRIDE_DRY_RUN"], "false")

    def test_env_vars_integer_json_encoded(self):
        env = self.bot._overrides_to_env_vars({"max_retries": 5})
        self.assertEqual(env["STEP_OVERRIDE_MAX_RETRIES"], "5")

    def test_env_vars_array_json_encoded(self):
        env = self.bot._overrides_to_env_vars({"assets": ["BTC", "ETH"]})
        self.assertEqual(env["STEP_OVERRIDE_ASSETS"], '["BTC", "ETH"]')

    def test_env_vars_object_json_encoded(self):
        env = self.bot._overrides_to_env_vars({"config": {"k": "v"}})
        self.assertEqual(env["STEP_OVERRIDE_CONFIG"], '{"k": "v"}')

    def test_env_vars_attr_uppercased(self):
        env = self.bot._overrides_to_env_vars({"focus_asset": "ETH"})
        self.assertIn("STEP_OVERRIDE_FOCUS_ASSET", env)
        self.assertNotIn("STEP_OVERRIDE_focus_asset", env)


if __name__ == "__main__":
    unittest.main()
