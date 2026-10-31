"""End-to-end through the CLI (CODE_STRUCTURE §6.6): a short run, verify, report, tamper, and the llm stub."""
import contextlib
import importlib.util
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path

import run as cli

HAS_LLM_SERVICE = importlib.util.find_spec("apex.llm_service") is not None


def call(*argv) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
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


if __name__ == "__main__":
    unittest.main()
