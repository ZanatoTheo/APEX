"""What can go wrong in a live run at night. Fake models and fake HTTP only;
every test is hang-guarded and every child process is killed in `finally`."""
import json
import os
import queue
import random
import re
import signal
import subprocess
import sys
import threading
import time
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest

import run
from apex import config
from apex.env_connector.feed import load as load_feed
from apex.estimate import cycle_cost
from apex.fake_model import FakeModel
from apex.fake_run import demo_model
from apex.llm import LLMError, call_llm, cost_usd, make_client
from apex.operation import Operation
from environment import build_chunks, start
from tests.fixtures.toy_connector import ToyConnector

ROOT = Path(__file__).resolve().parent.parent
LIVE = ROOT / "configs" / "live.json"
ASSETS = ROOT / "environment" / "assets.json"
FINAL = "Current agents, best loop score first"
GO = [{"role": "user", "content": "go"}]


@pytest.fixture(autouse=True)
def hang_guard():
    def stuck(*_):
        raise AssertionError("test ran past 90 s")
    old = signal.signal(signal.SIGALRM, stuck)
    signal.alarm(90)
    yield
    signal.alarm(0)
    signal.signal(signal.SIGALRM, old)


def toy_cfg(**models):
    over = {"operation": {"agents": 3, "max_loops": 3, "max_cycles": 2}}
    if models:
        over["models"] = models
    return config.load(overrides=over)


def events(run_dir, kind=None):
    rows = [json.loads(line) for line in (Path(run_dir) / "log.jsonl").read_text().splitlines()]   # every line parses
    return [r for r in rows if kind is None or r["event"] == kind]


def ended_by(run_dir):
    return [a["ended_by"] for s in events(run_dir, "step") for a in s["agents"].values()]


class Wrapper:
    """The demo model, except where `plan(role, messages, n)` says "error", "junk" (non-JSON text) or gives another
    model. Gen 0 (the first orchestrator call) always passes: it has no fallback."""

    def __init__(self, cfg, plan):
        self.demo = demo_model(cfg)
        self.junk = FakeModel(cfg, {}, defaults={r: {"text": "not json at all {"} for r in config.ROLES})
        self.plan, self.n, self.failed, self.gen0 = plan, 0, 0, False

    def __call__(self, role, messages, **kw):
        self.n += 1
        if role == "orchestrator" and not self.gen0:
            self.gen0 = True
            return self.demo(role, messages, **kw)
        what = self.plan(role, messages, self.n)
        if what == "error":
            self.failed += 1
            raise LLMError("fake outage", retryable=True)
        if what == "junk":
            self.failed += 1
            return self.junk(role, messages, **kw)
        return (what or self.demo)(role, messages, **kw)


def run_toy(tmp_path, cfg, model, **kw):
    op = Operation(cfg, ToyConnector(cfg), model, tmp_path / "run", **kw)
    return op, op.run()


# ---- 1: a flaky model over a whole run ---------------------------------------------------------------------------
def test_flaky_model_run_still_ends(tmp_path):
    cfg, rng = toy_cfg(), random.Random(7)
    model = Wrapper(cfg, lambda role, m, n: rng.choice(["error", "junk"]) if rng.random() < 0.3 else None)
    op, result = run_toy(tmp_path, cfg, model)
    assert result["reason"] == "max_cycles"
    assert result["selected"] in [a.id for a in op.orch.agents]
    assert json.loads((op.run_dir / "final.json").read_text())["reason"] == "max_cycles"
    assert model.failed > 0 and "error" in ended_by(op.run_dir)


# ---- 2: an outage during the final pick ---------------------------------------------------------------------------
def test_outage_at_final_pick(tmp_path):
    cfg = toy_cfg()
    model = Wrapper(cfg, lambda role, m, n: "error" if role == "orchestrator" and FINAL in json.dumps(m) else None)
    op, result = run_toy(tmp_path, cfg, model)
    assert result["reason"] == "max_cycles" and result["fallback"] is True
    assert result["selected"] in [a.id for a in op.orch.agents]
    assert json.loads((op.run_dir / "final.json").read_text())["fallback"] is True


# ---- 3: a total outage from the start ------------------------------------------------------------------------------
def broken(role, messages, **kw):
    raise LLMError("fake outage: every call fails", retryable=True)


def test_total_outage_stops_fast(tmp_path):
    cfg = toy_cfg()
    op = Operation(cfg, ToyConnector(cfg), broken, tmp_path / "run")
    t0 = time.monotonic()
    with pytest.raises(LLMError):
        op.run()
    assert time.monotonic() - t0 < 10
    last = events(op.run_dir)[-1]
    assert last["event"] == "stop" and last["reason"].startswith("error: LLMError")


def test_total_outage_cli_exits_1(tmp_path, monkeypatch, capsys):
    import apex.fake_run
    monkeypatch.setattr(apex.fake_run, "demo_model", lambda cfg: broken)
    code = run.main(["run", "--connector", "tests.fixtures.toy_connector", "--fake", "--out", str(tmp_path)])
    assert code == 1 and "stopped: error: LLMError" in capsys.readouterr().err


# ---- 4: a network outage of minutes, with the live retry settings ----------------------------------------------
OK = (200, {"model": "muse-spark-1.3-contributor", "status": "completed",
            "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "back"}]}],
            "usage": {"input_tokens": 10, "output_tokens": 2}})


def scripted(replies):
    replies = list(replies)

    def handle(request):
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return httpx.Response(reply[0], json=reply[1])
    return handle


def live_client(handler, monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "sk-live-risk-test")
    cfg = config.load(LIVE)
    return cfg, make_client(cfg, http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_live_retries_ride_out_an_outage(monkeypatch):
    cfg, client = live_client(scripted([httpx.ReadTimeout("slow"), (429, {}), (500, {}), httpx.ConnectError("down"),
                                        (503, {}), OK]), monkeypatch)
    sleeps = []
    out = call_llm(client, cfg, "agent", GO, max_output_tokens=1000, sleep=sleeps.append)
    assert out["text"] == "back" and sleeps == [5, 10, 20, 40, 80]


def test_live_retries_give_up_cleanly(monkeypatch):
    cfg, client = live_client(scripted([(503, {})] * 7), monkeypatch)
    sleeps = []
    with pytest.raises(LLMError) as err:
        call_llm(client, cfg, "agent", GO, max_output_tokens=1000, sleep=sleeps.append)
    assert err.value.retryable and sleeps == [5, 10, 20, 40, 80, 160]


def test_agent_outage_ends_steps_not_the_run(tmp_path):
    cfg = toy_cfg()
    op, result = run_toy(tmp_path, cfg, Wrapper(cfg, lambda role, m, n: "error" if role == "agent" else None))
    assert result["reason"] == "max_cycles"
    assert ended_by(op.run_dir) and set(ended_by(op.run_dir)) == {"error"}


# ---- 5: the live models are priced and named right ---------------------------------------------------------------
def test_live_models_priced_and_named():
    cfg = config.load(LIVE)
    roles = cfg["models"]["roles"]
    assert {r["model_id"] for r in roles.values()} == {"muse-spark-1.3-contributor"}   # user, 2026-11-04
    for r in roles.values():
        assert cost_usd(cfg, r["model_id"], {"input_tokens": 1000, "output_tokens": 200}) > 0


# ---- 6-7: a run in a child process: progress reaches the pipe; a kill leaves readable traces --------------------
def start_run(tmp_path, **popen):
    cfg_file = tmp_path / "cfg.json"
    cfg_file.write_text(json.dumps({"operation": {"agents": 3}}))
    return subprocess.Popen(
        [sys.executable, str(ROOT / "run.py"), "run", "--connector", "tests.fixtures.slow_toy", "--fake",
         "--config", str(cfg_file), "--out", str(tmp_path / "runs")],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}, **popen)       # no PYTHONUNBUFFERED


class Lines:
    """The child's output lines, read in a thread so a wait has a deadline."""

    def __init__(self, proc):
        self.q, self.seen = queue.Queue(), []
        threading.Thread(target=lambda: [self.q.put(line) for line in proc.stdout], daemon=True).start()

    def wait_for(self, pattern, seconds=30):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                line = self.q.get(timeout=max(0.05, end - time.monotonic()))
            except queue.Empty:
                break
            self.seen.append(line)
            if re.search(pattern, line):
                return line
        raise AssertionError(f"no line matching {pattern!r} within {seconds} s; got {self.seen}")


def test_progress_reaches_the_pipe_while_running(tmp_path):
    proc = start_run(tmp_path)
    try:
        lines = Lines(proc)
        lines.wait_for(r"^run dir: ")
        lines.wait_for(r"^loop 1 cycle 1 ")
        assert proc.poll() is None                                  # still running: the lines were flushed
    finally:
        proc.kill()
        proc.wait(10)


def test_killed_run_leaves_readable_traces(tmp_path):
    proc = start_run(tmp_path, start_new_session=True)
    try:
        lines = Lines(proc)
        run_dir = Path(lines.wait_for(r"^run dir: ").split(": ", 1)[1].strip())
        lines.wait_for(r"^loop 1 cycle 1 ")
        os.killpg(proc.pid, signal.SIGTERM)
        assert proc.wait(10) != 0
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(10)
    assert any(r["event"] == "step" for r in events(run_dir))
    assert (run_dir / "config.json").is_file() and (run_dir / "agents").is_dir()
    with pytest.raises(ProcessLookupError):
        os.killpg(proc.pid, 0)                                      # nothing left in the group


# ---- 8: the full asset list builds ----------------------------------------------------------------------------------
def synthetic_csv(path, assets):
    """2021-2025: weekdays, BTC-USD every day, IWM from 2021-07-01, context missing on the 17th of a month."""
    rng, lines = random.Random(3), ["date,series,open,high,low,close,volume"]
    price = {t: 100.0 for t in assets["tradable"]}
    d = date(2021, 1, 1)
    while d <= date(2025, 12, 31):
        weekday = d.weekday() < 5
        for t in sorted(assets["tradable"]):
            if (t == "BTC-USD" or weekday) and not (t == "IWM" and d < date(2021, 7, 1)):
                p = price[t] = price[t] * (1 + rng.uniform(-0.02, 0.02))
                lines.append(f"{d},{t},{p:.6f},{p * 1.01:.6f},{p * 0.99:.6f},{p:.6f},1000")
        if weekday and d.day != 17:
            lines += [f"{d},{name},,,,{3 + rng.random():.4f}," for name in sorted(assets["context"])]
        d += timedelta(days=1)
    path.write_text("\n".join(lines) + "\n")


def test_full_asset_list_builds(tmp_path, monkeypatch, capsys):
    assets = json.loads(ASSETS.read_text())
    assert len(assets["tradable"]) == 13 and len(assets["context"]) == 3
    csv_path = tmp_path / "prices.csv"
    synthetic_csv(csv_path, assets)
    paths = build_chunks.build(csv_path, ASSETS, 1, 2025, 2022, tmp_path / "data", seed=1)
    for key in ("train", "holdout"):
        load_feed(paths[key])
    monkeypatch.setattr(run, "main", lambda cmd: 0)
    common = ["--csv", str(csv_path), "--build-out", str(tmp_path / "data"), "--seed", "1", "--skip-holdout"]
    assert start.main(common) == 0
    assert "worst case: 13 cycles" in capsys.readouterr().out
    cfg = config.load()
    bound = 4 * min(cycle_cost(cfg, 28)["total"], cfg["budget"]["cycle_usd"])
    for extra in (["--max-cycles", "4"], ["--config", str(LIVE)]):
        assert start.main(common + extra) == 0
        assert f"worst case: 4 cycles, at most ${bound:.2f}" in capsys.readouterr().out


# ---- 9: the key never lands on disk ---------------------------------------------------------------------------------
def test_key_never_on_disk(tmp_path, monkeypatch, capsys):
    key = "sk-FAKE-night-key-7f3e9a"
    monkeypatch.setenv("MODEL_API_KEY", key)
    cfg = toy_cfg(retries=0)
    leaky = make_client(cfg, http_client=httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(500, json={"error": {"message": f"upstream rejected key {key}"}}))))

    def via_api(role, messages, **kw):
        return call_llm(leaky, cfg, role, messages, sleep=lambda s: None, **kw)
    op, _ = run_toy(tmp_path, cfg, Wrapper(cfg, lambda role, m, n: via_api if n % 3 == 0 else None),
                    progress=print)
    files = [p for p in op.run_dir.rglob("*") if p.is_file()]
    assert any(b"HTTP 500" in p.read_bytes() for p in files)       # the leaky path was used
    for p in files:
        assert key.encode() not in p.read_bytes(), p
    out = capsys.readouterr()
    assert key not in out.out + out.err
