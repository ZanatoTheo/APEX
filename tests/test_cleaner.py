"""The cleaner, its deletion log, undo, and Op. Orch's review."""
import json

import pytest

from apex import config
from apex.agent import Agent
from apex.budget import CapReached, CycleBudget
from apex.cleaner import Cleaner, CleanerError
from apex.fake_model import FakeModel
from apex.orchestrator import Orchestrator
from tests.fixtures.toy_connector import ToyConnector

RULES = ToyConnector().cleaning_rules()
NO_FACTS = {"text": json.dumps({"facts": []})}


@pytest.fixture
def cfg():
    return config.load()


def facts(*items):
    return {"text": json.dumps({"facts": [{"file": f, "quote": q, "reason": "data"} for f, q in items]})}


def make(tmp_path, agent_id="a1", notes=None, extra=None):
    files = dict(ToyConnector().starter_files())
    if notes is not None:
        files["notes.md"] = notes
    files.update(extra or {})
    return Agent.create(tmp_path / "run" / "agents", tmp_path / "run" / "logs", agent_id, "axioms text", files,
                        RULES["data_file"])


def cleaner(cfg, tmp_path, replies=(), budget=None):
    fake = FakeModel(cfg, {"cleaner": list(replies)}, defaults={"cleaner": NO_FACTS})
    return Cleaner(cfg, budget or CycleBudget(cfg), fake, tmp_path / "run" / "hidden"), fake


def by_file(dels, name):
    return [d for d in dels if d["file"] == name]


def events(tmp_path):
    path = tmp_path / "run" / "hidden" / "cleaner" / "deletions.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


# 1
def test_data_file(cfg, tmp_path):
    a = make(tmp_path)
    original = (a.dir / "data.md").read_text() + "v1=5\n"
    (a.dir / "data.md").write_text(original)
    c, _ = cleaner(cfg, tmp_path)
    dels = c.clean(1, a, RULES)
    assert not (a.dir / "data.md").exists()
    d = by_file(dels, "data.md")[0]
    assert d["id"] == "c1-0001" and d["kind"] == "data_file"
    with pytest.raises(CleanerError, match="data by the task's rules"):   # never brought back
        c.undo("c1-0001")
    assert not (a.dir / "data.md").exists()


# 2
def test_pattern_fact_and_lesson(cfg, tmp_path):
    a = make(tmp_path, notes="v3=8 seen; lesson: smooth over 3 steps\n")
    c, _ = cleaner(cfg, tmp_path)
    d = by_file(c.clean(1, a, RULES), "notes.md")[0]
    assert (a.dir / "notes.md").read_text() == "[cleaned c1-0002] seen; lesson: smooth over 3 steps\n"
    assert d["source"] == "pattern" and d["original"] == "v3=8" and d["kind"] == "span"


# 3
def test_model_fact(cfg, tmp_path):
    a = make(tmp_path, notes="the fourth number was eight\nkeep it simple\n")
    c, fake = cleaner(cfg, tmp_path, [facts(("notes.md", "the fourth number was eight"))])
    d = by_file(c.clean(1, a, RULES), "notes.md")[0]
    assert (a.dir / "notes.md").read_text() == "[cleaned c1-0002]\nkeep it simple\n" and d["source"] == "model"


def test_bad_quotes_skip_model_pass(cfg, tmp_path):
    a = make(tmp_path, notes="the fourth number was eight\nv2=4\n")
    c, _ = cleaner(cfg, tmp_path, [facts(("notes.md", "not there"))] * 2)
    c.clean(1, a, RULES)
    text = (a.dir / "notes.md").read_text()
    assert "v2=4" not in text and "the fourth number was eight" in text
    assert any(e["event"] == "model_pass_failed" for e in events(tmp_path))


# 4
def test_undo_exact_and_refusals(cfg, tmp_path):
    original = "v3=8 seen; lesson: smooth over 3 steps\n"
    a = make(tmp_path, notes=original)
    c, _ = cleaner(cfg, tmp_path)
    c.clean(1, a, RULES)
    c.undo("c1-0002")
    assert (a.dir / "notes.md").read_text() == original
    with pytest.raises(CleanerError):
        c.undo("c1-0002")
    with pytest.raises(CleanerError):
        c.undo("c7-0001")

    b = make(tmp_path / "b", notes=original)
    c2, _ = cleaner(cfg, tmp_path / "b")
    c2.clean(1, b, RULES)
    (b.dir / "notes.md").write_text("agent rewrote this\n")
    with pytest.raises(CleanerError):
        c2.undo("c1-0002")
    assert (b.dir / "notes.md").read_text() == "agent rewrote this\n"


# 5
def test_code_markers(cfg, tmp_path):
    a = make(tmp_path, extra={
        "answer.py": "ANSWER = 8  # v3=8\n",
        "model.py": "def f():\n    return 1\n\nv3 = 8\n# a comment long enough to keep the share of data low\n"})
    c, _ = cleaner(cfg, tmp_path)
    dels = c.clean(1, a, RULES)
    assert (a.dir / "answer.py").read_text() == "ANSWER = 8  # [cleaned c1-0002]\n"
    assert by_file(dels, "answer.py")[0]["broke_code"] is False
    assert by_file(dels, "model.py")[0]["broke_code"] is True
    assert "\n[cleaned c1-0003]\n" in (a.dir / "model.py").read_text()


# 6
def test_glob_and_dense_files(cfg, tmp_path):
    csv = "step,value\n0,3\n1,5\n"
    dump = "".join(f"v{i}={i}\n" for i in range(200))
    a = make(tmp_path, extra={"values.csv": csv, "dump.txt": dump})
    c, _ = cleaner(cfg, tmp_path)
    dels = c.clean(1, a, RULES)
    assert not (a.dir / "values.csv").exists() and not (a.dir / "dump.txt").exists()
    assert by_file(dels, "values.csv")[0]["source"] == "glob" and by_file(dels, "dump.txt")[0]["source"] == "dense"
    for d in by_file(dels, "values.csv") + by_file(dels, "dump.txt"):
        assert d["kind"] == "whole_file"
    with pytest.raises(CleanerError, match="data by the task's rules"):   # a glob is the connector's rule
        c.undo(by_file(dels, "values.csv")[0]["id"])
    c.undo(by_file(dels, "dump.txt")[0]["id"])                           # dense is the cleaner's own guess
    assert not (a.dir / "values.csv").exists() and (a.dir / "dump.txt").read_text() == dump


# 7
def test_binary_file(cfg, tmp_path):
    a = make(tmp_path)
    (a.dir / "cache.pkl").write_bytes(b"\x80\x04\x95\xff")
    c, _ = cleaner(cfg, tmp_path)
    d = by_file(c.clean(1, a, RULES), "cache.pkl")[0]
    assert d["source"] == "binary" and not (a.dir / "cache.pkl").exists()
    c.undo(d["id"])
    assert (a.dir / "cache.pkl").read_bytes() == b"\x80\x04\x95\xff"


# 8
def test_axioms_cleaned_and_reloaded(cfg, tmp_path):
    a = make(tmp_path)
    (a.dir / "axioms.md").write_text("watch v5=6 closely\nrule two\n")
    c, _ = cleaner(cfg, tmp_path)
    c.clean(1, a, RULES)
    text = (a.dir / "axioms.md").read_text()
    assert "v5=6" not in text and "rule two" in text and a.axioms == text


# 9
def test_undo_refuses_links(cfg, tmp_path):
    a = make(tmp_path, notes="v3=8 seen; lesson: smooth over 3 steps\n")
    outside = tmp_path / "outside.txt"
    outside.write_text("[cleaned c1-0002] host file\n")
    c, _ = cleaner(cfg, tmp_path)
    c.clean(1, a, RULES)
    (a.dir / "notes.md").unlink()
    (a.dir / "notes.md").symlink_to(outside)
    with pytest.raises(CleanerError):
        c.undo("c1-0002")
    (a.dir / "data.md").symlink_to(outside)
    with pytest.raises(CleanerError):
        c.undo("c1-0001")
    assert outside.read_text() == "[cleaned c1-0002] host file\n"


# 10
def review_setup(cfg, tmp_path, orch_replies, budget=None):
    a = make(tmp_path, notes="v3=8 seen; lesson: smooth over 3 steps\n")
    c, _ = cleaner(cfg, tmp_path, budget=budget)
    dels = c.clean(1, a, RULES)
    fake = FakeModel(cfg, {"orchestrator": orch_replies})
    o = Orchestrator(cfg, budget or CycleBudget(cfg), fake, tmp_path / "run")
    return a, c, dels, o


def orch_events(o):
    return [json.loads(line) for line in (o.orch_dir / "log.jsonl").read_text().splitlines()]


def test_review_undoes_with_reason(cfg, tmp_path):
    reply = {"text": json.dumps({"undo": [{"id": "c1-0002", "reason": "a lesson"}]})}
    a, c, dels, o = review_setup(cfg, tmp_path, [reply])
    assert o.review_deletions(1, dels, c) == ["c1-0002"]
    assert "v3=8" in (a.dir / "notes.md").read_text()
    assert any(e["event"] == "undo_decision" and e["ok"] for e in orch_events(o))


def test_review_retries_unknown_id(cfg, tmp_path):
    bad = {"text": json.dumps({"undo": [{"id": "c9-0001", "reason": "x"}]})}
    good = {"text": json.dumps({"undo": []})}
    _, c, dels, o = review_setup(cfg, tmp_path, [bad, good])
    assert o.review_deletions(1, dels, c) == [] and len(o.model.calls) == 2


def test_review_failure_and_cap(cfg, tmp_path):
    _, c, dels, o = review_setup(cfg, tmp_path, [{"text": "no"}, {"text": "no"}])
    assert o.review_deletions(1, dels, c) == []
    assert any(e["event"] == "review_failed" for e in orch_events(o))
    budget = CycleBudget(cfg)
    _, c2, dels2, o2 = review_setup(cfg, tmp_path / "b", [], budget=budget)
    budget.limit = 1e-12
    with pytest.raises(CapReached):
        o2.review_deletions(1, dels2, c2)


# 11
def test_hidden_scoped_and_clean_all(cfg, tmp_path):
    a = make(tmp_path, "a1", notes="A1-NOTE v1=3 and a general lesson about steps\n")
    b = make(tmp_path, "b1", notes="B1-NOTE v2=4 and a general lesson about steps\n")
    c, fake = cleaner(cfg, tmp_path)
    dels = c.clean_all(1, [a, b], RULES)
    assert {d["agent"] for d in dels} == {"a1", "b1"}
    hidden = tmp_path / "run" / "hidden" / "cleaner"
    assert (hidden / "deletions.jsonl").exists() and hidden not in (tmp_path / "run" / "agents").parents
    first = json.dumps(fake.calls[0]["body"])
    assert "A1-NOTE" in first and "B1-NOTE" not in first


def test_clean_all_cap_still_cleans_everyone(tmp_path):
    cfg = config.load(overrides={"budget": {"cycle_usd": 1e-9}})
    a = make(tmp_path, "a1", notes="A1-NOTE v1=3 and a general lesson about steps\n")
    b = make(tmp_path, "b1", notes="B1-NOTE v2=4 and a general lesson about steps\n")
    c, _ = cleaner(cfg, tmp_path)
    with pytest.raises(CapReached):
        c.clean_all(1, [a, b], RULES)
    for ag, fact in ((a, "v1=3"), (b, "v2=4")):
        assert not (ag.dir / "data.md").exists() and fact not in (ag.dir / "notes.md").read_text()


# ---- review fixes ----------------------------------------------------------------------------------------------
import os


# 13
def test_read_only_and_locked_entries_are_cleaned(cfg, tmp_path):
    a = make(tmp_path, notes="v3=8 seen; lesson: smooth over 3 steps\n")
    (a.dir / "notes.md").chmod(0o444)
    (a.dir / "prices.txt").write_text("v1=3\nv2=5\n")
    (a.dir / "prices.txt").chmod(0)
    for name, mode in (("locked", 0), ("readonly", 0o555)):
        (a.dir / name).mkdir()
        (a.dir / name / "dump.txt").write_text("v1=3\nv2=5\n")
        (a.dir / name).chmod(mode)
    c, _ = cleaner(cfg, tmp_path)
    try:
        dels = c.clean(1, a, RULES)
    finally:
        for name in ("locked", "readonly"):
            if (a.dir / name).exists():
                (a.dir / name).chmod(0o755)
    assert "v3=8" not in (a.dir / "notes.md").read_text()
    assert not (a.dir / "prices.txt").exists()
    assert not (a.dir / "locked" / "dump.txt").exists() and not (a.dir / "readonly" / "dump.txt").exists()
    logged = {e["id"] for e in events(tmp_path) if e["event"] == "deletion"}
    assert {d["id"] for d in dels} <= logged


# 14
def test_big_axioms_never_deleted_whole(cfg, tmp_path):
    a = make(tmp_path)
    (a.dir / "axioms.md").write_text("x" * cfg["tools"]["max_file_chars"] + " v3=8\n")
    c, _ = cleaner(cfg, tmp_path)
    dels = by_file(c.clean(1, a, RULES), "axioms.md")
    assert dels and all(d["kind"] == "span" for d in dels)
    assert (a.dir / "axioms.md").exists() and "v3=8" not in (a.dir / "axioms.md").read_text()


# 15
def test_ids_unique_across_cleaner_instances(cfg, tmp_path):
    a = make(tmp_path, notes="v3=8 seen; lesson: smooth over 3 steps\n")
    c1, _ = cleaner(cfg, tmp_path)
    c1.clean(1, a, RULES)                                    # c1-0001 (data.md), c1-0002 (notes)
    b = make(tmp_path, "b1")
    c2, _ = cleaner(cfg, tmp_path)
    d = c2.clean(1, b, RULES)
    assert d[0]["id"] == "c1-0003"
    with pytest.raises(CleanerError, match="data by the task's rules"):   # known to c2 (not "no deletion")
        c2.undo("c1-0001")                                   # a record from the first instance
    c2.undo("c1-0002")
    assert "v3=8" in (a.dir / "notes.md").read_text()


# 16
def test_model_quote_cannot_overlap_a_marker(cfg, tmp_path):
    a = make(tmp_path, notes="v3=8 and more text here\n")
    c, _ = cleaner(cfg, tmp_path, [facts(("notes.md", "2] and"))] * 2)
    c.clean(1, a, RULES)
    assert (a.dir / "notes.md").read_text() == "[cleaned c1-0002] and more text here\n"
    c.undo("c1-0002")
    assert (a.dir / "notes.md").read_text() == "v3=8 and more text here\n"


# 17
def test_odd_entries(cfg, tmp_path):
    a = make(tmp_path)
    os.link(a.dir / "data.md", a.dir / "copy.txt")           # a second name for the data file
    (a.dir / "log.jsonl").write_text("v1=3\nv2=5\n")         # made by a script, not the real log
    os.mkfifo(a.dir / "pipe")
    b = make(tmp_path, "b1")
    (b.dir / "data.md").unlink()
    (b.dir / "data.md").symlink_to(b.dir / "notes.md")
    c, _ = cleaner(cfg, tmp_path)
    c.clean_all(1, [a, b], RULES)
    for gone in ("data.md", "copy.txt", "log.jsonl", "pipe"):
        assert not os.path.lexists(a.dir / gone), gone
    assert not os.path.lexists(b.dir / "data.md") and (b.dir / "notes.md").exists()


# 18
def test_data_in_names(cfg, tmp_path):
    a = make(tmp_path)
    (a.dir / "v3=8 notes.txt").write_text("a general lesson\n")
    (a.dir / "link").symlink_to("v5=6")
    c, _ = cleaner(cfg, tmp_path)
    dels = c.clean(1, a, RULES)
    assert not os.path.lexists(a.dir / "v3=8 notes.txt") and not os.path.lexists(a.dir / "link")
    assert {d["source"] for d in dels if d["file"] in ("v3=8 notes.txt", "link")} == {"name"}
