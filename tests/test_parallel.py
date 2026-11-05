"""operation.parallel_agents: the agents of one step work at the same time.
Toy connector, demo model, fixtures only: no real API call."""
import json
import threading
import time
from pathlib import Path

import pytest

from apex import config, operation
from apex.env_connector import Connector
from apex.fake_run import demo_model
from apex.operation import Operation
from tests.fixtures.toy_connector import ToyConnector

ROOT = Path(__file__).resolve().parent.parent
F7 = ROOT / "tests" / "fixtures" / "chunks_small_7.json"


def cfg_for(parallel, agents=4, cycles=1):
    return config.load(overrides={"operation": {"agents": agents, "max_cycles": cycles,
                                                "parallel_agents": parallel}})


class Slow:
    """The demo model, but every agent call takes `delay` seconds (like a real call, in any thread)."""

    def __init__(self, cfg, delay):
        self.inner, self.delay = demo_model(cfg), delay
        self.lock = threading.Lock()

    @property
    def calls(self):
        return self.inner.calls

    def __call__(self, role, messages, **kw):
        if role == "agent":
            time.sleep(self.delay)
        with self.lock:                      # the demo script is a queue: keep its pops in order
            return self.inner(role, messages, **kw)


def run(tmp_path, parallel, name, delay=0.0, agents=4):
    cfg = cfg_for(parallel, agents)
    op = Operation(cfg, ToyConnector(cfg), Slow(cfg, delay), tmp_path / name)
    t0 = time.monotonic()
    result = op.run()
    return op, result, time.monotonic() - t0


def ends(run_dir, agent_id):
    p = Path(run_dir) / "logs" / f"{agent_id}.jsonl"
    return [json.loads(x)["step"] for x in p.read_text().splitlines() if json.loads(x).get("event") == "end"]


# 1
@pytest.mark.parametrize("bad", [0, -1, "4", True, 1.5])
def test_config(tmp_path, bad):
    assert config.load()["operation"]["parallel_agents"] == 1
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"operation": {"parallel_agents": bad}}))
    with pytest.raises(config.ConfigError):
        config.load(p)


# 2
def test_parallel_run_ends_like_sequential(tmp_path):
    op1, r1, _ = run(tmp_path, 1, "seq")
    op4, r4, _ = run(tmp_path, 4, "par")
    assert r4["reason"] == r1["reason"] == "max_cycles" and r4["cycles"] == r1["cycles"] == 1
    n_steps = len([1 for x in (op4.run_dir / "log.jsonl").read_text().splitlines() if '"event": "step"' in x])
    for d in sorted((op4.run_dir / "agents").iterdir()):
        assert ends(op4.run_dir, d.name) == list(range(n_steps)), d.name


# 3
def test_parallel_is_faster(tmp_path):
    _, _, t_seq = run(tmp_path, 1, "seq", delay=0.2)
    _, _, t_par = run(tmp_path, 4, "par", delay=0.2)
    assert t_par < 0.5 * t_seq, (t_par, t_seq)


# 4
def test_one_agent_bug_others_finish(tmp_path, monkeypatch):
    real = operation.call_agent

    def flaky(agent, report, step, *a, **kw):
        if agent.id.endswith("-02") and step == 1:
            raise RuntimeError("BUG-X")
        return real(agent, report, step, *a, **kw)

    monkeypatch.setattr(operation, "call_agent", flaky)
    for mode, name in ((1, "seq"), (4, "par")):
        with pytest.raises(RuntimeError, match="BUG-X"):          # Operation.run logs the stop and re-raises a bug
            run(tmp_path, mode, name)
        stop = [json.loads(x) for x in (tmp_path / name / "log.jsonl").read_text().splitlines()][-1]
        assert stop["event"] == "stop" and "BUG-X" in stop["reason"]
    par = tmp_path / "par"
    others = [d.name for d in (par / "agents").iterdir() if not d.name.endswith("-02")]
    assert len(others) == 3 and all(1 in ends(par, a) for a in others)


# 5
def test_data_files_built_once(monkeypatch):
    conn = Connector(config.load(), F7)
    conn.release(3)
    real, count = conn.feed.write_files, []

    def slow(upto, out):
        count.append(upto)
        time.sleep(0.1)
        return real(upto, out)

    monkeypatch.setattr(conn.feed, "write_files", slow)
    barrier = threading.Barrier(8)
    got = []

    def ask():
        barrier.wait()
        got.append(conn.script_files("a1", 0))

    threads = [threading.Thread(target=ask) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert count == [0] and len(got) == 8
    assert all(g == got[0] for g in got) and all(Path(p).is_file() for p in got[0].values())
