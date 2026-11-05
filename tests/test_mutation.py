"""Mutation drafts and Op. Orch's next generation."""
import json

import pytest

from apex import config
from apex.budget import CycleBudget
from apex.call_agent import snapshot
from apex.fake_model import FakeModel
from apex.mutation import Mutation
from apex.orchestrator import Orchestrator
from apex.selection import select
from tests.fixtures.toy_connector import ToyConnector


@pytest.fixture
def cfg():
    return config.load()


def drafts(cfg, n, tag="d", parents=("g0-01",), start=None):
    axes = cfg["operation"]["axes"]
    return [{"name": f"{tag} {i}", "approach": f"{tag} approach {i}",
             "axioms": {a: f"{tag} rule {i} {a.split(':')[0]}" for a in axes},
             "parents": list(parents), "start_files_from": start, "why": "w"} for i in range(n)]


def gen0_reply(cfg):
    return {"text": json.dumps({"stop_threshold": 0, "threshold_reason": "r",
                                "agents": [{k: d[k] for k in ("name", "approach", "axioms")}
                                           for d in drafts(cfg, 10, tag="g")]})}


def mutation_reply(cfg, n=10, third=None, new_axes=(), start=None):
    return {"text": json.dumps({"axis_analysis": [{"axis": "signals", "held_up": "h", "failed": "f",
                                                   "unaddressed": ["u"]}],
                                "drafts": drafts(cfg, n, start=start), "suggest_third_survivor": third,
                                "third_reason": "close second" if third else "",
                                "new_axes": [{"axis": a, "why": "w"} for a in new_axes]})}


def orch_reply(adopt, n_drafts=10, third=False, fills=(), axes=()):
    return {"text": json.dumps({
        "decisions": [{"draft": i, "adopt": i in adopt, "reason": f"reason {i}"} for i in range(n_drafts)],
        "third_survivor": third, "third_reason": "ok" if third else "",
        "fills": list(fills), "axes": [{"axis": a, "approve": ok, "reason": "r"} for a, ok in axes]})}


def setup(cfg, tmp_path, scripts):
    fake = FakeModel(cfg, {"orchestrator": [gen0_reply(cfg)] + scripts.pop("orchestrator", []), **scripts})
    o = Orchestrator(cfg, CycleBudget(cfg), fake, tmp_path / "run")
    conn = ToyConnector(cfg)
    agents = o.start(conn)
    for i, a in enumerate(agents):
        (a.dir / "model.py").write_text(f"WORK = {i}\n")
    scores = {a.id: float(i) for i, a in enumerate(agents)}          # g0-10 best, g0-09 second
    sel = select(scores, cfg)
    notes = {a.id: {"strengths": [f"S-{a.id}"], "weaknesses": [], "axiom_flaws": [], "axiom_fixes": []} for a in agents}
    return o, conn, fake, agents, sel, notes


def orch_log(o):
    return [json.loads(line) for line in (o.run_dir / "orch" / "log.jsonl").read_text().splitlines()]


# 1
def test_mutation_drafts(cfg, tmp_path):
    o, conn, fake, agents, sel, notes = setup(cfg, tmp_path, {"mutation": [mutation_reply(cfg)]})
    m = Mutation(cfg, o.budget, fake, o.run_dir / "hidden").run(1, agents, notes, sel, conn.brief(), o.axes)
    assert len(m["drafts"]) == 10 and "error" not in m
    assert json.loads((o.run_dir / "hidden" / "mutation" / "cycle-1.json").read_text())["drafts"][0]["name"] == "d 0"
    body = json.dumps(fake.calls[-1]["body"])
    assert all(a.id in body for a in agents) and "S-g0-01" in body and "WORK = 0" in body
    assert "g rule 0" in body                                    # the lowest agent's axioms are shown too


# 2
def test_mutation_failure_is_not_fatal(cfg, tmp_path):
    o, conn, fake, agents, sel, notes = setup(cfg, tmp_path, {"mutation": [mutation_reply(cfg, 9)] * 2})
    m = Mutation(cfg, o.budget, fake, o.run_dir / "hidden").run(1, agents, notes, sel, conn.brief(), o.axes)
    assert m["drafts"] == [] and "expected 10" in m["error"]


def next_gen(cfg, tmp_path, mutation, orch, **kw):
    o, conn, fake, agents, sel, notes = setup(cfg, tmp_path, {"mutation": mutation, "orchestrator": orch})
    m = Mutation(cfg, o.budget, fake, o.run_dir / "hidden").run(1, agents, notes, sel, conn.brief(), o.axes)
    before = {a: snapshot(o.agents_root / a) for a in sel["survivors"]}
    new = o.next_generation(1, conn, sel, notes, m)
    return o, new, sel, before, agents


# 3
def test_adopt_and_drop(cfg, tmp_path):
    o, new, sel, before, _ = next_gen(cfg, tmp_path, [mutation_reply(cfg)], [orch_reply(set(range(8)))])
    assert len(new) == 10 and [a.id for a in new[:2]] == ["g0-10", "g0-09"]
    assert all(snapshot(a.dir) == before[a.id] for a in new[:2])
    assert [a.id for a in new[2:]] == [f"g1-{i:02d}" for i in range(1, 9)]
    assert all(a.generation == 1 and a.parents == ["g0-01"] for a in new[2:])
    decisions = [e for e in orch_log(o) if e["event"] == "draft_decision"]
    assert len(decisions) == 10 and all(d["reason"] for d in decisions)
    assert [d["draft"] for d in decisions if not d["adopt"]] == [8, 9]
    assert o.agents == new and o.generation == 1


# 4
def test_third_survivor_only_when_suggested_and_accepted(cfg, tmp_path):
    o, new, *_ = next_gen(cfg, tmp_path, [mutation_reply(cfg, third="g0-08")],
                          [orch_reply(set(range(7)), third=True)])
    assert [a.id for a in new[:3]] == ["g0-10", "g0-09", "g0-08"] and len(new) == 10

    o, new, *_ = next_gen(cfg, tmp_path / "b", [mutation_reply(cfg, third="g0-08")], [orch_reply(set(range(8)))])
    assert "g0-08" not in [a.id for a in new] and len(new) == 10

    o, new, *_ = next_gen(cfg, tmp_path / "c", [mutation_reply(cfg)],
                          [orch_reply(set(range(7)), third=True), orch_reply(set(range(8)))])
    assert [a.id for a in new[:2]] == ["g0-10", "g0-09"] and "g0-08" not in [a.id for a in new]


# 5
def test_all_dropped_orch_fills(cfg, tmp_path):
    fills = [{k: d[k] for k in ("name", "approach", "axioms")} for d in drafts(cfg, 8, tag="fill")]
    o, new, *_ = next_gen(cfg, tmp_path, [mutation_reply(cfg)], [orch_reply(set(), fills=fills)])
    assert len(new) == 10 and all("fill rule" in a.axioms for a in new[2:])
    assert all(a.parents == [] for a in new[2:])


# 6
def test_decision_needs_reason(cfg, tmp_path):
    bad = json.loads(orch_reply(set(range(8)))["text"])
    bad["decisions"][3]["reason"] = ""
    o, new, *_ = next_gen(cfg, tmp_path, [mutation_reply(cfg)], [{"text": json.dumps(bad)}, orch_reply(set(range(8)))])
    assert len(new) == 10
    assert "reason" in json.dumps(o.model.calls[-1]["body"])


# 7
def test_orch_failure_fallback(cfg, tmp_path):
    o, new, *_ = next_gen(cfg, tmp_path, [mutation_reply(cfg)], [{"text": "no"}, {"text": "no"}])
    assert len(new) == 10 and [a.axioms.splitlines()[0] for a in new[2:]] == [f"# d {i}" for i in range(8)]
    assert any(e["event"] == "fallback" for e in orch_log(o))


# 8
def test_everything_fails_fallback_copies_bases(cfg, tmp_path):
    o, new, sel, *_ = next_gen(cfg, tmp_path, [mutation_reply(cfg, 1)] * 2, [{"text": "no"}, {"text": "no"}])
    assert len(new) == 10
    base_axioms = {a.axioms for a in o.all_agents.values() if a.id in sel["bases"]}
    assert all(a.axioms in base_axioms for a in new[2:])


# 9
def test_new_axes(cfg, tmp_path):
    o, new, *_ = next_gen(cfg, tmp_path, [mutation_reply(cfg, new_axes=("timing: when to act", "memory: what to keep"))],
                          [orch_reply(set(range(8)), axes=[("timing: when to act", True),
                                                           ("memory: what to keep", False)])])
    assert "timing: when to act" in o.axes and "memory: what to keep" not in o.axes
    assert any(e["event"] == "axis_decision" and not e["approve"] for e in orch_log(o))


# 10
def test_start_files_from_parent(cfg, tmp_path):
    o, new, *_ = next_gen(cfg, tmp_path, [mutation_reply(cfg, start="g0-05")], [orch_reply(set(range(8)))])
    assert (new[2].dir / "model.py").read_text() == "WORK = 4\n"
    o2, new2, *_ = next_gen(cfg, tmp_path / "b", [mutation_reply(cfg)], [orch_reply(set(range(8)))])
    assert not (new2[2].dir / "model.py").exists() and (new2[2].dir / "answer.py").read_text() == "ANSWER = 0\n"


# ---- review fixes ----------------------------------------------------------------------------------------------
# 11
def test_all_nan_scores_still_ten(cfg, tmp_path):
    o, conn, fake, agents, _, notes = setup(cfg, tmp_path, {"mutation": [mutation_reply(cfg, 1)] * 2,
                                                            "orchestrator": [{"text": "no"}, {"text": "no"}]})
    sel = select({a.id: float("nan") for a in agents}, cfg)
    m = Mutation(cfg, o.budget, fake, o.run_dir / "hidden").run(1, agents, notes, sel, conn.brief(), o.axes)
    assert len(o.next_generation(1, conn, sel, notes, m)) == 10


# 12
def test_draft_with_a_survivors_rules_refused(cfg, tmp_path):
    from apex.orchestrator import check_drafts
    o, conn, fake, agents, sel, notes = setup(cfg, tmp_path, {})
    survivor = o.all_agents["g0-10"]
    d = drafts(cfg, 1)[0]
    d["axioms"] = {a: f"g rule 9 {a.split(':')[0]}" for a in cfg["operation"]["axes"]}    # g0-10's rules
    assert "same axioms" in check_drafts(o.axes, [d], 1, [survivor.axioms])


# 13
def test_copies_key_from_model_ignored(cfg, tmp_path):
    r = json.loads(orch_reply(set(range(8)))["text"])
    r["_copies"] = ["g0-01", "g0-02"]
    o, new, *_ = next_gen(cfg, tmp_path, [mutation_reply(cfg)], [{"text": json.dumps(r)}])
    assert len(new) == 10 and not any(e["event"] == "fallback" for e in orch_log(o))


# 14
def test_budget_stop_passes_through(tmp_path):
    from apex.budget import CapReached
    cfg = config.load()
    o, conn, fake, agents, sel, notes = setup(cfg, tmp_path, {})
    o.budget.limit = 1e-12
    with pytest.raises(CapReached):
        Mutation(cfg, o.budget, fake, o.run_dir / "hidden").run(1, agents, notes, sel, conn.brief(), o.axes)
    with pytest.raises(CapReached):
        o.next_generation(1, conn, sel, notes, {"drafts": []})
    assert o.generation == 0 and not (o.agents_root / "g1-01").exists()


# 15
def test_new_axes_must_differ(cfg, tmp_path):
    for bad in (("timing: a", "Timing: b"), (": x",)):
        o, conn, fake, agents, sel, notes = setup(cfg, tmp_path / str(len(bad)),
                                                  {"mutation": [mutation_reply(cfg, new_axes=bad)] * 2})
        m = Mutation(cfg, o.budget, fake, o.run_dir / "hidden").run(1, agents, notes, sel, conn.brief(), o.axes)
        assert m["drafts"] == [] and "new_axes" in m["error"]


# 16
def test_work_files_total_cap(cfg, tmp_path):
    o, conn, fake, agents, sel, notes = setup(cfg, tmp_path, {})
    a = agents[0]
    for i in range(30):
        (a.dir / f"f{i:02d}.txt").write_text("x" * 1000)
    skipped = []
    files = a.work_files(1000, skipped=skipped)
    assert sum(len(t) for t in files.values()) <= 10_000 and skipped


# 17
def test_eval_notes_capped_in_orch_prompt(cfg):
    from apex.prompts import next_gen_message
    notes = {f"g0-{i:02d}": {"strengths": ["s" * 20000]} for i in range(10)}
    sel = {"scores": {}, "survivors": [], "bases": []}
    msg = next_gen_message(cfg["operation"]["axes"], sel, notes, {}, [], None, [], 10,
                           cfg["operation"]["orch_notes_chars"])
    assert len(msg) < cfg["operation"]["orch_notes_chars"] + 5000
