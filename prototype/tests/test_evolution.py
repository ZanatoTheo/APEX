import dataclasses
import json
import random
import re
import tempfile
import unittest
from pathlib import Path

from apex import config, evaluation, evolution
from apex.evaluation import PublicResult, clopper_pearson, l1_components, l1_ppm
from apex.evolution import UCB1, PatchError, apply_axiom_edit, apply_json_patch
from apex.ledger import verify

PROTO = Path(__file__).resolve().parent.parent
GENESIS_ACTIONS = {"config", "gate_definition", "public_manifest", "holdout_manifest", "rng_seed"}


class JsonPatchTest(unittest.TestCase):
    DOC = {"max_steps": 12, "nodes": [{"id": "a"}, {"id": "b"}]}

    def test_add_remove_replace(self):
        out = apply_json_patch(self.DOC, [{"op": "replace", "path": "/max_steps", "value": 14},
                                          {"op": "add", "path": "/nodes/-", "value": {"id": "c"}},
                                          {"op": "add", "path": "/nodes/0", "value": {"id": "z"}},
                                          {"op": "remove", "path": "/nodes/1"},
                                          {"op": "add", "path": "/extra~1key", "value": 1}])
        self.assertEqual(out, {"max_steps": 14, "nodes": [{"id": "z"}, {"id": "b"}, {"id": "c"}], "extra/key": 1})
        self.assertEqual(self.DOC["max_steps"], 12)   # input untouched

    def test_errors(self):
        for ops in ([{"op": "move", "from": "/a", "path": "/b"}], [{"op": "replace", "path": "/nope", "value": 1}],
                    [{"op": "remove", "path": "/nodes/5"}], [{"op": "add", "path": "nodes", "value": 1}],
                    [{"op": "replace", "path": "/max_steps"}], [{"op": "replace", "path": "/nodes/01", "value": 1}],
                    [{"op": "add", "path": "/max_steps/x", "value": 1}], ["not an object"]):
            with self.assertRaises(PatchError, msg=ops):
                apply_json_patch(self.DOC, ops)


class AxiomEditTest(unittest.TestCase):
    def test_ops_and_bounds(self):
        self.assertEqual(apply_axiom_edit(["a", "b"], [{"op": "add", "index": 2, "text": "c"},
                                                       {"op": "replace", "index": 0, "text": "A"},
                                                       {"op": "remove", "index": 1}]), ["A", "c"])
        for ops in ([{"op": "add", "index": 3, "text": "x"}], [{"op": "replace", "index": 2, "text": "x"}],
                    [{"op": "remove", "index": -1}], [{"op": "add", "index": 0}], [{"op": "swap", "index": 0}],
                    [{"op": "remove", "index": True}]):
            with self.assertRaises(PatchError, msg=ops):
                apply_axiom_edit(["a", "b"], ops)


class UCB1Test(unittest.TestCase):
    def test_unvisited_first_then_spread_within_a_call(self):
        ucb = UCB1(1_414_214)
        self.assertEqual(ucb.pick(3, ["L2", "L1", "L0"]), ["L0", "L1", "L2"])

    def test_credit_and_exploitation(self):
        ucb = UCB1(1_414_214)
        for _ in range(5):
            ucb.credit("good", 900_000)
            ucb.credit("bad", 100_000)
        self.assertEqual(ucb.pick(1, ["bad", "good"]), ["good"])
        self.assertEqual(ucb.pick(1, ["bad", "good", "new"]), ["new"])   # unvisited still first

    def test_redraw_excludes_the_failed_lineage(self):
        ucb = UCB1(1_414_214)
        self.assertEqual(ucb.pick(1, ["L0", "L1"], exclude=["L0"]), ["L1"])
        self.assertEqual(ucb.pick(1, ["L0"], exclude=["L0"]), ["L0"])   # only arm left: allowed

    def test_score_formula(self):
        ucb = UCB1(1_414_214)
        ucb.credit("A", 500_000)
        ucb.credit("B", 1_000_000)
        ucb.credit("B", 0)
        import math
        self.assertAlmostEqual(ucb.score("A", {}), 0.5 + 1.414214 * math.sqrt(math.log(3) / 1), places=5)


class BudgetTest(unittest.TestCase):
    def test_in_flight_reservations_protect_the_holdout_reserve(self):
        from apex.models import Budget, BudgetExceeded
        b = Budget(1000, 400)
        b.reserve(500)                      # a call in flight
        with self.assertRaises(BudgetExceeded):
            b.reserve(200)                  # would overshoot 1000 − 400 while the first call runs
        b.settle(500, 120)
        self.assertEqual((b.spent, b.reserved, b.available), (120, 0, 480))
        b.holdout_phase = True
        self.assertEqual(b.available, 880)


class ScoringTest(unittest.TestCase):
    def test_clopper_pearson_reference_values(self):
        for (k, n), (lo, hi) in {(0, 10): (0.0, 0.3085), (10, 10): (0.6915, 1.0), (5, 10): (0.1871, 0.8129)}.items():
            got = clopper_pearson(k, n)
            self.assertAlmostEqual(got[0], lo, delta=0.0005, msg=(k, n))
            self.assertAlmostEqual(got[1], hi, delta=0.0005, msg=(k, n))
        self.assertEqual(clopper_pearson(0, 0), (0.0, 1.0))

    def test_l1_formula(self):
        w = {"pass_rate": 700_000, "tokens": 200_000, "latency": 100_000}
        c = l1_components(500_000, 5000, 10000, 30_000, 60)
        self.assertEqual(c, {"pass_rate": 500_000, "token_term": 500_000, "latency_term": 500_000})
        self.assertEqual(l1_ppm(c, w), 500_000)
        self.assertEqual(l1_components(1_000_000, 99999, 10, 10**9, 1)["token_term"], 0)   # clamped

    def test_public_result_has_no_hidden_field(self):
        names = {f.name for f in dataclasses.fields(PublicResult)} | {f.name for f in dataclasses.fields(evaluation.TaskPublic)}
        self.assertFalse(any("hidden" in n for n in names), names)


class IsolationTest(unittest.TestCase):
    def test_only_evaluation_reads_the_holdout(self):
        for path in (PROTO / "apex").glob("*.py"):
            text = path.read_text()
            if path.name in ("evaluation.py", "config.py"):
                continue
            self.assertNotIn("hidden_tests", text, path.name)
            self.assertNotIn("holdout_blobs.get", text, path.name)
        code_refs = re.compile(r"holdout_blobs|holdout_dir|hidden_tests|hidden_ref|hidden_fitness|\bhidden\[")
        evo = (PROTO / "apex" / "evolution.py").read_text()
        selection = evo[evo.index("ranked = sorted"):evo.index("fitness = {")]
        self.assertNotRegex(selection, code_refs)
        mutation = evo[evo.index("def pick_trace"):evo.index("# -- the run")]
        self.assertNotRegex(mutation, code_refs)


class LoopTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name) / "run"

    def tearDown(self):
        self._tmp.cleanup()

    def test_small_run_verifies_and_cites_traces(self):
        cfg = config.load(overrides={"run": {"seed": 7, "g_max": 2}, "population": {"P": 3, "mu": 2},
                                     "batch": {"K": 2}})
        summary = evolution.run(cfg, self.run_dir, log=lambda *_: None)
        self.assertEqual(verify(self.run_dir, required_genesis_actions=GENESIS_ACTIONS), [])
        self.assertEqual(len(summary["generations"]), 2)
        self.assertEqual(len(summary["final_survivors"]), 2)
        self.assertEqual(len(summary["heldout_refs"]), 2 * 4)
        from apex.ledger import Ledger
        ledger = Ledger(self.run_dir)
        try:
            blocks = {b["block_hash"]: b for b in ledger.blocks()}
            proposals = [ledger.blobs.get(t["result_hash"]) for b in blocks.values()
                         if b["kind"] == "generation_event" for t in b["state_transitions"]
                         if t["action"] == "mutation_proposal"]
            later = [p for p in proposals if p["attribution"]["step_identifier"] == "eval:public"]
            self.assertTrue(later)
            for p in later:   # design §16: the evidence link must appear in the cited block
                cited = blocks[p["attribution"]["block_hash"]]
                self.assertIn(p["attribution"]["empirical_evidence_link"],
                              [t["result_hash"] for t in cited["state_transitions"]])
        finally:
            ledger.close()

    def test_all_seeds_fail_l0_stops_the_run(self):
        cfg = config.load(overrides={"run": {"g_max": 2}, "population": {"P": 2, "mu": 1}, "batch": {"K": 1},
                                     "limits": {"token_budget": 50}})
        summary = evolution.run(cfg, self.run_dir, log=lambda *_: None)
        self.assertEqual(summary["stop_reason"], "all generation-0 seeds failed L0")
        self.assertEqual(summary["final_survivors"], [])
        self.assertEqual(verify(self.run_dir, required_genesis_actions=GENESIS_ACTIONS), [])

    def test_same_seed_same_seeding_batches_and_gen0_scores(self):
        """The seed fixes batches, generation 0 and every model reply. Later selection can differ between runs
        because L1's latency term and the hash tie-break use wall-clock values (README "Determinism")."""
        cfg = config.load(overrides={"run": {"seed": 3, "g_max": 2}, "population": {"P": 3, "mu": 2},
                                     "batch": {"K": 2}})
        a = evolution.run(cfg, self.run_dir / "a", log=lambda *_: None)
        b = evolution.run(cfg, self.run_dir / "b", log=lambda *_: None)
        gen0 = lambda s: {k: (v["axioms"], v["pass_ppm"], v["tokens"], v["l0"]) for k, v in s["generations"][0]["results"].items()}
        self.assertEqual(gen0(a), gen0(b))
        self.assertEqual([g["batch"] for g in a["generations"]], [g["batch"] for g in b["generations"]])


if __name__ == "__main__":
    unittest.main()
