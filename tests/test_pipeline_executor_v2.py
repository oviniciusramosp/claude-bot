"""Tests for PipelineExecutor v2 type dispatcher (Commit 3 of Phase 1).

Validates that _execute_step routes to the right handler based on:
- step.manual (always wins, any pipeline_version)
- step.has_loop (always wins after manual)
- step.type when both PIPELINE_V2_ENABLED + pipeline_version >= 2
- LLM fallback otherwise

The handlers themselves are tested in commits 4-6 (script, validate, publish).
This commit only validates the dispatch contract.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _botload import load_bot_module, ensure_agent_layout


class DispatcherTestBase(unittest.TestCase):
    """Shared scaffolding to construct a minimal PipelineExecutor for dispatch tests."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="pv2-dispatch-"))
        cls.bot_mod = load_bot_module(tmp_home=cls.tmp)
        ensure_agent_layout(cls.bot_mod.VAULT_DIR, "main")

    def _make_executor(self, steps, pipeline_version=1):
        """Build a PipelineExecutor with mocked bot/ctx/state_mgr."""
        bot = MagicMock()
        ctx = MagicMock()
        state_mgr = MagicMock()
        task = self.bot_mod.PipelineTask(
            name="test-pipe",
            title="Test",
            steps=steps,
            model="sonnet",
            time_slot="00:00",
            agent="main",
            pipeline_version=pipeline_version,
        )
        return self.bot_mod.PipelineExecutor(task, bot, ctx, state_mgr)

    def _make_step(self, sid="s1", **kwargs):
        defaults = {"id": sid, "name": sid, "model": "sonnet", "prompt": "x"}
        defaults.update(kwargs)
        return self.bot_mod.PipelineStep(**defaults)


class DispatcherTests(DispatcherTestBase):
    """Type dispatcher routing precedence."""

    def test_default_v1_step_dispatches_to_llm(self):
        step = self._make_step()
        ex = self._make_executor([step], pipeline_version=1)
        with patch.object(ex, "_execute_llm_step") as llm, \
             patch.object(ex, "_execute_script_step") as script, \
             patch.object(ex, "_execute_validate_step") as validate, \
             patch.object(ex, "_execute_publish_step") as publish, \
             patch.object(ex, "_execute_manual_step") as manual, \
             patch.object(ex, "_execute_loop_step") as loop:
            ex._execute_step(step, Path("/tmp"))
            llm.assert_called_once_with(step, Path("/tmp"))
            script.assert_not_called()
            validate.assert_not_called()
            publish.assert_not_called()
            manual.assert_not_called()
            loop.assert_not_called()

    def test_v1_pipeline_with_type_script_falls_back_to_llm(self):
        """Even if a step declares type:script, a v1 pipeline must run it as LLM."""
        step = self._make_step(type="script", command="echo hi")
        ex = self._make_executor([step], pipeline_version=1)
        with patch.object(ex, "_execute_llm_step") as llm, \
             patch.object(ex, "_execute_script_step") as script:
            ex._execute_step(step, Path("/tmp"))
            llm.assert_called_once()
            script.assert_not_called()

    def test_v2_pipeline_with_flag_off_falls_back_to_llm(self):
        """pipeline_version=2 alone is not enough; PIPELINE_V2_ENABLED must also be on."""
        step = self._make_step(type="script", command="echo hi")
        ex = self._make_executor([step], pipeline_version=2)
        # Flag should be False by default in test harness
        self.assertFalse(self.bot_mod.PIPELINE_V2_ENABLED)
        with patch.object(ex, "_execute_llm_step") as llm, \
             patch.object(ex, "_execute_script_step") as script:
            ex._execute_step(step, Path("/tmp"))
            llm.assert_called_once()
            script.assert_not_called()

    def test_v2_pipeline_with_flag_on_dispatches_script(self):
        step = self._make_step(type="script", command="echo hi")
        ex = self._make_executor([step], pipeline_version=2)
        with patch.object(self.bot_mod, "PIPELINE_V2_ENABLED", True), \
             patch.object(ex, "_execute_llm_step") as llm, \
             patch.object(ex, "_execute_script_step") as script:
            ex._execute_step(step, Path("/tmp"))
            script.assert_called_once_with(step, Path("/tmp"))
            llm.assert_not_called()

    def test_v2_pipeline_with_flag_on_dispatches_validate(self):
        step = self._make_step(type="validate", validates="other", command="echo")
        ex = self._make_executor([step], pipeline_version=2)
        with patch.object(self.bot_mod, "PIPELINE_V2_ENABLED", True), \
             patch.object(ex, "_execute_validate_step") as validate, \
             patch.object(ex, "_execute_llm_step") as llm:
            ex._execute_step(step, Path("/tmp"))
            validate.assert_called_once_with(step, Path("/tmp"))
            llm.assert_not_called()

    def test_v2_pipeline_with_flag_on_dispatches_publish(self):
        step = self._make_step(type="publish", publishes="upstream", sink="telegram")
        ex = self._make_executor([step], pipeline_version=2)
        with patch.object(self.bot_mod, "PIPELINE_V2_ENABLED", True), \
             patch.object(ex, "_execute_publish_step") as publish, \
             patch.object(ex, "_execute_llm_step") as llm:
            ex._execute_step(step, Path("/tmp"))
            publish.assert_called_once_with(step, Path("/tmp"))
            llm.assert_not_called()

    def test_unknown_v2_type_falls_back_to_llm_with_warning(self):
        # Bypass parser by constructing PipelineStep with type="bogus" directly
        step = self._make_step(type="bogus")
        ex = self._make_executor([step], pipeline_version=2)
        with patch.object(self.bot_mod, "PIPELINE_V2_ENABLED", True), \
             patch.object(ex, "_execute_llm_step") as llm, \
             self.assertLogs("claude-bot", level="WARNING") as cm:
            ex._execute_step(step, Path("/tmp"))
            llm.assert_called_once()
            self.assertTrue(any("unknown step type" in msg.lower() for msg in cm.output))

    def test_manual_wins_over_v2_type(self):
        """A step with manual=True AND type=script must run as manual review."""
        step = self._make_step(manual=True, type="script")
        ex = self._make_executor([step], pipeline_version=2)
        with patch.object(self.bot_mod, "PIPELINE_V2_ENABLED", True), \
             patch.object(ex, "_execute_manual_step") as manual, \
             patch.object(ex, "_execute_script_step") as script, \
             patch.object(ex, "_execute_llm_step") as llm:
            ex._execute_step(step, Path("/tmp"))
            manual.assert_called_once()
            script.assert_not_called()
            llm.assert_not_called()

    def test_loop_wins_over_v2_type(self):
        """A step with loop_until set AND type=script must run via loop executor."""
        step = self._make_step(type="script", loop_until="DONE", loop_max_iterations=2)
        self.assertTrue(step.has_loop)
        ex = self._make_executor([step], pipeline_version=2)
        with patch.object(self.bot_mod, "PIPELINE_V2_ENABLED", True), \
             patch.object(ex, "_execute_loop_step") as loop, \
             patch.object(ex, "_execute_script_step") as script, \
             patch.object(ex, "_execute_llm_step") as llm:
            ex._execute_step(step, Path("/tmp"))
            loop.assert_called_once()
            script.assert_not_called()
            llm.assert_not_called()


class StubsRaiseTests(DispatcherTestBase):
    """The remaining stub (publish) raises NotImplementedError until commit 6.
    Script and validate are implemented (commits 4 and 5)."""

    def test_publish_stub_raises(self):
        step = self._make_step(type="publish")
        ex = self._make_executor([step], pipeline_version=2)
        with self.assertRaises(NotImplementedError) as cm:
            ex._execute_publish_step(step, Path("/tmp"))
        self.assertIn("commit 6", str(cm.exception))


class ValidateStepHandlerTests(DispatcherTestBase):
    """_execute_validate_step + on_failure policies + feedback retry loop."""

    def setUp(self):
        self.data_dir = Path(tempfile.mkdtemp(prefix="pv2-validate-data-"))
        self.scripts_dir = Path(tempfile.mkdtemp(prefix="pv2-validate-fixtures-"))

    def _write_script(self, name: str, body: str) -> Path:
        p = self.scripts_dir / name
        p.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
        p.chmod(0o755)
        return p

    def _seed_upstream_output(self, ex, upstream_id: str, content: str = "upstream data"):
        upstream = ex._steps_by_id[upstream_id]
        target = self.data_dir / upstream.resolved_filename
        target.write_text(content, encoding="utf-8")
        return target

    def test_no_command_fails_loud(self):
        upstream = self._make_step("writer")
        validator = self._make_step("check", type="validate", validates="writer", command="")
        ex = self._make_executor([upstream, validator], pipeline_version=2)
        self._seed_upstream_output(ex, "writer")
        ex._execute_validate_step(validator, self.data_dir)
        self.assertEqual(ex._step_status["check"], "failed")
        self.assertIn("no `command:`", ex._step_errors["check"])

    def test_no_validates_fails_loud(self):
        validator = self._make_step("check", type="validate", command="echo")
        ex = self._make_executor([validator], pipeline_version=2)
        ex._execute_validate_step(validator, self.data_dir)
        self.assertEqual(ex._step_status["check"], "failed")
        self.assertIn("no `validates:`", ex._step_errors["check"])

    def test_unknown_upstream_fails_loud(self):
        validator = self._make_step("check", type="validate", validates="bogus", command="echo")
        ex = self._make_executor([validator], pipeline_version=2)
        ex._execute_validate_step(validator, self.data_dir)
        self.assertEqual(ex._step_status["check"], "failed")
        self.assertIn("unknown upstream", ex._step_errors["check"])

    def test_target_missing_fails_loud(self):
        upstream = self._make_step("writer")
        validator = self._make_step("check", type="validate", validates="writer", command="echo")
        ex = self._make_executor([upstream, validator], pipeline_version=2)
        # don't seed the upstream output
        ex._execute_validate_step(validator, self.data_dir)
        self.assertEqual(ex._step_status["check"], "failed")
        self.assertIn("does not exist", ex._step_errors["check"])

    def test_validator_passes_step_completed(self):
        script = self._write_script(
            "pass.py",
            'print(\'{"status": "ready"}\')\n'
        )
        upstream = self._make_step("writer")
        validator = self._make_step("check", type="validate", validates="writer",
                                    command=f"python3 {script}")
        ex = self._make_executor([upstream, validator], pipeline_version=2)
        self._seed_upstream_output(ex, "writer")
        ex._execute_validate_step(validator, self.data_dir)
        self.assertEqual(ex._step_status["check"], "completed")

    def test_validator_fails_on_failure_fail(self):
        script = self._write_script(
            "fail.py",
            'print(\'{"status": "failed", "reason": "missing field X"}\')\n'
            'import sys; sys.exit(1)\n'
        )
        upstream = self._make_step("writer")
        validator = self._make_step("check", type="validate", validates="writer",
                                    on_failure="fail",
                                    command=f"python3 {script}")
        ex = self._make_executor([upstream, validator], pipeline_version=2)
        self._seed_upstream_output(ex, "writer")
        ex._execute_validate_step(validator, self.data_dir)
        self.assertEqual(ex._step_status["check"], "failed")
        self.assertIn("missing field X", ex._step_errors["check"])
        # Upstream is NOT touched (fail policy)
        self.assertEqual(ex._step_status["writer"], "pending")

    def test_validator_fails_on_failure_warn(self):
        script = self._write_script(
            "warnfail.py",
            'print(\'{"status": "failed", "reason": "minor formatting"}\')\n'
            'import sys; sys.exit(1)\n'
        )
        upstream = self._make_step("writer")
        validator = self._make_step("check", type="validate", validates="writer",
                                    on_failure="warn",
                                    command=f"python3 {script}")
        ex = self._make_executor([upstream, validator], pipeline_version=2)
        self._seed_upstream_output(ex, "writer")
        ex._execute_validate_step(validator, self.data_dir)
        # warn → step still completed so downstream proceeds
        self.assertEqual(ex._step_status["check"], "completed")
        self.assertIn("minor formatting", ex._skip_reasons["check"])

    def test_validator_feedback_triggers_upstream_rerun(self):
        """on_failure=feedback resets upstream to pending and queues feedback text."""
        script = self._write_script(
            "feedback.py",
            'print(\'{"status": "failed", "reason": "no intro paragraph", '
            '"feedback": "Add an introductory paragraph before section 1"}\')\n'
            'import sys; sys.exit(1)\n'
        )
        upstream = self._make_step("writer")
        validator = self._make_step("check", type="validate", validates="writer",
                                    on_failure="feedback",
                                    command=f"python3 {script}")
        ex = self._make_executor([upstream, validator], pipeline_version=2)
        # Mark upstream as completed (simulating it ran already)
        ex._step_status["writer"] = "completed"
        ex._step_outputs["writer"] = "upstream content"
        self._seed_upstream_output(ex, "writer")
        ex._execute_validate_step(validator, self.data_dir)
        # Upstream reset to pending (DAG loop will rerun it)
        self.assertEqual(ex._step_status["writer"], "pending")
        # Validate step also reset to pending (will rerun after upstream)
        self.assertEqual(ex._step_status["check"], "pending")
        # Feedback queued for upstream
        self.assertIn("introductory paragraph", ex._validation_feedback["writer"])
        # Retry counter incremented
        self.assertEqual(ex._validate_feedback_retries["check"], 1)

    def test_validator_feedback_retry_capped_at_one(self):
        """Second feedback failure downgrades to fail (no infinite loop)."""
        script = self._write_script(
            "always_fail.py",
            'print(\'{"status": "failed", "reason": "still bad", "feedback": "fix it"}\')\n'
            'import sys; sys.exit(1)\n'
        )
        upstream = self._make_step("writer")
        validator = self._make_step("check", type="validate", validates="writer",
                                    on_failure="feedback",
                                    command=f"python3 {script}")
        ex = self._make_executor([upstream, validator], pipeline_version=2)
        ex._step_status["writer"] = "completed"
        ex._step_outputs["writer"] = "upstream content"
        self._seed_upstream_output(ex, "writer")
        # First call: triggers retry
        ex._execute_validate_step(validator, self.data_dir)
        self.assertEqual(ex._validate_feedback_retries["check"], 1)
        # Reset state to simulate after upstream re-ran
        ex._step_status["writer"] = "completed"
        ex._step_status["check"] = "pending"
        # Second call: cap reached → fail
        ex._execute_validate_step(validator, self.data_dir)
        self.assertEqual(ex._step_status["check"], "failed")
        self.assertIn("retry already attempted", ex._step_errors["check"])


class FeedbackPromptInjectionTests(DispatcherTestBase):
    """_build_step_prompt injects validation feedback + overrides into LLM prompts."""

    def setUp(self):
        self.data_dir = Path(tempfile.mkdtemp(prefix="pv2-prompt-data-"))

    def test_no_feedback_no_overrides_v1(self):
        step = self._make_step("writer", prompt="write a post")
        ex = self._make_executor([step], pipeline_version=1)
        prompt = ex._build_step_prompt(step, self.data_dir)
        self.assertIn("write a post", prompt)
        self.assertNotIn("Validation feedback", prompt)
        self.assertNotIn("Overrides for this run", prompt)

    def test_feedback_injected_for_v2_when_flag_on(self):
        step = self._make_step("writer", prompt="write a post")
        ex = self._make_executor([step], pipeline_version=2)
        ex._validation_feedback["writer"] = "Add intro paragraph"
        with patch.object(self.bot_mod, "PIPELINE_V2_ENABLED", True):
            prompt = ex._build_step_prompt(step, self.data_dir)
        self.assertIn("Validation feedback from previous attempt", prompt)
        self.assertIn("Add intro paragraph", prompt)

    def test_overrides_injected_into_v2_prompt(self):
        step = self._make_step("writer", prompt="write a post",
                               accepts_overrides={"focus_asset": {"type": "string"}})
        ex = self._make_executor([step], pipeline_version=2)
        ex.applied_overrides = {"writer": {"focus_asset": "ETH"}}
        with patch.object(self.bot_mod, "PIPELINE_V2_ENABLED", True):
            prompt = ex._build_step_prompt(step, self.data_dir)
        self.assertIn("Overrides for this run", prompt)
        self.assertIn("focus_asset", prompt)
        self.assertIn("ETH", prompt)

    def test_overrides_not_injected_when_flag_off(self):
        step = self._make_step("writer", prompt="write a post")
        ex = self._make_executor([step], pipeline_version=2)
        ex.applied_overrides = {"writer": {"focus_asset": "ETH"}}
        # flag is off → no injection even though pipeline_version=2
        prompt = ex._build_step_prompt(step, self.data_dir)
        self.assertNotIn("Overrides for this run", prompt)


class ScriptStepHandlerTests(DispatcherTestBase):
    """_execute_script_step subprocess execution + status report parsing."""

    def setUp(self):
        # Each test gets its own data dir + temp scripts dir
        self.data_dir = Path(tempfile.mkdtemp(prefix="pv2-script-data-"))
        self.scripts_dir = Path(tempfile.mkdtemp(prefix="pv2-script-fixtures-"))

    def _write_script(self, name: str, body: str) -> Path:
        p = self.scripts_dir / name
        p.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
        p.chmod(0o755)
        return p

    def test_no_command_fails_loud(self):
        step = self._make_step("noop", type="script", command="")
        ex = self._make_executor([step], pipeline_version=2)
        ex._execute_script_step(step, self.data_dir)
        self.assertEqual(ex._step_status["noop"], "failed")
        self.assertIn("no `command:`", ex._step_errors["noop"])

    def test_script_writes_file_and_reports_ready(self):
        # Script writes the output file and prints status JSON on its last line
        script = self._write_script(
            "writer.py",
            'import os, sys\n'
            'p = os.environ["PIPELINE_STEP_OUTPUT_FILE"]\n'
            'open(p, "w").write("hello world")\n'
            'print("doing some work...")\n'
            'print(\'{"status": "ready", "output_file": "\' + p + \'"}\')\n'
        )
        step = self._make_step("writer", type="script",
                               command=f"python3 {script}",
                               output_file="writer.md")
        ex = self._make_executor([step], pipeline_version=2)
        ex._execute_script_step(step, self.data_dir)
        self.assertEqual(ex._step_status["writer"], "completed")
        self.assertEqual(ex._step_outputs["writer"], "hello world")
        # Output file persists in data_dir
        self.assertTrue((self.data_dir / "writer.md").exists())

    def test_script_fallback_ready_when_no_json(self):
        # Script writes file but doesn't print JSON status — fallback ladder
        # synthesizes ready when exit=0 + non-empty file.
        script = self._write_script(
            "no_json.py",
            'import os\n'
            'p = os.environ["PIPELINE_STEP_OUTPUT_FILE"]\n'
            'open(p, "w").write("data")\n'
            'print("just chatty stdout, no JSON")\n'
        )
        step = self._make_step("nj", type="script",
                               command=f"python3 {script}",
                               output_file="nj.md")
        ex = self._make_executor([step], pipeline_version=2)
        ex._execute_script_step(step, self.data_dir)
        self.assertEqual(ex._step_status["nj"], "completed")

    def test_script_fallback_skipped_when_no_output(self):
        # Script exits 0 but writes no file → skipped (defensive fallback)
        script = self._write_script(
            "noop.py",
            'print("nothing to do")\n'
        )
        step = self._make_step("noop2", type="script",
                               command=f"python3 {script}")
        ex = self._make_executor([step], pipeline_version=2)
        ex._execute_script_step(step, self.data_dir)
        self.assertEqual(ex._step_status["noop2"], "skipped")

    def test_script_explicit_skipped_status(self):
        script = self._write_script(
            "skip.py",
            'print(\'{"status": "skipped", "reason": "nothing matched filter"}\')\n'
        )
        step = self._make_step("skip", type="script",
                               command=f"python3 {script}")
        ex = self._make_executor([step], pipeline_version=2)
        ex._execute_script_step(step, self.data_dir)
        self.assertEqual(ex._step_status["skip"], "skipped")
        self.assertIn("nothing matched", ex._skip_reasons.get("skip", ""))

    def test_script_failure_when_exit_nonzero(self):
        script = self._write_script(
            "fail.py",
            'import sys\n'
            'sys.exit(7)\n'
        )
        step = self._make_step("fail", type="script",
                               command=f"python3 {script}")
        ex = self._make_executor([step], pipeline_version=2)
        ex._execute_script_step(step, self.data_dir)
        self.assertEqual(ex._step_status["fail"], "failed")
        self.assertIn("exit code 7", ex._step_errors["fail"])

    def test_script_explicit_failed_status(self):
        script = self._write_script(
            "boom.py",
            'print(\'{"status": "failed", "reason": "API down"}\')\n'
            'import sys; sys.exit(1)\n'
        )
        step = self._make_step("boom", type="script",
                               command=f"python3 {script}")
        ex = self._make_executor([step], pipeline_version=2)
        ex._execute_script_step(step, self.data_dir)
        self.assertEqual(ex._step_status["boom"], "failed")
        self.assertIn("API down", ex._step_errors["boom"])

    def test_script_hard_timeout_kills_process(self):
        script = self._write_script(
            "slow.py",
            'import time\n'
            'time.sleep(30)\n'
            'print(\'{"status": "ready"}\')\n'
        )
        step = self._make_step("slow", type="script",
                               command=f"python3 {script}",
                               timeout=1)
        ex = self._make_executor([step], pipeline_version=2)
        ex._execute_script_step(step, self.data_dir)
        self.assertEqual(ex._step_status["slow"], "failed")
        self.assertIn("hard timeout", ex._step_errors["slow"])

    def test_script_receives_pipeline_env_vars(self):
        # Script verifies PIPELINE_NAME, PIPELINE_STEP_ID, PIPELINE_RUN_ID,
        # STEP_DATA_DIR are all set
        script = self._write_script(
            "env_check.py",
            'import os, json\n'
            'p = os.environ["PIPELINE_STEP_OUTPUT_FILE"]\n'
            'data = {k: os.environ.get(k, "MISSING") for k in '
            '["PIPELINE_NAME", "PIPELINE_AGENT", "PIPELINE_DATA_DIR", '
            '"STEP_DATA_DIR", "PIPELINE_STEP_ID", "PIPELINE_RUN_ID"]}\n'
            'open(p, "w").write(json.dumps(data))\n'
            'print(\'{"status": "ready"}\')\n'
        )
        step = self._make_step("envcheck", type="script",
                               command=f"python3 {script}",
                               agent="main",
                               output_file="env.json")
        ex = self._make_executor([step], pipeline_version=2)
        ex._execute_script_step(step, self.data_dir)
        self.assertEqual(ex._step_status["envcheck"], "completed")
        import json as _json
        env_data = _json.loads(ex._step_outputs["envcheck"])
        self.assertEqual(env_data["PIPELINE_NAME"], "test-pipe")
        self.assertEqual(env_data["PIPELINE_STEP_ID"], "envcheck")
        self.assertEqual(env_data["STEP_DATA_DIR"], str(self.data_dir))
        # PIPELINE_DATA_DIR is the alias source (Q14)
        self.assertEqual(env_data["PIPELINE_DATA_DIR"], str(self.data_dir))
        # run_id format: timestamp-hex
        self.assertRegex(env_data["PIPELINE_RUN_ID"], r"^\d+-[0-9a-f]{6}$")

    def test_script_receives_overrides_as_env_vars(self):
        script = self._write_script(
            "ovr_check.py",
            'import os, json\n'
            'p = os.environ["PIPELINE_STEP_OUTPUT_FILE"]\n'
            'open(p, "w").write(os.environ.get("STEP_OVERRIDE_FOCUS_ASSET", "NONE"))\n'
            'print(\'{"status": "ready"}\')\n'
        )
        step = self._make_step(
            "ovrcheck", type="script",
            command=f"python3 {script}",
            accepts_overrides={"focus_asset": {"type": "string"}},
            output_file="ovr.txt",
        )
        ex = self._make_executor([step], pipeline_version=2)
        # Apply override
        ex.applied_overrides = {"ovrcheck": {"focus_asset": "ETH"}}
        ex._execute_script_step(step, self.data_dir)
        self.assertEqual(ex._step_status["ovrcheck"], "completed")
        self.assertEqual(ex._step_outputs["ovrcheck"], "ETH")

    def test_script_invalid_command_fails_loud(self):
        step = self._make_step("bogus", type="script",
                               command="/nonexistent/path/script.sh")
        ex = self._make_executor([step], pipeline_version=2)
        ex._execute_script_step(step, self.data_dir)
        self.assertEqual(ex._step_status["bogus"], "failed")
        self.assertIn("failed to spawn", ex._step_errors["bogus"])


class ParseStatusReportTests(unittest.TestCase):
    """Module-level _parse_status_report() helper."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="pv2-parsereport-"))
        cls.bot_mod = load_bot_module(tmp_home=cls.tmp)

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="pv2-parsework-"))
        self.out = self.work / "out.md"

    def test_explicit_json_ready(self):
        report = self.bot_mod._parse_status_report(
            stdout='log line\n{"status": "ready", "output_file": "/tmp/x"}',
            exit_code=0,
            output_file=self.out,
        )
        self.assertEqual(report["status"], "ready")
        self.assertEqual(report["output_file"], "/tmp/x")

    def test_fallback_ready_exit0_with_file(self):
        self.out.write_text("data")
        report = self.bot_mod._parse_status_report(
            stdout="just logs", exit_code=0, output_file=self.out,
        )
        self.assertEqual(report["status"], "ready")
        self.assertEqual(report["output_file"], str(self.out))

    def test_fallback_skipped_exit0_no_file(self):
        report = self.bot_mod._parse_status_report(
            stdout="nothing", exit_code=0, output_file=self.out,
        )
        self.assertEqual(report["status"], "skipped")

    def test_fallback_failed_nonzero_exit(self):
        report = self.bot_mod._parse_status_report(
            stdout="error", exit_code=2, output_file=self.out,
        )
        self.assertEqual(report["status"], "failed")
        self.assertIn("exit code 2", report["reason"])

    def test_explicit_failed_overrides_exit0(self):
        report = self.bot_mod._parse_status_report(
            stdout='{"status": "failed", "reason": "validation error"}',
            exit_code=0,
            output_file=self.out,
        )
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["reason"], "validation error")

    def test_invalid_json_falls_through_to_ladder(self):
        self.out.write_text("data")
        report = self.bot_mod._parse_status_report(
            stdout="not-json{{{", exit_code=0, output_file=self.out,
        )
        self.assertEqual(report["status"], "ready")  # fallback to file-based ready


if __name__ == "__main__":
    unittest.main()
