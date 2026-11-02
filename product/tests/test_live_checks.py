"""tools/live_checks.py: the key check and the step commands. Nothing here starts a subprocess or a network call."""
import importlib.util
import os
import unittest
from pathlib import Path
from unittest import mock

_PATH = Path(__file__).resolve().parent.parent / "tools" / "live_checks.py"
_spec = importlib.util.spec_from_file_location("live_checks", _PATH)
live_checks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(live_checks)


class LiveChecksTest(unittest.TestCase):
    def test_key_problem(self):
        for env in ({}, {"MODEL_API_KEY": ""}, {"MODEL_API_KEY": "banana"}, {"MODEL_API_KEY": " banana\r"}):
            with self.subTest(env=env):
                self.assertIn("MODEL_API_KEY", live_checks.key_problem(env))
        self.assertIsNone(live_checks.key_problem({"MODEL_API_KEY": "sk-real"}))

    def test_contract_step_sets_the_config_only_for_its_command(self):
        (argv, extra), = live_checks.plan("contract", "configs/meta.json", "v1-meta-1")
        self.assertEqual(argv[1:], ["-m", "unittest", "tests.test_llm_contract", "-v"])
        self.assertEqual(extra, {"APEX_LLM_CONFIG": "configs/meta.json"})

    def test_run_step_runs_then_verifies(self):
        cmds = [argv[1:] for argv, _ in live_checks.plan("run", "c.json", "r1")]
        self.assertEqual(cmds, [["run.py", "run", "--config", "c.json", "--run-id", "r1"],
                                ["run.py", "verify", "runs/r1"]])

    def test_steps_needing_a_key_refuse_the_placeholder(self):
        with mock.patch.object(live_checks.subprocess, "run") as run, \
                mock.patch.object(live_checks.envfile, "load"):
            for step in ("models", "contract", "probe", "run"):
                with self.subTest(step=step), mock.patch.dict(os.environ, {"MODEL_API_KEY": "banana"}):
                    self.assertEqual(live_checks.main([step]), 2)
            run.assert_not_called()

    def test_offline_steps_need_no_key(self):
        with mock.patch.object(live_checks.subprocess, "run", return_value=mock.Mock(returncode=0)) as run, \
                mock.patch.object(live_checks.envfile, "load"), mock.patch.dict(os.environ, {"MODEL_API_KEY": ""}):
            self.assertEqual(live_checks.main(["estimate"]), 0)
            self.assertEqual(live_checks.main(["stats"]), 0)
        self.assertEqual(run.call_count, 2)

    def test_unknown_step(self):
        with mock.patch.object(live_checks.subprocess, "run") as run, mock.patch.object(live_checks.envfile, "load"):
            self.assertEqual(live_checks.main(["nope"]), 2)
            self.assertEqual(live_checks.main([]), 2)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
