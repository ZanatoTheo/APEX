"""The operation loop, run log and CLI. Fake models only: no real API call."""
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from apex import config
from apex.agent import DATA_HEADER
from apex.budget import CycleBudget
from apex.connector import ConnectorError, cycle_steps, target_score
from apex.fake_run import demo_model
from apex.operation import Operation, loop_scores, split_cycles
from apex.orchestrator import Orchestrator
from apex.selection import parent_penalty, select
from tests.fixtures.toy_connector import SECRET, ToyConnector

ROOT = Path(__file__).resolve().parent.parent
FINAL = "Current agents, best loop score first"      # a phrase only the final prompt holds


@pytest.fixture
def cfg():
    return config.load()


class RecToy(ToyConnector):
    """The toy, recording what the core asks of it."""

    def __init__(self, cfg=None, data=None):
        super().__init__(cfg, data)
        self.released, self.begun, self.loop = [], [], 0

    def release(self, step):
        if step == 0:
            self.loop += 1
        self.released.append(step)
        super().release(step)

    def begin_cycle(self, agent_ids):
        self.begun.append(list(agent_ids))
        super().begin_cycle(agent_ids)


class TwoStepToy(RecToy):
    def steps_per_cycle(self):
        return 2


def events(run_dir, kind=None):
    rows = [json.loads(line) for line in (Path(run_dir) / "log.jsonl").read_text().splitlines()]
    return [r for r in rows if kind is None or r["event"] == kind]


def run_op(cfg, tmp_path, conn=None, model=None, loops=2, **kw):
    cfg["operation"]["max_loops"] = loops
    conn = conn or RecToy(cfg)
    model = model or demo_model(cfg)
    op = Operation(cfg, conn, model, tmp_path / "run", **kw)
    return op, conn, model, op.run()


# ---- 1-2: cycles and the optional connector methods ------------------------------------------------------------
def test_split_cycles():
    lens = lambda n, k: [len(c) for c in split_cycles(n, k)]
    assert split_cycles(8, 4) == [[0, 1, 2, 3], [4, 5, 6, 7]]
    assert lens(9, 4) == [4, 5]
    assert lens(10, 4) == [4, 4, 2]
    assert lens(53, 4) == [4] * 12 + [5]
    assert lens(183, 14) == [14] * 12 + [15]
    assert lens(3, 4) == [3]
    assert lens(1, 1) == [1]
    assert [s for c in split_cycles(183, 14) for s in c] == list(range(183))


def test_cycle_steps(cfg):
    assert cycle_steps(ToyConnector(cfg), cfg) == 4
    assert cycle_steps(TwoStepToy(cfg), cfg) == 2
    for bad in (0, -1, True, 2.5, "3"):
        conn = ToyConnector(cfg)
        conn.steps_per_cycle = lambda v=bad: v
        with pytest.raises(ConnectorError):
            cycle_steps(conn, cfg)
    conn = ToyConnector(cfg)
    conn.steps_per_cycle = lambda: 1 / 0
    with pytest.raises(ConnectorError):
        cycle_steps(conn, cfg)


def test_target_score(cfg):
    assert target_score(ToyConnector(cfg)) is None
    conn = ToyConnector(cfg)
    conn.target_score = lambda: -60
    assert target_score(conn) == -60.0
    for bad in (math.nan, math.inf, "x", True):
        conn.target_score = lambda v=bad: v
        with pytest.raises(ConnectorError):
            target_score(conn)


# ---- 3: gen 0 takes its cycle length from the connector ---------------------------------------------------------
def test_gen0_prompt_uses_cycle_steps(cfg, tmp_path):
    model = demo_model(cfg)
    Orchestrator(cfg, CycleBudget(cfg), model, tmp_path / "run").start(TwoStepToy(cfg))
    assert "a cycle is 2 steps" in json.dumps(model.calls[0]["body"])


# ---- 4-5: loop score and the worse-than-parents penalty ---------------------------------------------------------
def test_loop_scores():
    history = [{"cycle": 1, "steps": 4, "scores": {"A": -10.0, "B": -5.0}},
               {"cycle": 2, "steps": 4, "scores": {"A": -20.0, "C": math.nan}}]
    assert loop_scores(history, 8) == {"A": -30.0, "B": -10.0}


def test_penalty_same_cycle_changes_survivors(cfg):
    scores = {"p": -5.0, "c": -6.0, "x": -7.0, "y": -20.0}
    assert select(scores, cfg)["survivors"] == ["p", "c"]
    adjusted, flags = parent_penalty(scores, {"c": ["p"]}, 4, [], cfg)
    assert adjusted["c"] == pytest.approx(-9.0) and adjusted["p"] == -5.0
    assert flags == {"c": {"score": -6.0, "ref": -5.0, "basis": "same_cycle", "penalty": pytest.approx(3.0)}}
    assert select(adjusted, cfg)["survivors"] == ["p", "x"]


def test_penalty_child_above_parent_unchanged(cfg):
    scores = {"p": -5.0, "c": -4.0, "x": -7.0}
    adjusted, flags = parent_penalty(scores, {"c": ["p"]}, 4, [], cfg)
    assert adjusted == scores and flags == {}


def test_penalty_per_step_when_no_parent_ran(cfg):
    history = [{"cycle": 1, "steps": 4, "scores": {"q": -8.0}}]           # q: -2 per step
    _, flags = parent_penalty({"r": -12.0, "z": -1.0}, {"r": ["q"]}, 4, history, cfg)   # r: -3 per step
    assert flags["r"]["basis"] == "per_step" and flags["r"]["ref"] == -2.0
    _, flags = parent_penalty({"r": -6.0, "z": -1.0}, {"r": ["q"]}, 4, history, cfg)    # -1.5 per step
    assert flags == {}


def test_penalty_skips_what_cannot_compare(cfg):
    scores = {"a": -5.0, "b": math.nan, "c": -9.0}
    adjusted, flags = parent_penalty(scores, {"b": ["a"], "c": ["ghost"]}, 4, [], cfg)
    assert flags == {} and adjusted["c"] == -9.0


# ---- 6: the full fake run ---------------------------------------------------------------------------------------
def test_full_fake_run(cfg, tmp_path):
    op, conn, model, result = run_op(cfg, tmp_path)
    run_dir = tmp_path / "run"
    assert result["reason"] == "max_loops"
    assert conn.released == list(range(8)) * 2                      # wrap-around
    steps = events(run_dir, "step")
    assert len(steps) == 16 and all(len(s["agents"]) == 10 for s in steps)
    assert len(conn.begun) == 4 and all(len(ids) == 10 for ids in conn.begun)
    assert [g["cycle"] for g in events(run_dir, "generation")] == [1, 2, 3]
    assert [c["cycle"] for c in events(run_dir, "cleaner")] == [1, 2, 3]
    assert all(len(g["ids"]) == 10 for g in events(run_dir, "generation"))
    assert len(list((run_dir / "hidden" / "eval" / "cycle-4").glob("*.json"))) == 10
    finals = [c for c in model.calls if c["role"] == "orchestrator" and FINAL in json.dumps(c["body"])]
    assert len(finals) == 1
    final = json.loads((run_dir / "final.json").read_text())
    assert final["selected"] in [a.id for a in op.orch.agents] and final["fallback"] is False
    assert [e["loop_score"] for e in events(run_dir, "loop_end")] == [-40.0, -40.0]
    assert events(run_dir, "stop")[0]["reason"] == "max_loops"
    assert json.loads((run_dir / "config.json").read_text())["operation"]["max_loops"] == 2


# ---- 7: no look-ahead after the wrap ----------------------------------------------------------------------------
def test_no_data_survives_into_a_replayed_cycle(cfg, tmp_path):
    model = demo_model(cfg)

    def agent(messages, offered, rng):
        user = next(m["content"] for m in messages if m.get("role") == "user")
        if any(m.get("type") == "function_call_output" for m in messages):
            return {"tool_calls": [{"name": "finish", "arguments": {"summary": "ok"}}]}
        if "Step 8 of 8" in user:
            return {"tool_calls": [
                {"name": "write_file", "arguments": {"path": "notes.md", "content": f"remember {SECRET}\n"}},
                {"name": "write_file", "arguments": {"path": "data.md", "content": DATA_HEADER + "v7 = 8\n"}}]}
        return {"tool_calls": [{"name": "finish", "arguments": {}}]}

    model.defaults["agent"] = agent
    seen, sent = [], []

    class Checked(RecToy):
        def begin_cycle(self, agent_ids):
            leftovers = []
            for aid in agent_ids:
                folder = tmp_path / "run" / "agents" / aid
                for f in folder.rglob("*"):
                    text = f.read_text(errors="replace") if f.is_file() else ""
                    if SECRET in text or "v7 = 8" in text:
                        leftovers.append(f"{aid}/{f.name}")
                if (folder / "data.md").read_text() != DATA_HEADER:
                    leftovers.append(f"{aid}/data.md not fresh")
            seen.append(leftovers)
            super().begin_cycle(agent_ids)

    conn = Checked(cfg)

    def recording(role, messages, **kw):
        sent.append((conn.loop, conn.current, role, json.dumps(messages)))
        return model(role, messages, **kw)

    run_op(cfg, tmp_path, conn=conn, model=recording)
    assert seen == [[], [], [], []]            # cycle 3 starts right after step 8 planted the data
    loop2 = [s for loop, cur, role, s in sent if loop == 2 and role == "agent" and cur is not None and cur < 7]
    assert loop2 and not any(SECRET in s for s in loop2)


# ---- 8: threshold and the connector's target --------------------------------------------------------------------
def test_threshold_stops_after_loop_one(cfg, tmp_path):
    _, conn, _, result = run_op(cfg, tmp_path, model=demo_model(cfg, threshold=-100), loops=3)
    assert result["reason"] == "threshold" and result["loops"] == 1 and result["cycles"] == 2
    assert conn.released == list(range(8))
    assert [g["cycle"] for g in events(tmp_path / "run", "generation")] == [1]


def test_connector_target_wins(cfg, tmp_path):
    class Target(RecToy):
        def target_score(self):
            return -60

    _, _, _, result = run_op(cfg, tmp_path, conn=Target(cfg), loops=3)
    assert result["reason"] == "threshold" and result["loops"] == 1
    gen0 = events(tmp_path / "run", "gen0")[0]
    assert gen0["target"] == -60.0 and gen0["target_source"] == "connector"


# ---- 9-10: budget stop and a failed final pick ------------------------------------------------------------------
class TightBudget(CycleBudget):
    """A budget whose dollars run out after `after` checks."""

    def __init__(self, cfg, after):
        super().__init__(cfg)
        self.n, self.after = 0, after

    def _check(self, role, est, allowed, agent_id=None):
        self.n += 1
        if self.n > self.after:
            self.limit = 0.0
        super()._check(role, est, allowed, agent_id)


def test_budget_stop(cfg, tmp_path):
    op, _, model, result = run_op(cfg, tmp_path, budget=TightBudget(cfg, after=5))
    assert result["reason"] == "budget:cycle_usd"
    final = json.loads((tmp_path / "run" / "final.json").read_text())
    assert final["fallback"] is True
    assert final["selected"] is None and "no agent was scored" in final["why"]     # stopped before any score
    assert any(e.get("what") == "cap" for e in events(tmp_path / "run", "budget"))
    assert not any(FINAL in json.dumps(c["body"]) for c in model.calls)          # no model call to pick


def test_bad_final_reply_falls_back(cfg, tmp_path):
    model = demo_model(cfg)
    orch = model.defaults["orchestrator"]
    model.defaults["orchestrator"] = lambda m, o, r: ({"text": "not json"} if '"selected"' in m[1]["content"]
                                                       else orch(m, o, r))
    op, _, _, result = run_op(cfg, tmp_path, model=model)
    final = json.loads((tmp_path / "run" / "final.json").read_text())
    scores = loop_scores(op.history, 8)
    current = [a.id for a in op.orch.agents]
    assert final["fallback"] is True
    assert final["selected"] == max(current, key=lambda a: scores.get(a, -math.inf)) == "g0-01"


# ---- 11: the connector's cycle length drives the loop -----------------------------------------------------------
def test_two_step_cycles(cfg, tmp_path):
    _, conn, _, result = run_op(cfg, tmp_path, conn=TwoStepToy(cfg), loops=1)
    assert result["cycles"] == 4
    assert [c["steps"] for c in events(tmp_path / "run", "cycle_end")] == [2, 2, 2, 2]


# ---- 12: the CLI ------------------------------------------------------------------------------------------------
def cli(*args, cwd=ROOT):
    return subprocess.run([sys.executable, str(ROOT / "run.py"), *args], cwd=cwd, capture_output=True, text=True,
                          timeout=600, env={"PATH": "/usr/bin:/bin", "HOME": str(cwd)})


def test_cli_fake_run(tmp_path):
    out = cli("run", "--connector", "tests.fixtures.toy_connector", "--fake", "--max-loops", "2",
              "--out", str(tmp_path))
    assert out.returncode == 0, out.stderr
    assert "stopped: max_loops" in out.stdout
    runs = [p for p in tmp_path.iterdir() if p.is_dir()]
    assert len(runs) == 1 and (runs[0] / "log.jsonl").is_file() and (runs[0] / "final.json").is_file()


def test_cli_needs_a_connector(tmp_path):
    out = cli("run", "--fake", "--out", str(tmp_path))
    assert out.returncode == 2 and "connector" in out.stderr


def test_cli_estimate():
    out = cli("estimate", "--connector", "tests.fixtures.toy_connector")
    assert out.returncode == 0, out.stderr
    for role in config.ROLES:
        assert role in out.stdout
    assert "total" in out.stdout and "steps per cycle: 4" in out.stdout


def test_models_report(cfg):
    import run as run_cli

    class Stub:
        class models:
            @staticmethod
            def list():
                return [type("M", (), {"id": "muse-spark-1.3-contributor"})()]

    cfg["models"]["roles"]["agent"]["model_id"] = "muse-spark-1.2-contributor"
    rows = run_cli.models_report(cfg, Stub())
    assert ("orchestrator", "muse-spark-1.3-contributor", "found") in rows
    assert ("agent", "muse-spark-1.2-contributor", "missing") in rows


# ---- changes after the review -----------------------------------------------------------------------------------
class CapAt(CycleBudget):
    """The cycle's dollars run out at the `nth` check of `role`."""

    def __init__(self, cfg, role, nth=1):
        super().__init__(cfg)
        self.role, self.nth, self.seen = role, nth, 0

    def _check(self, role, est, allowed, agent_id=None):
        if role == self.role:
            self.seen += 1
            if self.seen >= self.nth:
                self.limit = 0.0
        super()._check(role, est, allowed, agent_id)


def test_cap_in_eval_stops_the_run(cfg, tmp_path):
    _, _, _, result = run_op(cfg, tmp_path, budget=CapAt(cfg, "evaluator"))
    assert result["reason"] == "budget:cycle_usd" and result["cycles"] == 1
    assert events(tmp_path / "run", "generation") == []
    assert result["selected"] is not None and result["fallback"] is True      # cycle 1 was scored


def test_cap_in_summarizer_stops_the_run(cfg, tmp_path):
    _, _, _, result = run_op(cfg, tmp_path, budget=CapAt(cfg, "summarizer"))
    assert result["reason"] == "budget:cycle_usd"
    assert len(events(tmp_path / "run", "step")) == 1


def test_cap_in_final_pick_is_a_budget_stop(cfg, tmp_path):
    # max_loops 1: Op. Orch checks are gen 0, next generation, review (cycle 1), then the final pick
    _, _, _, result = run_op(cfg, tmp_path, budget=CapAt(cfg, "orchestrator", nth=4), loops=1)
    assert result["reason"] == "budget:cycle_usd" and result["fallback"] is True
    assert result["selected"] is not None


def test_data_file_deletion_cannot_be_undone(cfg, tmp_path):
    from apex.agent import Agent
    from apex.cleaner import Cleaner, CleanerError

    a = Agent.create(tmp_path / "agents", tmp_path / "logs", "a1", "# axioms\n", {"t.csv": "1,2\n"})
    (a.dir / "data.md").write_text(DATA_HEADER + "v3 = 8\n")
    cleaner = Cleaner(cfg, CycleBudget(cfg), demo_model(cfg), tmp_path / "hidden")
    recs = cleaner.clean(1, a, ToyConnector(cfg).cleaning_rules())
    for kind, source in (("data_file", "rule"), ("whole_file", "glob")):
        rec = next(r for r in recs if r["kind"] == kind and r["source"] == source)
        with pytest.raises(CleanerError):
            cleaner.undo(rec["id"])
    assert not (a.dir / "data.md").exists() and not (a.dir / "t.csv").exists()


def test_huge_scores_stay_finite(cfg):
    adjusted, flags = parent_penalty({"p": 1e308, "c": -1e308}, {"c": ["p"]}, 4, [], cfg)
    assert math.isfinite(flags["c"]["penalty"]) and adjusted["c"] < -1e307
    history = [{"steps": 4, "scores": {"A": 1e308}}, {"steps": 4, "scores": {"A": 1e308, "B": -1.0}}]
    assert loop_scores(history, 8) == {"B": -2.0}


def test_cli_rejects_zero_loops(tmp_path):
    out = cli("run", "--connector", "tests.fixtures.toy_connector", "--fake", "--max-loops", "0",
              "--out", str(tmp_path))
    assert out.returncode == 2 and "max_loops" in out.stderr
