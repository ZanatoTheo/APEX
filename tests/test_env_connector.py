"""The 2025 market connector behind the interface.
The backtests here run in the real sandbox; Wayback uses fake HTTP; models are fake."""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from apex import config
from apex.agent import Agent
from apex.connector import check_connector, load_connector
from apex.env_connector import TARGET_MARGIN, Connector
from apex.env_connector.backtest import FEE, START_CASH, BuyAndHold, Portfolio, equal_weight, run_days, sixty_forty
from apex.operation import split_cycles
from apex.tools.files import ToolError
from tests.test_env_wayback import FakeHTTP

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"
F7, F2 = FIX / "chunks_small_7.json", FIX / "chunks_small_2.json"


@pytest.fixture
def cfg():
    return config.load()


@pytest.fixture
def conn(cfg):
    return Connector(cfg, F7)


def agent(tmp_path, conn, strategy=None, agent_id="a1"):
    files = conn.starter_files()
    if strategy is not None:
        files = {"strategy.py": strategy}
    return Agent.create(tmp_path / "agents", tmp_path / "logs", agent_id, "# axioms\n", files)


def tool(conn, name, step, agent_id="a1", agent_dir="/nowhere"):
    return next(t for t in conn.tools(agent_id, agent_dir, step) if t.name == name)


def report_rows(conn, agent_id="a1"):
    return json.loads(tool(conn, "backtest_report", conn.current, agent_id).handler({}))


def test_interface(cfg, conn):
    check_connector(conn)
    assert conn.n_steps() == 6 and conn.steps_per_cycle() == 4
    assert Connector(cfg, F2).steps_per_cycle() == 14
    assert load_connector("apex.env_connector", cfg, str(F2)).n_steps() == 18
    assert load_connector("apex.env_connector", cfg, json.loads(F7.read_text())).n_steps() == 6


def test_brief_holds_no_data(conn):
    brief = conn.brief()
    assert "7 days" in brief and "/data/prices.csv" in brief and "strategy.py" in brief
    assert not re.search(r"20\d\d-", brief) and not re.search(r"\d+\.\d\d", brief)
    for ticker in ("SPY", "QQQ", "TLT", "GLD", "BTC", "IEF", "XLE", "equity", "bond"):
        assert not re.search(rf"\b{ticker}\b", brief, re.I)


def test_cleaning_patterns(conn):
    rules = conn.cleaning_rules()
    hit = lambda s: any(re.search(p, s) for p in rules["patterns"])
    assert rules["data_file"] == "data.md" and "*.csv" in rules["file_globs"]
    assert hit("on 2025-03-04 it fell") and hit("level 512.34")
    assert not hit("risk 0.25 of cash") and not hit("window = 20")


def test_run_step_with_the_starter(cfg, conn, tmp_path):
    a = agent(tmp_path, conn)
    conn.begin_cycle([a.id])
    conn.release(0)
    rep = conn.run_step(a.id, a.dir, 0)
    assert all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in rep.values())
    assert rep["days"] == 5 and rep["errors"] == 0 and rep["trades"] > 0 and rep["fees"] > 0
    assert conn.cycle_score(a.id) == pytest.approx(rep["excess_return"])
    assert rep["excess_return"] == pytest.approx(rep["cycle_return"] - rep["benchmark_cycle_return"])
    conn.begin_cycle([a.id])
    assert conn.cycle_score(a.id) == 0.0


def test_strategy_never_sees_the_day_it_trades(cfg, conn, tmp_path):
    peek = ('import json\n'
            'def weights(history):\n'
            '    last_data = open("/data/prices.csv").read().strip().splitlines()[-1].split(",")[0]\n'
            '    with open("/work/peek.log", "a") as f:\n'
            '        f.write(json.dumps([len(history.close), str(history.close.index[-1].date()),\n'
            '                            str(history.today.date()), last_data]) + "\\n")\n'
            '    return None\n')
    a = agent(tmp_path, conn, peek)
    conn.begin_cycle([a.id])
    conn.release(1)
    rep = conn.run_step(a.id, a.dir, 1)
    lines = [json.loads(x) for x in (a.dir / "peek.log").read_text().splitlines()]
    assert len(lines) == rep["days"] == 7
    for n, (rows, last, today, last_data) in enumerate(lines):
        assert last < today and last_data <= conn.feed.step_end(0)
        assert rows == lines[0][0] + n                                  # one more day each call


def test_failures_go_to_cash(cfg, tmp_path):
    cases = {
        "tuesday": ('def weights(h):\n    if h.today.weekday() == 1:\n        raise ValueError("no tuesdays")\n'
                    '    return {"Asset C": 1.0}\n'),
        "import": 'import nosuchmodule\n',
        "print": 'def weights(h):\n    print("noise")\n    return {"Asset C": 1.0}\n',
        "loop": 'def weights(h):\n    while True:\n        pass\n',
        "net": ('import socket\ndef weights(h):\n    try:\n        socket.create_connection(("1.1.1.1", 80), 2)\n'
                '        open("/work/net.txt", "w").write("open")\n    except OSError:\n'
                '        open("/work/net.txt", "w").write("blocked")\n    return None\n'),
    }
    out = {}
    for name, code in cases.items():
        c = Connector(config.load(overrides={"tools": {"script_timeout_s": 5}}), F7)
        a = agent(tmp_path / name, c, code)
        c.begin_cycle([a.id])
        c.release(1)
        out[name] = (c.run_step(a.id, a.dir, 1), report_rows(c), a)
    rep, rows, _ = out["tuesday"]
    assert rep["errors"] == 1 and [r["weights_applied"] for r in rows["days"] if r["date"] == "2025-01-07"] == [{}]
    rep, rows, _ = out["import"]
    assert rep["trades"] == 0 and rep["cash_share"] == 1.0 and "fatal" in json.dumps(rows["errors"])
    rep, _, _ = out["print"]
    assert rep["errors"] == 0 and rep["cash_share"] < 0.05
    rep, rows, _ = out["loop"]
    assert rep["errors"] >= 1 and "deadline" in json.dumps(rows["errors"]) and rep["trades"] == 0
    _, _, a = out["net"]
    assert (a.dir / "net.txt").read_text() == "blocked"


def test_read_prices_is_gated(cfg, conn):
    conn.release(2)
    read = tool(conn, "read_prices", 2)
    conn.release(4)
    rows = json.loads(read.handler({"series": ["Asset C"], "start": "2025-01-01"}))["rows"]
    assert rows and max(r["date"] for r in rows) == conn.feed.step_end(2)
    conn.release(1)
    rows = json.loads(read.handler({"series": ["Asset C", "Oil"], "start": "2025-01-01"}))["rows"]
    assert max(r["date"] for r in rows) <= conn.feed.step_end(1)
    listing = json.loads(read.handler({}))
    assert "Asset A" in listing["tradable"] and "Oil" in listing["context"]
    assert listing["last_date"] == conn.feed.step_end(1)
    with pytest.raises(ToolError, match="series"):                      # ToolSet.run turns it into "error: …"
        read.handler({"series": ["Nope"]})


def test_read_prices_pages(cfg, conn, monkeypatch):
    import apex.env_connector as env
    monkeypatch.setattr(env, "READ_ROWS", 50)                           # the fixture is smaller than one real page
    conn.release(5)
    read = tool(conn, "read_prices", 5)
    args = {"series": ["Asset A", "Asset C", "Oil"], "start": "2024-11-01"}
    first = json.loads(read.handler(args))
    assert len(first["rows"]) <= 50 and first["next_start"]
    second = json.loads(read.handler({**args, "start": first["next_start"]}))
    assert min(r["date"] for r in second["rows"]) == first["next_start"] > max(r["date"] for r in first["rows"])


def test_wayback_tool_uses_the_built_step(cfg, conn):
    http = FakeHTTP()
    conn.http = http
    conn.release(2)
    fetch = tool(conn, "wayback_fetch", 2)
    conn.release(5)
    fetch.handler({"url": "https://www.reuters.com/x"})
    assert f"to={conn.feed.step_end(2).replace('-', '')}235959" in http.urls[0]


def test_target_is_sixty_forty_plus_margin(cfg, conn):
    f = conn.feed
    total = 0.0
    for steps in split_cycles(f.n_steps(), conn.steps_per_cycle()):
        days = [d for k in steps for d in f.days(k)]
        r = {}
        for name, targets, fee in (("ref", sixty_forty(f.meta["assets"]), FEE),
                                   ("bench", equal_weight(list(f.meta["assets"])), 0.0)):
            p = Portfolio(START_CASH)
            rows = run_days(BuyAndHold(targets), days, p, dict(f.last_close(steps[0] - 1)), fee)
            r[name] = rows[-1]["value_close"] / START_CASH - 1
        total += r["ref"] - r["bench"]
    assert conn.target_score() == pytest.approx(total + TARGET_MARGIN)


def test_script_files(cfg, conn):
    conn.release(4)
    conn.release(0)
    files = conn.script_files("a1", 0)
    assert set(files) == {"/data/prices.csv", "/data/context.csv", "/data/replay.py"}   # replay: the read-only helper
    last = open(files["/data/prices.csv"]).read().strip().splitlines()[-1].split(",")[0]
    assert last == conn.feed.step_end(0)


def run_cli(tmp_path, data):
    cfg_file = tmp_path / "small.json"
    cfg_file.write_text(json.dumps({"operation": {"agents": 3, "survivors": 1}}))
    return subprocess.run([sys.executable, str(ROOT / "run.py"), "run", "--connector", "apex.env_connector",
                           "--data", str(data), "--config", str(cfg_file), "--fake", "--max-loops", "1",
                           "--out", str(tmp_path / "runs")], cwd=ROOT, capture_output=True, text=True, timeout=900,
                          env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})


@pytest.mark.parametrize("data", [F7, F2], ids=["7days", "2days"])
def test_fake_run_end_to_end(tmp_path, data):
    out = run_cli(tmp_path, data)
    assert out.returncode == 0, out.stderr[-2000:]
    assert "stopped:" in out.stdout
    run_dir = next((tmp_path / "runs").iterdir())
    rows = [json.loads(x) for x in (run_dir / "log.jsonl").read_text().splitlines()]
    gen0 = next(r for r in rows if r["event"] == "gen0")
    assert gen0["target_source"] == "connector" and isinstance(gen0["target"], float)
    steps = [r for r in rows if r["event"] == "step"]
    assert len(steps) == json.loads(Path(data).read_text())["meta"]["step_ends"].__len__()
    assert all(r["report"]["days"] >= 1 for s in steps for r in s["agents"].values())


# ---- changes after the review ----------------------------------------------------------------------------------
def test_huge_weight_does_not_kill_the_runner(cfg, conn, tmp_path):
    a = agent(tmp_path, conn, 'def weights(h):\n    return {"Asset C": 10**400, "Asset A": 0.5}\n')
    conn.begin_cycle([a.id])
    conn.release(1)
    rep = conn.run_step(a.id, a.dir, 1)
    assert rep["errors"] == 0 and rep["trades"] > 0                     # 10**400 is clipped to 0, A still bought


def test_more_data_formats_are_cleaned(conn):
    rules = conn.cleaning_rules()
    hit = lambda s: any(re.search(p, s) for p in rules["patterns"])
    for s in ("on 2025/03/04", "20250304 close", "level 512.3", "level 1024.75"):
        assert hit(s), s
    for s in ("alpha = 0.05", "lookback = 20", "scale = 12.5", "year 252 days"):
        assert not hit(s), s
    assert hit("level 512.00")                                          # still a price
    for s in ("ann = 252.0", "pct * 100.0", "cap = 1000.0"):            # code constants: left alone
        assert not hit(s), s
    for g in ("*.json", "*.tsv", "*.txt"):
        assert g in rules["file_globs"]
    brief = conn.brief()
    assert "*.json" in brief and "decimal" in brief


def test_data_folders_capped_and_reports_cleared(cfg, conn, tmp_path):
    for k in range(6):
        conn.release(k)
        conn.script_files("a1", k)
    assert len(conn._files) <= 3 and conn.current in conn._files and conn.current - 1 in conn._files
    a = agent(tmp_path, conn)
    conn.begin_cycle([a.id])
    conn.release(0)
    conn.run_step(a.id, a.dir, 0)
    conn.release(1)
    (a.dir / "strategy.py").unlink()
    (a.dir / "strategy.py").mkdir()                                     # not a file: the step is cash
    conn.run_step(a.id, a.dir, 1)
    assert report_rows(conn)["step"] == 1


def test_bad_date_in_data_never_reaches_the_runner(cfg):
    d = json.loads(F7.read_text())
    d["steps"][-1]["days"][-1]["date"] = "2025-02-30"
    with pytest.raises(Exception, match="date"):
        Connector(cfg, d)
