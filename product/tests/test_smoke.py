"""End-to-end through the CLI (CODE_STRUCTURE §6.6): a short run, verify, report, tamper, and the llm stub."""
import contextlib
import importlib.util
import io
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import run as cli
from apex import config, corpus

HAS_LLM_SERVICE = importlib.util.find_spec("apex.llm_service") is not None


def call(*argv) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(list(argv))
        except SystemExit as e:   # an argparse error must fail one test, not stop the whole run
            code = e.code if isinstance(e.code, int) else 2
    return code, out.getvalue(), err.getvalue()


class SmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.runs = Path(cls._tmp.name)
        cls.code, cls.out, cls.err = call("run", "--seed", "11", "--g-max", "2", "--run-id", "smoke",
                                          "--runs-dir", str(cls.runs))
        cls.run_dir = cls.runs / "smoke"

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_1_run_succeeds_and_verifies(self):
        self.assertEqual(self.code, 0, self.out + self.err)
        self.assertIn("verify: OK", self.out)
        self.assertEqual(call("verify", str(self.run_dir))[:2], (0, "OK\n"))

    def test_2_report_has_generations_survivors_and_intervals(self):
        text = (self.run_dir / "report.md").read_text()
        for needle in ("## Generations", "| 1 |", "## Final survivors", "## Held-out tasks", "Clopper–Pearson",
                       "## Published heads", "Ledger verification: **OK**"):
            self.assertIn(needle, text)

    def test_3_tampered_ledger_fails(self):
        db = sqlite3.connect(self.run_dir / "ledger.sqlite")
        h, body = db.execute("SELECT block_hash, body FROM blocks WHERE kind='generation_event' LIMIT 1").fetchone()
        db.execute("UPDATE blocks SET body=? WHERE block_hash=?", (body.replace('"batch"', '"BATCH"', 1), h))
        db.commit()
        db.close()
        code, out, _ = call("verify", str(self.run_dir))
        self.assertEqual(code, 1)
        self.assertIn("hash mismatch", out)

    def test_5_report_and_config_errors_are_clean(self):
        self.assertEqual(call("report", str(self.runs / "missing"))[0], 2)
        bad = self.runs / "list.json"
        bad.write_text("[1, 2]")
        code, _, err = call("run", "--config", str(bad), "--run-id", "x", "--runs-dir", str(self.runs))
        self.assertEqual(code, 2)
        self.assertIn("must be a JSON object", err)

    @unittest.skipIf(HAS_LLM_SERVICE, "llm_service.py exists")
    def test_4_llm_model_without_service_exits_cleanly(self):
        code, _, err = call("run", "--model", "llm", "--run-id", "llm", "--runs-dir", str(self.runs))
        self.assertEqual(code, 2)
        self.assertIn("llm_service.py is missing", err)
        self.assertFalse((self.runs / "llm").exists())


class ProbeTest(unittest.TestCase):
    """`run.py probe` with the fake model: the baseline once on every public task."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.runs = Path(cls._tmp.name)
        cls.tasks = corpus.load_public(config.resolve_path(config.load(), "corpus"))
        cls.code, cls.out, cls.err = call("probe", "--run-id", "p", "--runs-dir", str(cls.runs))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_runs_every_public_task_once_and_verifies(self):
        self.assertEqual(self.code, 0, self.out + self.err)
        self.assertIn("verify: OK", self.out)
        self.assertEqual(call("verify", str(self.runs / "p"))[:2], (0, "OK\n"))
        self.assertTrue((self.runs / "p" / "report.md").is_file())
        rows = [line.split() for line in self.out.splitlines() if line.split()[:1] == ["g0-a000"]]
        self.assertEqual(sorted(r[1] for r in rows), sorted(t.id for t in self.tasks))   # task column, exact

    def test_prints_totals(self):
        self.assertIn("task runs", self.out)

    def test_never_runs_the_held_out_tasks(self):
        """design §9.1: held-out tasks are run once, by final survivors; a probe that can be rerun must not."""
        self.assertIn("held-out: not run by probe", self.out)
        db = sqlite3.connect(self.runs / "p" / "ledger.sqlite")
        bodies = [b for (b,) in db.execute("SELECT body FROM blocks WHERE kind='generation_event'")]
        db.close()
        self.assertFalse([b for b in bodies if '"heldout_run"' in b])

    def test_aborted_probe_fails_loudly(self):
        from apex import evaluation
        with mock.patch.object(evaluation, "evaluate_task", side_effect=evaluation.InfraError("HTTP 429")):
            code, out, err = call("probe", "--run-id", "aborted", "--runs-dir", str(self.runs))
        self.assertEqual(code, 1)
        self.assertIn("probe failed", err)
        self.assertIn("aborted", err)
        self.assertNotIn("task runs", out)

    def test_missing_agent_file(self):
        code, _, err = call("probe", "--agent", "nope.json", "--run-id", "q", "--runs-dir", str(self.runs))
        self.assertEqual(code, 2)
        self.assertIn("nope.json", err)
        self.assertFalse((self.runs / "q").exists())


class ModelsCommandTest(unittest.TestCase):
    """Never reaches api.meta.ai: the key is removed (even if the shell exported a real one) or the stub is used."""

    def setUp(self):
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        for name in ("MODEL_API_KEY", "APEX_LLM_CONFIG"):
            os.environ.pop(name, None)

    def test_models_without_key_exits_cleanly(self):
        code, _, err = call("models")
        self.assertEqual(code, 2)
        self.assertIn("MODEL_API_KEY", err)

    def test_main_does_not_load_dotenv(self):
        """Only `python3 run.py …` loads product/.env; tests calling main() stay offline."""
        with mock.patch("apex.envfile.load") as load:
            call("models")
        load.assert_not_called()

    def test_models_lists_ids_and_pin_status(self):
        from tests.test_llm_service import StubAPI
        stub = StubAPI()
        self.addCleanup(stub.close)
        stub.body = {"data": [{"id": "muse-spark-1.3"}, {"id": "muse-code-9"}]}
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "c.json"
            cfg.write_text(json.dumps({"models": {"base_url": stub.url, "subagent": {"model_id": "muse-spark-1.3"},
                                                  "mutation": {"model_id": "muse-code-1"}}}))
            os.environ["MODEL_API_KEY"] = "sk-test-local"
            code, out, err = call("models", "--config", str(cfg))
        self.assertEqual(code, 0, err)
        self.assertIn("  muse-code-9\n  muse-spark-1.3\n", out)
        self.assertIn("pinned subagent: muse-spark-1.3 (listed)", out)
        self.assertIn("pinned mutation: muse-code-1 (NOT listed)", out)


if __name__ == "__main__":
    unittest.main()
