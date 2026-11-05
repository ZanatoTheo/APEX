"""Evaluator: hidden per-agent notes."""
import json

import pytest

from apex import config
from apex.agent import Agent
from apex.budget import CycleBudget
from apex.evaluator import Evaluator
from apex.fake_model import FakeModel
from apex.tools import Workspace, core_toolset
from tests.fixtures.toy_connector import ToyConnector

GOOD = {"strengths": ["s"], "weaknesses": ["w"], "axiom_flaws": ["f"],
        "axiom_fixes": [{"axis": "signals", "fix": "watch more", "why": "missed turns"}]}


@pytest.fixture
def cfg():
    return config.load()


def agents(tmp_path, n=3):
    conn = ToyConnector()
    out = []
    for i in range(n):
        a = Agent.create(tmp_path / "run" / "agents", tmp_path / "run" / "logs", f"g0-{i + 1:02d}", f"AXIOMS-{i}",
                         conn.starter_files())
        (a.dir / "model.py").write_text(f"WORK = {i}\n")
        out.append(a)
    return out


def ev(cfg, tmp_path, scripts, budget=None):
    fake = FakeModel(cfg, scripts)
    return Evaluator(cfg, budget or CycleBudget(cfg), fake, tmp_path / "run" / "hidden"), fake


# 8
def test_judge_writes_hidden_notes(cfg, tmp_path):
    ags = agents(tmp_path)
    e, _ = ev(cfg, tmp_path, {"evaluator": [{"text": json.dumps(GOOD)}] * 3})
    notes = e.judge(1, ags, {"g0-01": -3.0, "g0-02": -1.0, "g0-03": -2.0}, ToyConnector().brief())
    assert set(notes) == {"g0-01", "g0-02", "g0-03"} and notes["g0-02"]["strengths"] == ["s"]
    stored = json.loads((tmp_path / "run" / "hidden" / "eval" / "cycle-1" / "g0-02.json").read_text())
    assert stored["axiom_fixes"][0]["axis"] == "signals" and stored["score"] == -1.0


# 9
def test_prompt_holds_the_agents_work(cfg, tmp_path):
    ags = agents(tmp_path)
    e, fake = ev(cfg, tmp_path, {"evaluator": [{"text": json.dumps(GOOD)}] * 3})
    e.judge(1, ags, {"g0-01": -3.0, "g0-02": -1.0, "g0-03": -2.0}, "BRIEF")
    body = json.dumps(fake.calls[1]["body"])
    assert "AXIOMS-1" in body and "WORK = 1" in body and "-1.0" in body and "BRIEF" in body
    assert "AXIOMS-0" not in body and "WORK = 0" not in body


# 10
def test_bad_reply_marks_one_agent(cfg, tmp_path):
    ags = agents(tmp_path)
    e, _ = ev(cfg, tmp_path, {"evaluator": [{"text": "x"}, {"text": "y"}, {"text": json.dumps(GOOD)},
                                            {"text": json.dumps(GOOD)}]})
    notes = e.judge(1, ags, {"g0-01": 0.0, "g0-02": 0.0, "g0-03": 0.0}, "B")
    assert "error" in notes["g0-01"] and notes["g0-02"]["weaknesses"] == ["w"] and "error" not in notes["g0-03"]


# 11
def test_cap_midway(tmp_path):
    cfg = config.load(overrides={"budget": {"cycle_usd": 1e-9}})
    ags = agents(tmp_path)
    e, fake = ev(cfg, tmp_path, {"evaluator": [{"text": json.dumps(GOOD)}] * 3})
    notes = e.judge(1, ags, {a.id: 0.0 for a in ags}, "B")
    assert all("cycle_usd" in notes[a.id]["error"] for a in ags) and fake.calls == []


# 12
def test_agents_cannot_read_eval_notes(cfg, tmp_path):
    ags = agents(tmp_path)
    e, _ = ev(cfg, tmp_path, {"evaluator": [{"text": json.dumps(GOOD)}] * 3})
    e.judge(1, ags, {a.id: 0.0 for a in ags}, "B")
    hidden = tmp_path / "run" / "hidden" / "eval" / "cycle-1" / "g0-01.json"
    assert hidden.exists()
    tools = core_toolset(Workspace(ags[0].dir, cfg), cfg)
    out = tools.run({"call_id": "c", "name": "read_file", "arguments": {"path": "../../hidden/eval/cycle-1/g0-01.json"},
                     "error": None})
    assert out["output"].startswith("error:")
    (ags[0].dir / "peek.py").write_text(f"""
try:
    print(open({str(hidden)!r}).read())
except OSError as e:
    print("blocked", type(e).__name__)
""")
    out = tools.run({"call_id": "c", "name": "run_script", "arguments": {"path": "peek.py"}, "error": None})
    assert "blocked" in out["output"] and "watch more" not in out["output"]


# 17
def test_files_text_cuts_cleanly(cfg, tmp_path):
    (a,) = agents(tmp_path, 1)
    (a.dir / "big.md").write_text("é" * 200_000)
    text = a.files_text(1000)
    assert "binary" not in text and "é" in text and len(text) < 1100
    for i in range(300):
        (a.dir / f"d{i:03d}").mkdir()
        (a.dir / f"d{i:03d}" / "f.txt").write_text("x" * 50)
    import apex.agent as agent_mod
    opened = []
    real_open = open
    def counting_open(path, *args, **kw):
        opened.append(path)
        return real_open(path, *args, **kw)
    agent_mod.open = counting_open
    try:
        a.files_text(1000)
    finally:
        del agent_mod.open
    assert len(opened) < 40


# 18
def test_judge_survives_huge_score(cfg, tmp_path):
    ags = agents(tmp_path)
    e, _ = ev(cfg, tmp_path, {"evaluator": [{"text": json.dumps(GOOD)}] * 3})
    notes = e.judge(1, ags, {"g0-01": 10 ** 400, "g0-02": 0.0, "g0-03": 1.0}, "B")
    assert len(notes) == 3
