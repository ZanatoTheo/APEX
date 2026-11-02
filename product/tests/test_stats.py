"""apex/stats.py: per-task rows and a run summary read from the public ledger (never the holdout)."""
import collections
import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from apex import config, evolution, stats
from apex.ledger import BlobStore

STATS_SRC = Path(stats.__file__).read_text(encoding="utf-8")


class StatsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.run_dir = Path(cls._tmp.name) / "r"
        cfg = config.load(overrides={"population": {"P": 2, "mu": 1}, "batch": {"K": 2}, "run": {"g_max": 2, "seed": 7}})
        evolution.run(cfg, cls.run_dir, log=lambda *a: None)
        db = sqlite3.connect(cls.run_dir / "ledger.sqlite")
        cls.blocks = {kind: [json.loads(body) for (body,) in db.execute(
            "SELECT body FROM blocks WHERE kind=? ORDER BY lamport_clock", (kind,))]
            for kind in ("agent_run", "generation_event")}
        db.close()
        cls.blobs = BlobStore(cls.run_dir / "blobs", create=False)
        cls.rows = stats.task_rows(cls.run_dir)
        cls.summary = stats.run_summary(cls.run_dir)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def blob_of(self, block, action):
        return self.blobs.get(next(t["result_hash"] for t in block["state_transitions"] if t["action"] == action))

    def test_one_row_per_agent_run_matching_its_blobs(self):
        self.assertEqual(len(self.rows), len(self.blocks["agent_run"]))
        self.assertGreater(len(self.rows), 0)
        for row, block in zip(self.rows, self.blocks["agent_run"]):
            end, public = self.blob_of(block, "end"), self.blob_of(block, "eval:public")
            llm = [t for t in block["state_transitions"] if t["action"].startswith("llm:")]
            self.assertEqual(row["agent_id"], block["state_transitions"][0]["agent_id"])
            self.assertEqual(row["task_id"], end["task_id"])
            self.assertEqual((row["outcome"], row["steps"], row["tokens"], row["latency_ms"]),
                             (end["outcome"], end["steps"], end["tokens"], end["latency_ms"]))
            self.assertEqual((row["passed"], row["total"], row["l0_failures"]),
                             (public["passed"], public["total"], public["l0_failures"]))
            self.assertEqual(row["llm_steps"], len(llm))
            self.assertEqual(row["parse_errors"], sum(t["outcome"] == "error" for t in llm))

    def test_summary_adds_up_from_the_rows(self):
        s, rows = self.summary, self.rows
        self.assertEqual(s["task_runs"], len(rows))
        self.assertEqual(s["tasks_passed"], sum(r["total"] > 0 and r["passed"] == r["total"] for r in rows))
        self.assertEqual((s["public_passed"], s["public_total"]),
                         (sum(r["passed"] for r in rows), sum(r["total"] for r in rows)))
        self.assertEqual((s["llm_steps"], s["parse_errors"]),
                         (sum(r["llm_steps"] for r in rows), sum(r["parse_errors"] for r in rows)))
        self.assertEqual(s["tokens_task_runs"], sum(r["tokens"] for r in rows))
        self.assertEqual(s["outcomes"], dict(collections.Counter(r["outcome"] for r in rows)))
        self.assertEqual(s["l0_failed_runs"], sum(bool(r["l0_failures"]) for r in rows))

    def test_summary_counts_mutation_proposals(self):
        props = [self.blobs.get(t["result_hash"]) for b in self.blocks["generation_event"]
                 for t in b["state_transitions"] if t["action"] == "mutation_proposal"]
        self.assertGreater(len(props), 0)
        self.assertEqual(self.summary["proposals"], len(props))
        self.assertEqual(self.summary["accepted"], sum(p["accepted"] for p in props))
        self.assertEqual(self.summary["mutation_calls"], sum(len(p["model_calls"]) for p in props))

    def test_tokens_per_generation_from_the_summary_file(self):
        gens = json.loads((self.run_dir / "summary.json").read_text())["generations"]
        spent = [g["tokens_spent"] for g in gens]
        self.assertEqual(self.summary["tokens_per_generation"], [b - a for a, b in zip([0] + spent, spent)])

    def test_never_reads_the_holdout(self):
        self.assertNotIn("holdout", STATS_SRC)
        read = []
        real_bytes, real_text = Path.read_bytes, Path.read_text

        def spy_bytes(path, *a, **k):
            read.append(str(path))
            return real_bytes(path, *a, **k)

        def spy_text(path, *a, **k):
            read.append(str(path))
            return real_text(path, *a, **k)
        with mock.patch.object(Path, "read_bytes", spy_bytes), mock.patch.object(Path, "read_text", spy_text), \
                mock.patch.object(sqlite3, "connect", wraps=sqlite3.connect) as connect:
            stats.task_rows(self.run_dir)
            stats.run_summary(self.run_dir)
        self.assertTrue(read)
        opened = read + [str(c.args[0]) for c in connect.call_args_list]
        self.assertFalse([p for p in opened if "holdout" in p], opened)
        self.assertTrue(all(p.endswith("ledger.sqlite?mode=ro") for p in map(str, (c.args[0] for c in
                                                                                     connect.call_args_list))))
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "r"
            shutil.copytree(self.run_dir, copy, ignore=shutil.ignore_patterns("blobs-holdout"))
            self.assertEqual(stats.task_rows(copy), self.rows)
            self.assertEqual(stats.run_summary(copy), self.summary)

    def test_damaged_block_gives_a_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "r"
            shutil.copytree(self.run_dir, copy)
            db = sqlite3.connect(copy / "ledger.sqlite")
            h, body = db.execute("SELECT block_hash, body FROM blocks WHERE kind='agent_run' LIMIT 1").fetchone()
            db.execute("UPDATE blocks SET body=? WHERE block_hash=?", (body.replace('"action":"end"', '"action":"x"'), h))
            db.commit()
            db.close()
            with self.assertRaises(stats.StatsError) as ctx:
                stats.task_rows(copy)
            self.assertIn(h[:12], str(ctx.exception))

    def test_read_only(self):
        before = sorted(p.relative_to(self.run_dir) for p in self.run_dir.rglob("*"))
        stats.task_rows(self.run_dir)
        stats.run_summary(self.run_dir)
        self.assertEqual(sorted(p.relative_to(self.run_dir) for p in self.run_dir.rglob("*")), before)

    def test_formatting(self):
        text = stats.format_rows(self.rows)
        self.assertIn("task", text.splitlines()[0])
        for r in self.rows:
            self.assertIn(r["task_id"], text)
        self.assertEqual(len(text.strip().splitlines()), len(self.rows) + 2)   # header + rule + rows
        summary = stats.format_summary(self.summary)
        for needle in ("task runs", "parse errors", "tokens", "mutation"):
            self.assertIn(needle, summary)


if __name__ == "__main__":
    unittest.main()
