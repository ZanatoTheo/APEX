import copy
import json
import tempfile
import unittest
from pathlib import Path

from apex import config, corpus
from apex.agent import Agent, GraphError, run_agent, validate_axioms, validate_graph
from apex.fake_model import SKILL_AXIOMS
from apex.ledger import BlobStore
from apex.models import Budget, ModelClient, load_service
from apex.sandbox import Limits, Workspace

PROTO = Path(__file__).resolve().parent.parent
SEED = json.loads((PROTO / "seeds" / "baseline.json").read_text())
TASK = corpus.load_task(PROTO / "corpus" / "public" / "obo_window_sum")


class GraphValidationTest(unittest.TestCase):
    def test_baseline_is_valid(self):
        validate_graph(SEED["graph"], len(SEED["axioms"]))
        validate_axioms(SEED["axioms"], 8, 300)

    def broken(self, mutate):
        g = copy.deepcopy(SEED["graph"])
        mutate(g)
        with self.assertRaises(GraphError):
            validate_graph(g, len(SEED["axioms"]))

    def test_rejects_bad_graphs(self):
        self.broken(lambda g: g["nodes"].append(dict(g["nodes"][0])))                     # duplicate id
        self.broken(lambda g: g["nodes"][0]["transitions"].append({"on": "x", "to": "nowhere"}))
        self.broken(lambda g: g["nodes"][1].update(tool="rm_rf"))                          # unknown tool
        self.broken(lambda g: g["nodes"][1]["transitions"].append({"on": "applied", "to": "plan"}))
        self.broken(lambda g: g.update(start="ghost"))
        self.broken(lambda g: g.update(max_steps=0))
        self.broken(lambda g: g["nodes"][0].update(axiom_refs=[7]))

    def test_rejects_unreachable_terminal(self):
        def cut(g):
            g["nodes"][0]["transitions"] = [{"on": "read_file", "to": "read"}]
            g["nodes"][1]["transitions"] = [{"on": "ok", "to": "plan"}]
        self.broken(cut)

    def test_rejects_bad_axioms(self):
        for bad in ([], ["x"] * 9, ["two\nlines"], ["y" * 301], [3]):
            with self.assertRaises(GraphError):
                validate_axioms(bad, 8, 300)


class RuntimeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.cfg = config.load()
        self.blobs = BlobStore(tmp / "blobs")
        self.client = ModelClient(load_service(self.cfg), self.cfg, self.blobs, Budget(10**7, 0))
        self.work = tmp / "work"

    def tearDown(self):
        self._tmp.cleanup()

    def run_with(self, axioms, graph=None):
        agent = Agent("a0", "L0", None, 0, graph or SEED["graph"], axioms)
        with Workspace.for_task(TASK, self.work, Limits(timeout_s=20)) as ws:
            result = run_agent(agent, TASK, self.client, ws, self.blobs, token_budget=8000, timeout_s=60)
            fixed = ws.run_tests().status == "pass"
        return result, fixed

    def test_skilled_agent_fixes_and_baseline_does_not(self):
        skilled, skilled_fixed = self.run_with(SEED["axioms"] + [SKILL_AXIOMS["off_by_one"]])
        base, base_fixed = self.run_with(SEED["axioms"])
        self.assertTrue(skilled_fixed, skilled)
        self.assertFalse(base_fixed, base)
        self.assertEqual(skilled.outcome, "terminal:done")
        self.assertIn("range(len(xs) - k + 1)", skilled.patch)

    def test_every_transition_has_a_stored_result(self):
        result, _ = self.run_with(SEED["axioms"])
        actions = [t["action"] for t in result.transitions]
        self.assertEqual(actions[:2], ["llm:plan", "tool:read_file"])
        self.assertEqual(actions[-1], "end")
        for t in result.transitions:
            self.assertTrue(self.blobs.has(t["result_hash"]), t)
            self.assertEqual(t["agent_id"], "a0")
        self.assertGreater(result.tokens, 0)

    def test_max_steps(self):
        g = copy.deepcopy(SEED["graph"])
        g["max_steps"] = 1
        result, _ = self.run_with(SEED["axioms"], g)
        self.assertEqual(result.outcome, "max_steps")
        self.assertEqual(result.steps, 1)

    def test_llm_node_without_error_edge_retries_and_llm_chain_gets_user_turns(self):
        class Scripted:
            def __init__(self):
                self.seen = []

            def complete(self, role, messages, max_tokens):
                self.seen.append(messages)
                text = ["not json", '{"outcome": "next", "args": {}}', '{"outcome": "stop", "args": {}}'][len(self.seen) - 1]
                return {"text": text, "model_id": "fake-subagent-1", "usage": {"input_tokens": 1, "output_tokens": 1}}
        g = {"graph_version": "1", "start": "a", "max_steps": 6, "nodes": [
            {"id": "a", "kind": "llm", "transitions": [{"on": "next", "to": "b"}]},
            {"id": "b", "kind": "llm", "transitions": [{"on": "stop", "to": "done"}]},
            {"id": "done", "kind": "terminal", "transitions": []}]}
        validate_graph(g, 1)
        service = Scripted()
        client = ModelClient(service, self.cfg, self.blobs, Budget(10**7, 0))
        agent = Agent("a0", "L0", None, 0, g, ["Think."])
        with Workspace.for_task(TASK, self.work) as ws:
            result = run_agent(agent, TASK, client, ws, self.blobs, token_budget=8000, timeout_s=60)
        self.assertEqual(result.outcome, "terminal:done")
        self.assertEqual([t["outcome"] for t in result.transitions[:3]], ["error", "next", "stop"])
        for messages in service.seen:
            self.assertEqual(messages[-1]["role"], "user")

    def test_token_budget_stops_the_run(self):
        agent = Agent("a0", "L0", None, 0, SEED["graph"], SEED["axioms"])
        with Workspace.for_task(TASK, self.work) as ws:
            result = run_agent(agent, TASK, self.client, ws, self.blobs, token_budget=10, timeout_s=60)
        self.assertEqual(result.outcome, "token_budget")


if __name__ == "__main__":
    unittest.main()
