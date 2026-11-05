"""Op. Orch gen 0, stop threshold, and the per-step summarizer."""
import json

import pytest

from apex import config
from apex.budget import CycleBudget
from apex.call_agent import call_agent
from apex.fake_model import FakeModel
from apex.jsonreply import ReplyError
from apex.orchestrator import Orchestrator, OrchestratorError
from apex.summarizer import Summarizer
from tests.fixtures.toy_connector import SECRET, ToyConnector


@pytest.fixture
def cfg():
    return config.load()


def drafts(cfg, n, start=0):
    axes = cfg["operation"]["axes"]
    return [{"name": f"agent {i}", "approach": f"approach {i}",
             "axioms": {axis: f"rule {i} for {axis.split(':')[0]}" for axis in axes}} for i in range(start, start + n)]


def gen0(cfg, n, threshold=-5):
    return {"text": json.dumps({"stop_threshold": threshold, "threshold_reason": "r", "agents": drafts(cfg, n)})}


def orch(cfg, tmp_path, scripts, **kw):
    fake = FakeModel(cfg, scripts, **kw)
    return Orchestrator(cfg, CycleBudget(cfg), fake, tmp_path / "run"), fake


def seeds(tmp_path, n):
    root = tmp_path / "seeds"
    for i in range(n):
        (root / f"s{i:02d}").mkdir(parents=True)
        (root / f"s{i:02d}" / "axioms.md").write_text(f"seed {i}")
    return root


def orch_log(o):
    return [json.loads(line) for line in (o.run_dir / "orch" / "log.jsonl").read_text().splitlines()]


# 1
def test_seeds_used_as_given(cfg, tmp_path):
    root = seeds(tmp_path, 10)
    (root / "s03" / "answer.py").write_text("ANSWER = 4\n")
    o, fake = orch(cfg, tmp_path, {"orchestrator": [gen0(cfg, 0)]})
    agents = o.start(ToyConnector(cfg), root)
    assert [a.id for a in agents] == [f"g0-{i:02d}" for i in range(1, 11)]
    assert [(a.dir / "axioms.md").read_text() for a in agents] == [f"seed {i}" for i in range(10)]
    assert (agents[3].dir / "answer.py").read_text() == "ANSWER = 4\n"
    assert (agents[0].dir / "answer.py").read_text() == "ANSWER = 0\n"
    assert "Draft 0 new agents" in json.dumps(fake.calls[0]["body"])


# 2
def test_some_seeds(cfg, tmp_path):
    o, fake = orch(cfg, tmp_path, {"orchestrator": [gen0(cfg, 7)]})
    agents = o.start(ToyConnector(cfg), seeds(tmp_path, 3))
    assert len(agents) == 10 and (agents[2].dir / "axioms.md").read_text() == "seed 2"
    body = json.dumps(fake.calls[0]["body"])
    assert "Draft 7 new agents" in body and "seed 1" in body


# 3
def test_no_seeds(cfg, tmp_path):
    o, _ = orch(cfg, tmp_path, {"orchestrator": [gen0(cfg, 10)]})
    agents = o.start(ToyConnector(cfg))
    assert [a.id for a in agents] == [f"g0-{i:02d}" for i in range(1, 11)]
    assert len({a.axioms for a in agents}) == 10
    text = (agents[4].dir / "axioms.md").read_text()
    assert "agent 4" in text and "approach 4" in text
    assert all(f"## {axis}" in text for axis in cfg["operation"]["axes"])
    assert o.stop_threshold == -5
    assert orch_log(o)[-1]["event"] == "gen0" and orch_log(o)[-1]["stop_threshold"] == -5


# 4
def test_retry_once(cfg, tmp_path):
    o, fake = orch(cfg, tmp_path, {"orchestrator": [{"text": "not json"}, gen0(cfg, 10)]})
    assert len(o.start(ToyConnector(cfg))) == 10
    assert "not valid: reply is not a JSON object" in json.dumps(fake.calls[1]["body"])


def test_fails_after_one_retry(cfg, tmp_path):
    o, _ = orch(cfg, tmp_path, {"orchestrator": [gen0(cfg, 9), gen0(cfg, 9)]})
    with pytest.raises(ReplyError, match="expected 10 agents"):
        o.start(ToyConnector(cfg))
    assert not (tmp_path / "run" / "agents").exists() or not any((tmp_path / "run" / "agents").iterdir())


# 5
def test_duplicate_axioms_refused(cfg, tmp_path):
    d = drafts(cfg, 10)
    d[7]["axioms"] = {k: "  " + v.upper() + " " for k, v in d[2]["axioms"].items()}
    bad = {"text": json.dumps({"stop_threshold": 1, "threshold_reason": "r", "agents": d})}
    o, _ = orch(cfg, tmp_path, {"orchestrator": [bad, bad]})
    with pytest.raises(ReplyError, match="same axioms"):
        o.start(ToyConnector(cfg))


# 6
def test_bad_seeds_and_double_start(cfg, tmp_path):
    root = seeds(tmp_path, 2)
    (root / "s01" / "axioms.md").unlink()
    o, _ = orch(cfg, tmp_path, {})
    with pytest.raises(OrchestratorError, match="axioms.md"):
        o.start(ToyConnector(cfg), root)
    o2, _ = orch(cfg, tmp_path / "b", {})
    with pytest.raises(OrchestratorError):
        o2.start(ToyConnector(cfg), seeds(tmp_path / "b", 11))
    o3, _ = orch(cfg, tmp_path / "c", {"orchestrator": [gen0(cfg, 10)]})
    o3.start(ToyConnector(cfg))
    with pytest.raises(OrchestratorError):
        o3.start(ToyConnector(cfg))


# 7
def test_should_stop(cfg, tmp_path):
    o, _ = orch(cfg, tmp_path, {"orchestrator": [gen0(cfg, 10)]})
    o.start(ToyConnector(cfg))
    assert o.should_stop(-4.9) and o.should_stop(-5) and not o.should_stop(-6)


# 8
def test_no_secret_in_orch_or_summary(cfg, tmp_path):
    conn = ToyConnector(cfg)
    conn.release(2)
    o, fake = orch(cfg, tmp_path, {
        "orchestrator": [gen0(cfg, 10)],
        "agent": [{"tool_calls": [{"name": "read_values", "arguments": {}}]},
                  {"tool_calls": [{"name": "finish", "arguments": {"summary": "saw 3 5 4"}}]}],
        "summarizer": [{"text": "all fine"}]})
    agents = o.start(conn)
    conn.begin_cycle([a.id for a in agents])
    report = conn.run_step(agents[0].id, agents[0].dir, 2)
    result = call_agent(agents[0], report, 2, conn, o.budget, fake)
    text = Summarizer(cfg, o.budget, fake).summarize(agents[:1], 2, {agents[0].id: {"report": report, "call": result}})
    assert text == "all fine"
    orch_bodies = json.dumps([c["body"] for c in fake.calls if c["role"] in ("orchestrator", "summarizer")])
    assert SECRET not in orch_bodies
    summ = json.dumps([c["body"] for c in fake.calls if c["role"] == "summarizer"])
    assert "saw 3 5 4" in summ and "-4.0" in summ


# 9
def test_summary_fallback(tmp_path):
    cfg = config.load(overrides={"budget": {"cycle_usd": 1e-9}})
    conn = ToyConnector(cfg)
    from apex.agent import Agent
    a = Agent.create(tmp_path / "agents", tmp_path / "logs", "x1", "ax", conn.starter_files())
    result = {"ended_by": "finish", "turns": 1, "files_changed": [], "tokens": 0, "cost": 0, "summary": "s"}
    text = Summarizer(cfg, CycleBudget(cfg), FakeModel(cfg, {})).summarize([a], 0, {"x1": {"report": {"score": -1},
                                                                                         "call": result}})
    assert text.startswith("(no model summary:") and "x1" in text


# ---- review fixes ----------------------------------------------------------------------------------------------
# 10
def test_extract_json_live_formats():
    from apex.jsonreply import extract_json
    assert extract_json('{"a": 1}\nNote: keep {axis} names') == {"a": 1}
    assert extract_json('Here: {"a": {"b": "}"}} and also {"c": 2}') == {"a": {"b": "}"}}
    assert extract_json("see {axis} then ```json\n{\"a\": 2}\n```") == {"a": 2}
    assert extract_json("[" * 100000) is None


# 11
def test_overflowing_threshold_is_a_reply_problem(cfg, tmp_path):
    bad = {"text": '{"stop_threshold": 1' + "0" * 400 + ', "agents": []}'}
    o, _ = orch(cfg, tmp_path, {"orchestrator": [bad, bad]})
    with pytest.raises(ReplyError):
        o.start(ToyConnector(cfg))


# 12
def test_draft_equal_to_seed_refused(cfg, tmp_path):
    o, _ = orch(cfg, tmp_path, {})
    d = drafts(cfg, 1)
    root = seeds(tmp_path, 1)
    (root / "s00" / "axioms.md").write_text(o.render(d[0]))
    assert "same axioms" in o.check_drafts(d, 1, [(root / "s00" / "axioms.md").read_text()])


# 13
def test_seed_files_checked(cfg, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("HOST FILE")
    root = seeds(tmp_path, 1)
    (root / "s00" / "notes.md").symlink_to(outside)
    o, _ = orch(cfg, tmp_path, {})
    with pytest.raises(OrchestratorError, match="link"):
        o.start(ToyConnector(cfg), root)
    (root / "s00" / "notes.md").unlink()
    (root / "s00" / "blob.bin").write_bytes(b"\xff\xfe\x00\x81")
    with pytest.raises(OrchestratorError, match="text"):
        o.start(ToyConnector(cfg), root)
    (root / "s00" / "blob.bin").unlink()
    (root / "s00" / "big.txt").write_text("x" * (cfg["tools"]["max_file_chars"] + 1))
    with pytest.raises(OrchestratorError, match="big"):
        o.start(ToyConnector(cfg), root)


# 14
def test_axis_keys_loose_match(cfg, tmp_path):
    d = drafts(cfg, 10)
    for x in d:
        x["axioms"] = {" " + k.split(":")[0].upper() + " ": v for k, v in x["axioms"].items()}
    o, _ = orch(cfg, tmp_path, {"orchestrator": [{"text": json.dumps({"stop_threshold": 1, "agents": d})}]})
    assert len(o.start(ToyConnector(cfg))) == 10


# 15
def test_creation_failure_rolls_back(cfg, tmp_path, monkeypatch):
    from apex import orchestrator as orch_mod
    real, n = orch_mod.Agent.create, {"i": 0}

    def flaky(*a, **k):
        n["i"] += 1
        if n["i"] == 4:
            raise OSError("disk full")
        return real(*a, **k)

    monkeypatch.setattr(orch_mod.Agent, "create", flaky)
    o, _ = orch(cfg, tmp_path, {"orchestrator": [gen0(cfg, 10), gen0(cfg, 10)]})
    with pytest.raises(OrchestratorError, match="disk full"):
        o.start(ToyConnector(cfg))
    assert o.agents == [] and o.stop_threshold is None
    assert not any((tmp_path / "run" / "agents").iterdir()) and not any((tmp_path / "run" / "logs").iterdir())
    monkeypatch.setattr(orch_mod.Agent, "create", real)
    assert len(o.start(ToyConnector(cfg))) == 10
