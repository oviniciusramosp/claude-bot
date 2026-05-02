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
    """The stub handlers raise NotImplementedError so v2 opt-in is fail-loud."""

    def test_script_stub_raises(self):
        step = self._make_step(type="script")
        ex = self._make_executor([step], pipeline_version=2)
        with self.assertRaises(NotImplementedError) as cm:
            ex._execute_script_step(step, Path("/tmp"))
        self.assertIn("commit 4", str(cm.exception))

    def test_validate_stub_raises(self):
        step = self._make_step(type="validate")
        ex = self._make_executor([step], pipeline_version=2)
        with self.assertRaises(NotImplementedError) as cm:
            ex._execute_validate_step(step, Path("/tmp"))
        self.assertIn("commit 5", str(cm.exception))

    def test_publish_stub_raises(self):
        step = self._make_step(type="publish")
        ex = self._make_executor([step], pipeline_version=2)
        with self.assertRaises(NotImplementedError) as cm:
            ex._execute_publish_step(step, Path("/tmp"))
        self.assertIn("commit 6", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
