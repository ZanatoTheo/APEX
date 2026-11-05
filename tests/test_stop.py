"""The stop button and the per-axiom interpretation.md.
Fake model and toy connector only: no real API call."""
import json
from pathlib import Path

import run
from apex import config, prompts
from apex.agent import INTERPRETATION, INTERPRETATION_HEADER, Agent, interpretation_stub
from apex.budget import CycleBudget
from apex.call_agent import call_agent
from apex.fake_model import FakeModel
from apex.fake_run import demo_model
from apex.operation import Operation
from tests.fixtures.toy_connector import ToyConnector

AXES = {"signals: x": "watch X", "sizing: y": "size Y"}


class StopAfter(ToyConnector):
    def __init__(self, cfg, stop_file, n):
        super().__init__(cfg)
        self.stop_file, self.n, self.calls = stop_file, n, 0

    def run_step(self, agent_id, agent_dir, step):
        self.calls += 1
        if self.calls == self.n:
            self.stop_file.write_text("stop\n")
        return super().run_step(agent_id, agent_dir, step)


def events(run_dir, kind):
    rows = [json.loads(line) for line in (Path(run_dir) / "log.jsonl").read_text().splitlines()]
    return [r for r in rows if r["event"] == kind]


# 1
def test_stop_file_mid_run(tmp_path):
    cfg = config.load(overrides={"operation": {"agents": 3, "max_loops": 1, "max_cycles": 2}})
    run_dir = tmp_path / "run"
    op = Operation(cfg, StopAfter(cfg, run_dir / "STOP", 5), demo_model(cfg), run_dir)
    result = op.run()
    assert result["reason"] == "stopped_by_user" and result["fallback"] is True
    assert (run_dir / "final.json").exists()
    assert events(run_dir, "stop")[-1]["reason"] == "stopped_by_user"
    assert events(run_dir, "cycle_end") == []


# 2
def test_run_py_stop_given_dir(tmp_path):
    d = tmp_path / "r1"
    d.mkdir()
    assert run.main(["stop", "--run-dir", str(d)]) == 0
    assert (d / "STOP").exists()


def make_run(root, name, finished):
    d = root / name
    d.mkdir(parents=True)
    (d / "log.jsonl").write_text("")
    if finished:
        (d / "final.json").write_text("{}")
    return d


# 3
def test_run_py_stop_newest_unfinished(tmp_path):
    a = make_run(tmp_path, "20261104-150000-aaaa", True)
    b = make_run(tmp_path, "20261104-140000-bbbb", False)
    c = make_run(tmp_path, "20261104-160000-cccc", False)
    (tmp_path / "run3-20261104-1600.log").write_text("x")
    assert run.main(["stop", "--out", str(tmp_path)]) == 0
    assert (c / "STOP").exists() and not (b / "STOP").exists() and not (a / "STOP").exists()


# 4
def test_run_py_stop_nothing_running(tmp_path):
    a = make_run(tmp_path, "20261104-150000-aaaa", True)
    assert run.main(["stop", "--out", str(tmp_path)]) == 1
    assert not (a / "STOP").exists()


# 5
def test_interpretation_per_axiom(tmp_path):
    axioms = prompts.render_axioms("Name", "An approach.", AXES)
    stub = interpretation_stub(axioms)
    assert "## signals: x\n(empty)" in stub and "## sizing: y\n(empty)" in stub
    agent = Agent.create(tmp_path / "agents", tmp_path / "logs", "a1", axioms, {"answer.py": "ANSWER = 0\n"})
    assert (agent.dir / INTERPRETATION).read_text() == stub


# 6
def test_interpretation_without_headings():
    assert interpretation_stub("AX") == INTERPRETATION_HEADER


# 7
def test_step_message_marks_per_axiom_stub(tmp_path):
    cfg = config.load()
    conn = ToyConnector(cfg)
    agent = Agent.create(tmp_path / "agents", tmp_path / "logs", "a1", prompts.render_axioms("N", "A.", AXES),
                         conn.starter_files(), conn.cleaning_rules()["data_file"])
    conn.release(0)
    fake = FakeModel(cfg, {"agent": [{"text": "ok"}]})
    call_agent(agent, {}, 0, conn, CycleBudget(cfg), fake)
    body = json.dumps(fake.calls[0]["body"])
    assert "--- interpretation.md (still empty: write it first) ---" in body and "## signals: x" in body
