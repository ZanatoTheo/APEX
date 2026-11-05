"""The held-out check of the picked agent: a copy walks the held-out steps once, with no evolution.
Fake models only: no real API call."""
import hashlib
import json
import math
import os
import signal
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from apex import config
from apex.agent import DATA_HEADER
from apex.budget import CycleBudget
from apex.fake_run import demo_model
from apex.operation import Operation
from tests.fixtures import make_env_fixtures
from tests.fixtures.toy_connector import ToyConnector
from tests.test_operation import TightBudget

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"
HELD = [2, 9, 1, 7]
OTHER_ROLES = ("orchestrator", "evaluator", "mutation", "summarizer")


@pytest.fixture
def cfg():
    c = config.load()
    c["operation"]["max_loops"] = 1
    return c


@pytest.fixture(autouse=True)
def guard():
    def stuck(*_):
        raise AssertionError("the test ran past 240 s")
    old = signal.signal(signal.SIGALRM, stuck)
    signal.alarm(240)                                                   # a hang fails the test, it doesn't hang it
    yield
    signal.alarm(0)
    signal.signal(signal.SIGALRM, old)


def events(run_dir, kind=None):
    rows = [json.loads(line) for line in (Path(run_dir) / "log.jsonl").read_text().splitlines()]
    return [r for r in rows if kind is None or r["event"] == kind]


def tree_hashes(folder: Path) -> dict:
    return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file() and os.access(p, os.R_OK)}


def run_with_holdout(cfg, tmp_path, held=None, budget=None, before_holdout=None):
    model = demo_model(cfg)
    op = Operation(cfg, ToyConnector(cfg), model, tmp_path / "run", budget=budget,
                   holdout=held if held is not None else ToyConnector(cfg, HELD))
    seen, original = {}, op.holdout_check

    def wrapped(agent_id):
        agent = next(a for a in op.orch.agents if a.id == agent_id)
        if before_holdout:
            before_holdout(op, agent)
        seen.update(roles=Counter(c["role"] for c in model.calls), agent=agent, hashes=tree_hashes(agent.dir))
        return original(agent_id)

    op.holdout_check = wrapped
    return op, model, op.run(), seen


# ---- 1-3: the walk, the copy, the cleaning ----------------------------------------------------------------------
def test_full_walk(cfg, tmp_path):
    _, model, result, seen = run_with_holdout(cfg, tmp_path)
    run = tmp_path / "run"
    h = result["holdout"]
    assert h == json.loads((run / "final.json").read_text())["holdout"]
    assert h["agent"] == result["selected"] and h["stopped"] == "done"
    assert (h["steps_done"], h["n_steps"], h["cycles"]) == (4, 4, 1)
    assert h["target"] is None and h["target_source"] == "none" and h["passed"] is None     # the toy has no target
    steps = events(run, "holdout_step")
    assert [e["step"] for e in steps] == [0, 1, 2, 3]
    assert h["loop_score"] == pytest.approx(sum(e["report"]["score"] for e in steps))
    names = [e["event"] for e in events(run)]
    assert names.index("stop") < names.index("holdout_start") < names.index("holdout_end") == len(names) - 1
    after = Counter(c["role"] for c in model.calls)
    for role in OTHER_ROLES:
        assert after[role] == seen["roles"][role], role                 # no Eval, Mutation, summary or Op. Orch call
    assert after["agent"] >= seen["roles"]["agent"] + 4                 # the agent keeps working
    assert after["cleaner"] == seen["roles"]["cleaner"] + 1             # one cleaner call cleans the copy
    assert isinstance(events(run, "holdout_cleaner")[0]["deletions"], list)


def test_training_folder_untouched(cfg, tmp_path):
    _, _, result, seen = run_with_holdout(cfg, tmp_path)
    assert tree_hashes(seen["agent"].dir) == seen["hashes"]
    copy = tmp_path / "run" / "holdout" / "agents" / result["selected"]
    assert copy.is_dir() and copy.resolve() != seen["agent"].dir.resolve()
    assert (tmp_path / "run" / "holdout" / "logs" / f"{result['selected']}.jsonl").is_file()


def test_copy_is_cleaned(cfg, tmp_path):
    def plant(op, agent):
        (agent.dir / agent.data_file).write_text(DATA_HEADER + "v3 = 8\n")
    _, _, result, seen = run_with_holdout(cfg, tmp_path, before_holdout=plant)
    copy = tmp_path / "run" / "holdout" / "agents" / result["selected"]
    assert "v3 = 8" in (seen["agent"].dir / "data.md").read_text()
    assert "v3 = 8" not in (copy / "data.md").read_text()
    assert events(tmp_path / "run", "holdout_cleaner")[0]["deletions"]


def test_special_file_is_not_copied(cfg, tmp_path):
    import os
    # a FIFO made in the last cycle (no cleaner runs after it): copying would open it and block for good
    _, _, result, _ = run_with_holdout(cfg, tmp_path, before_holdout=lambda op, a: os.mkfifo(a.dir / "pipe"))
    copy = tmp_path / "run" / "holdout" / "agents" / result["selected"]
    assert result["holdout"]["stopped"] == "done" and not (copy / "pipe").exists()


# ---- 4-6: no pick, a cap, errors --------------------------------------------------------------------------------
def test_no_pick_skips(cfg, tmp_path):
    op = Operation(cfg, ToyConnector(cfg), demo_model(cfg), tmp_path / "run", budget=TightBudget(cfg, after=5),
                   holdout=ToyConnector(cfg, HELD))
    result = op.run()
    assert result["selected"] is None and result["holdout"] == {"skipped": "no agent was selected"}
    assert json.loads((tmp_path / "run" / "final.json").read_text())["holdout"] == result["holdout"]
    assert not events(tmp_path / "run", "holdout_step")


class ArmedCap(CycleBudget):
    """Once armed, the cycle's dollars run out at the 2nd agent check."""

    def __init__(self, cfg):
        super().__init__(cfg)
        self.armed, self.seen = False, 0

    def _check(self, role, est, allowed, agent_id=None):
        if self.armed and role == "agent":
            self.seen += 1
            if self.seen >= 2:
                self.limit = 0.0
        super()._check(role, est, allowed, agent_id)


def test_cap_inside_holdout(cfg, tmp_path):
    budget = ArmedCap(cfg)
    _, _, result, _ = run_with_holdout(cfg, tmp_path, budget=budget,
                                       before_holdout=lambda op, a: setattr(budget, "armed", True))
    h = result["holdout"]
    assert h["stopped"] == "budget:cycle_usd" and h["steps_done"] < h["n_steps"] == 4
    final = json.loads((tmp_path / "run" / "final.json").read_text())
    assert final["reason"] == "max_loops" and final["selected"] == h["agent"]


class RaisingToy(ToyConnector):
    def run_step(self, agent_id, agent_dir, step):
        if step == 2:
            raise RuntimeError("broken step")
        return super().run_step(agent_id, agent_dir, step)


class BadCycleToy(ToyConnector):
    def begin_cycle(self, agent_ids):
        raise RuntimeError("no cycle")


def test_step_error_goes_on(cfg, tmp_path):
    _, _, result, _ = run_with_holdout(cfg, tmp_path, held=RaisingToy(cfg, HELD))
    steps = events(tmp_path / "run", "holdout_step")
    assert len(steps) == 4 and "broken step" in steps[2]["error"] and steps[1]["error"] is None
    assert result["holdout"]["stopped"] == "done"


def test_cycle_error_stops_holdout_only(cfg, tmp_path):
    _, _, result, _ = run_with_holdout(cfg, tmp_path, held=BadCycleToy(cfg, HELD))
    assert result["holdout"]["stopped"].startswith("error: RuntimeError: no cycle")
    assert result["reason"] == "max_loops" and result["selected"]


# ---- 7-8: the command line ---------------------------------------------------------------------------------------
def cli(*args):
    return subprocess.run([sys.executable, "run.py", "run", *args], cwd=ROOT, capture_output=True, text=True,
                          timeout=200)


def test_cli_bad_holdout_file(tmp_path):
    out = tmp_path / "runs"
    p = cli("--connector", "apex.env_connector", "--data", "tests/fixtures/chunks_small_7.json",
            "--holdout", "/nonexistent.json", "--fake", "--out", str(out))
    assert p.returncode == 2, p.stderr
    assert not out.exists() or not any(out.iterdir())


def test_cli_toy_holdout(tmp_path):
    values = tmp_path / "values.json"
    values.write_text(json.dumps(HELD))
    p = cli("--connector", "tests.fixtures.toy_connector", "--holdout", str(values), "--fake", "--max-loops", "1",
            "--out", str(tmp_path / "runs"))
    assert p.returncode == 0, p.stderr
    assert "holdout:" in p.stdout


def test_cli_market_holdout(tmp_path):
    p = cli("--connector", "apex.env_connector", "--data", "tests/fixtures/chunks_small_7.json",
            "--holdout", "tests/fixtures/chunks_holdout_7.json", "--fake", "--max-loops", "1",
            "--out", str(tmp_path / "runs"))
    assert p.returncode == 0, p.stderr
    run = next((tmp_path / "runs").iterdir())
    h = json.loads((run / "final.json").read_text())["holdout"]
    assert h["stopped"] == "done" and h["n_steps"] == 6
    assert h["target_source"] == "connector" and math.isfinite(h["target"])


# ---- 9: the held-out fixture -------------------------------------------------------------------------------------
def test_holdout_fixture():
    built = make_env_fixtures.build_holdout()
    assert built == json.loads((FIX / "chunks_holdout_7.json").read_text())

    def dates(d):
        return {x["date"] for x in d["history"]} | {x["date"] for s in d["steps"] for x in s["days"]}
    train = json.loads((FIX / "chunks_small_7.json").read_text())
    assert not dates(built) & dates(train)
    assert max(dates(built)) < min(dates(train))


# ---- changes after the review ----------------------------------------------------------------------------------
class TargetToy(ToyConnector):
    """A held-out toy with a target every score passes."""

    def target_score(self):
        return -1e9


def test_locked_files_are_skipped(cfg, tmp_path):
    import os
    locked = []

    def lock(op, agent):
        (agent.dir / "secret.txt").write_text("x")
        (agent.dir / "box").mkdir()
        (agent.dir / "box" / "in.txt").write_text("y")
        for path in (agent.dir / "secret.txt", agent.dir / "box"):
            os.chmod(path, 0)
            locked.append(path)
    try:
        _, _, result, _ = run_with_holdout(cfg, tmp_path, before_holdout=lock)
    finally:
        for path in locked:
            os.chmod(path, 0o700)
    h = result["holdout"]
    assert h["stopped"] == "done" and h["steps_done"] == 4
    assert sorted(Path(f).name for f in h["skipped_files"]) == ["box", "secret.txt"]


def test_full_walk_with_target_passes(cfg, tmp_path):
    _, _, result, _ = run_with_holdout(cfg, tmp_path, held=TargetToy(cfg, HELD))
    h = result["holdout"]
    assert h["passed"] is True and h["step_errors"] == 0 and h["target_source"] == "connector"


def test_cap_gives_no_verdict(cfg, tmp_path):
    budget = ArmedCap(cfg)
    _, _, result, _ = run_with_holdout(cfg, tmp_path, held=TargetToy(cfg, HELD), budget=budget,
                                       before_holdout=lambda op, a: setattr(budget, "armed", True))
    h = result["holdout"]
    assert h["stopped"] == "budget:cycle_usd" and h["passed"] is None and h["loop_score"] is not None


class LateBreakToy(TargetToy):
    def release(self, step):
        if step == 2:
            raise RuntimeError("release broke")
        super().release(step)


def test_error_stop_scores_like_cap(cfg, tmp_path):
    _, _, result, _ = run_with_holdout(cfg, tmp_path, held=LateBreakToy(cfg, HELD))
    h = result["holdout"]
    assert h["stopped"].startswith("error: RuntimeError: release broke") and h["steps_done"] == 2
    assert h["passed"] is None and h["loop_score"] is not None


def test_cli_empty_holdout_fails_early(tmp_path):
    values, out = tmp_path / "values.json", tmp_path / "runs"
    values.write_text("[]")
    p = cli("--connector", "tests.fixtures.toy_connector", "--holdout", str(values), "--fake", "--out", str(out))
    assert p.returncode == 2 and "holdout" in p.stderr
    assert not out.exists() or not any(out.iterdir())


def test_cli_same_file_refused(tmp_path):
    out = tmp_path / "runs"
    p = cli("--connector", "apex.env_connector", "--data", "tests/fixtures/chunks_small_7.json",
            "--holdout", str(FIX / "chunks_small_7.json"), "--fake", "--out", str(out))
    assert p.returncode == 2 and "same file" in p.stderr
    assert not out.exists() or not any(out.iterdir())


def test_log_failures_never_lose_training(cfg, tmp_path):
    for bad in ("holdout_start", "holdout_end"):
        model = demo_model(cfg)
        op = Operation(cfg, ToyConnector(cfg), model, tmp_path / bad, holdout=ToyConnector(cfg, HELD))
        event = op.log.event

        def flaky(name, *args, bad=bad, event=event, **kw):
            if name == bad:
                raise OSError("disk full")
            return event(name, *args, **kw)
        op.log.event = flaky
        result = op.run()
        assert result["selected"] and "holdout" in result
        if bad == "holdout_start":
            assert result["holdout"]["stopped"].startswith("error: OSError")
        else:
            assert "disk full" in result["holdout"]["write_error"]
            assert "holdout" in json.loads((tmp_path / bad / "final.json").read_text())


def test_step_errors_withhold_the_verdict(cfg, tmp_path):
    class RaisingTargetToy(RaisingToy, TargetToy):
        pass
    _, _, result, _ = run_with_holdout(cfg, tmp_path, held=RaisingTargetToy(cfg, HELD))
    h = result["holdout"]
    assert h["stopped"] == "done" and h["step_errors"] == 1 and h["passed"] is None
