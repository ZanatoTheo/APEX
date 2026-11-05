"""environment/: the price fetch (fake HTTP only), the chunk builder, the held-out file, start.py and the
config defaults. No network, no real API call."""
import csv
import json
import math
import signal
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from apex import config
from apex.connector import load_connector
from apex.estimate import cycle_cost
from environment import build_chunks, fetch_prices
from tests.fixtures import make_prices_small

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"
CSV, ASSETS = FIX / "prices_small.csv", FIX / "assets_small.json"
TICKERS = ("SPY", "TLT", "BTC")


@pytest.fixture(autouse=True)
def guard():
    def stuck(*_):
        raise AssertionError("the test ran past 280 s")
    old = signal.signal(signal.SIGALRM, stuck)
    signal.alarm(280)
    yield
    signal.alarm(0)
    signal.signal(signal.SIGALRM, old)


def built(tmp_path, gap=1, **kw):
    out = tmp_path / f"gap{gap}"
    args = dict(time_gap=gap, year=2025, holdout_year=2022, out=out, seed=5)
    args.update(kw)
    return build_chunks.build(CSV, ASSETS, **args)


def read(path):
    return json.loads(Path(path).read_text())


def step_days(d):
    return [x for s in d["steps"] for x in s["days"]]


def all_dates(d):
    return [x["date"] for x in d["history"]] + [x["date"] for x in step_days(d)]


def csv_closes():
    out = {}
    for r in csv.DictReader(open(CSV)):
        out.setdefault(r["series"], {})[r["date"]] = float(r["close"])
    return out


def test_fixture_is_reproducible():
    assert make_prices_small.csv_text() == CSV.read_text()


# ---- 1-2: the cut ------------------------------------------------------------------------------------------------
def test_seven_day_ends_are_sundays(tmp_path):
    ends = read(built(tmp_path, 7)["train"])["meta"]["step_ends"]
    assert ends == ["2025-01-05", "2025-01-12", "2025-01-19", "2025-01-26", "2025-02-02", "2025-02-04"]
    days = [date.fromisoformat(e) for e in ends]
    assert all(d.weekday() == 6 for d in days[:-1])
    assert all((b - a).days == 7 for a, b in zip(days[:-2], days[1:-1]))


def test_same_days_at_7_2_1(tmp_path):
    cfg = config.load()
    files = {g: built(tmp_path, g)["train"] for g in (7, 2, 1)}
    flat = {g: step_days(read(p)) for g, p in files.items()}
    assert flat[7] == flat[2] == flat[1] and len(flat[1]) == 35
    assert all(len(s["days"]) == 1 for s in read(files[1])["steps"])
    spc = {g: load_connector("apex.env_connector", cfg, str(p)).steps_per_cycle() for g, p in files.items()}
    assert spc == {7: 4, 2: 14, 1: 28}


# ---- 3-6: what the files hold ------------------------------------------------------------------------------------
def test_no_real_ticker_in_files(tmp_path):
    paths = built(tmp_path)
    for key in ("train", "holdout"):
        text = Path(paths[key]).read_text()
        for t in TICKERS:
            assert t not in text, (key, t)


def test_rebased_to_100_with_same_moves(tmp_path):
    paths = built(tmp_path)
    mapping = read(paths["mapping"])
    raw = csv_closes()
    for key in ("train", "holdout"):
        days = read(paths[key])["history"] + step_days(read(paths[key]))
        for letter, ticker in mapping.items():
            series = [(x["date"], x["tradable"][letter]["close"]) for x in days if letter in x["tradable"]]
            assert series[0][1] == pytest.approx(100.0)
            d0 = series[0][0]
            for d, c in series:
                assert c / 100.0 == pytest.approx(raw[ticker][d] / raw[ticker][d0], rel=1e-6)


def test_context_kept(tmp_path):
    d = read(built(tmp_path)["train"])
    assert d["meta"]["context"] == ["Oil", "US 10y yield"]
    raw = csv_closes()
    for x in step_days(d):
        for name, v in x["context"].items():
            assert v == pytest.approx(raw[name][x["date"]])


def test_one_mapping_for_both_files(tmp_path):
    paths = built(tmp_path)
    mapping = read(paths["mapping"])
    assert sorted(mapping.values()) == ["BTC-USD", "SPY", "TLT"]
    assert read(paths["train"])["meta"]["assets"] == read(paths["holdout"])["meta"]["assets"]
    equity = [a for a, m in read(paths["train"])["meta"]["assets"].items() if m["class"] == "equity"]
    assert equity == [a for a, t in mapping.items() if t == "SPY"]
    assert read(built(tmp_path / "again")["mapping"]) == mapping                    # same seed, same mapping
    assert Path(paths["mapping"]).parent == tmp_path / "gap1"
    assert "apex" not in Path(paths["mapping"]).relative_to(tmp_path).parts


# ---- 7-8: the held-out file ----------------------------------------------------------------------------------------
def test_files_share_no_day(tmp_path):
    paths = built(tmp_path)
    train, held = read(paths["train"]), read(paths["holdout"])
    assert not set(all_dates(train)) & set(all_dates(held))
    assert min(all_dates(train)) > "2022-12-31"
    assert all(x["date"].startswith("2022") for x in step_days(held))
    assert max(x["date"] for x in held["history"]) <= "2021-12-31"
    assert all(x["date"].startswith("2025") for x in step_days(train))


def test_overlap_refused(tmp_path):
    paths = built(tmp_path)
    train, held = read(paths["train"]), read(paths["holdout"])
    held["history"].append(dict(train["history"][0]))
    with pytest.raises(ValueError, match="share"):
        build_chunks.check_apart(train, held)
    with pytest.raises(ValueError):
        built(tmp_path / "bad", holdout_year=2025)


def test_connector_loads_both(tmp_path):
    cfg = config.load()
    paths = built(tmp_path)
    for key in ("train", "holdout"):
        conn = load_connector("apex.env_connector", cfg, str(paths[key]))
        assert math.isfinite(conn.target_score())


# ---- 9: the fetch, with fake HTTP ---------------------------------------------------------------------------------
def yahoo(closes, adj):
    return json.dumps({"chart": {"error": None, "result": [{
        "meta": {"gmtoffset": -18000},
        "timestamp": [1735828200 + 86400 * i for i in range(len(closes))],          # 2025-01-02 14:30 UTC, …
        "indicators": {"quote": [{"open": [c - 1 for c in closes], "high": [c + 1 for c in closes],
                                  "low": [c - 2 for c in closes], "close": closes, "volume": [100] * len(closes)}],
                       "adjclose": [{"adjclose": adj}]}}]}})


class FakeHTTP:
    def __init__(self, fail=None):
        self.urls, self.fail = [], fail

    def __call__(self, url):
        self.urls.append(url)
        if self.fail and self.fail in url:
            return 404, "not found"
        if "fred" in url:
            return 200, "observation_date,DGS10\n2025-01-02,4.5\n2025-01-03,.\n"
        return 200, yahoo([10.0, 11.0], [9.0, 9.9])


def test_fetch_scales_by_adjclose():
    rows = fetch_prices.fetch({"tradable": {"SPY": "equity"}, "context": {}}, "2025-01-01", "2025-01-10",
                              http=FakeHTTP())
    assert [r["date"] for r in rows] == ["2025-01-02", "2025-01-03"]
    assert [r["close"] for r in rows] == pytest.approx([9.0, 9.9])
    assert rows[0]["open"] == pytest.approx(9 * 0.9) and rows[0]["volume"] == 100


def test_fetch_skips_fred_dots():
    rows = fetch_prices.fetch({"tradable": {}, "context": {"US 10y yield": "DGS10"}}, "2025-01-01", "2025-01-10",
                              http=FakeHTTP())
    assert [(r["date"], r["series"], r["close"]) for r in rows] == [("2025-01-02", "US 10y yield", 4.5)]


def test_fetch_error_names_ticker():
    with pytest.raises(fetch_prices.FetchError, match="QQQ"):
        fetch_prices.fetch({"tradable": {"SPY": "equity", "QQQ": "equity"}, "context": {}}, "2025-01-01",
                           "2025-01-10", http=FakeHTTP(fail="QQQ"))


def test_dry_run_sends_nothing(capsys):
    http = FakeHTTP()
    assert fetch_prices.main(["--dry-run"], http=http) == 0
    assert http.urls == []
    printed = [line for line in capsys.readouterr().out.splitlines() if line.startswith("https://")]
    assert len(printed) == 16


# ---- 10-11: assets and config ------------------------------------------------------------------------------------
def test_assets_json():
    a = json.loads((ROOT / "environment" / "assets.json").read_text())
    assert len(a["tradable"]) == 13 and {"equity", "bond"} <= set(a["tradable"].values())
    assert len(a["context"]) == 3


def test_default_config_fits_the_cap():
    cfg = config.load()
    assert cfg["budget"]["cycle_usd"] == 2.5
    assert cycle_cost(cfg, 28)["total"] <= 2.5


# ---- 12: start.py end to end ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("gap", [1, 7, 2])
def test_start_end_to_end(tmp_path, gap):
    small = tmp_path / "small.json"
    small.write_text(json.dumps({"operation": {"agents": 3}}))
    p = subprocess.run([sys.executable, "environment/start.py", "--csv", str(CSV), "--assets", str(ASSETS),
                        "--time-gap", str(gap), "--seed", "5", "--build-out", str(tmp_path / "data"),
                        "--fake", "--max-loops", "1", "--config", str(small), "--out", str(tmp_path / "runs")],
                       cwd=ROOT, capture_output=True, text=True, timeout=260)
    assert p.returncode == 0, p.stderr[-2000:]
    assert "holdout:" in p.stdout


# ---- changes after the review ----------------------------------------------------------------------------------
def chart(quote, adj=None, n=None):
    n = n or len(quote["close"])
    ind = {"quote": [quote]}
    if adj is not None:
        ind["adjclose"] = [{"adjclose": adj}]
    return json.dumps({"chart": {"error": None, "result": [{
        "meta": {"gmtoffset": -18000}, "timestamp": [1735828200 + 86400 * i for i in range(n)], "indicators": ind}]}})


class ChartHTTP:
    def __init__(self, text):
        self.text = text

    def __call__(self, url):
        return 200, self.text


SPY_ONLY = {"tradable": {"SPY": "equity"}, "context": {}}


def test_partial_adjclose_bar_dropped(capsys):
    q = {"open": [10, 11, 12], "high": [10, 11, 12], "low": [10, 11, 12], "close": [10, 11, 12], "volume": [1, 1, 1]}
    rows = fetch_prices.fetch(SPY_ONLY, "2025-01-01", "2025-01-10", http=ChartHTTP(chart(q, [9.0, None, 11.4])))
    assert [r["close"] for r in rows] == pytest.approx([9.0, 11.4])
    assert [r["date"] for r in rows] == ["2025-01-02", "2025-01-04"]
    assert "1 bar" in capsys.readouterr().err


def test_bar_order_holds_with_missing_fields():
    q = {"open": [100.0], "high": [100.5], "low": [None], "close": [101.0], "volume": [None]}
    (row,) = fetch_prices.fetch(SPY_ONLY, "2025-01-01", "2025-01-10", http=ChartHTTP(chart(q)))
    assert row["high"] >= max(row["open"], row["close"]) and row["low"] <= min(row["open"], row["close"])
    assert row["volume"] == 0


def test_short_yahoo_arrays_are_fetch_error():
    q = {"open": [1, 1], "high": [1, 1], "low": [1, 1], "close": [1, 1], "volume": [1, 1]}
    with pytest.raises(fetch_prices.FetchError, match="SPY"):
        fetch_prices.fetch(SPY_ONLY, "2025-01-01", "2025-01-10", http=ChartHTTP(chart(q, [1.0])))


def test_load_csv_skips_and_repairs(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("date,series,open,high,low,close,volume\n"
                   "2025-01-02,SPY,10,11,9,10,5\n"
                   "2025-01-03,SPY,10,11,9,nan,5\n"
                   "2025-01-04,SPY,10,inf,9,10,5\n"
                   "2025-01-05,SPY,10,9,11,10.5,5\n"
                   "2025-01-02,TLT,10,11,9,10,5\n")
    days = build_chunks.load_csv(bad, {"tradable": {"SPY": "equity", "TLT": "bond"}, "context": {}})
    spy = {d: v["tradable"]["SPY"] for d, v in days.items() if "SPY" in v["tradable"]}
    assert sorted(spy) == ["2025-01-02", "2025-01-05"]
    fixed = spy["2025-01-05"]
    assert fixed["high"] == 11 and fixed["low"] == 9


def test_failed_build_leaves_no_file(tmp_path, monkeypatch):
    def refuse(path):
        raise ValueError("refused")
    monkeypatch.setattr(build_chunks, "load_feed", refuse)
    with pytest.raises(ValueError, match="refused"):
        built(tmp_path)
    assert not list((tmp_path / "gap1").glob("*.json*")) and not list((tmp_path / "gap1").glob("*.tmp"))


def test_mapping_kept_across_builds(tmp_path):
    first = read(built(tmp_path, seed=None)["mapping"])
    assert read(built(tmp_path, seed=None)["mapping"]) == first                     # same tickers: kept
    again = read(built(tmp_path, seed=None, new_mapping=True)["mapping"])
    assert sorted(again.values()) == sorted(first.values())
    two = tmp_path / "two.json"
    two.write_text(json.dumps({"tradable": {"SPY": "equity", "TLT": "bond"}, "context": {"Oil": "DCOILWTICO"}}))
    other = build_chunks.build(CSV, two, time_gap=1, year=2025, holdout_year=2022, out=tmp_path / "gap1")
    assert sorted(read(other["mapping"]).values()) == ["SPY", "TLT"]               # other tickers: a new one


def test_rare_classes_are_generic(tmp_path):
    classes = {m["class"] for m in read(built(tmp_path)["train"])["meta"]["assets"].values()}
    assert classes <= {"equity", "bond", "other"} and "other" in classes


def test_cut_starts_late_and_long_gap():
    days = [{"date": f"2025-01-{d:02d}", "tradable": {}, "context": {}} for d in range(15, 32)]
    assert build_chunks.cut(days, 2025, 7)[0]["step_end"] == "2025-01-19"
    steps = build_chunks.cut(days, 2025, 400)
    assert len(steps) == 1 and steps[0]["step_end"] == "2025-01-31" and len(steps[0]["days"]) == 17


def test_start_defaults_and_bound(tmp_path, monkeypatch, capsys):
    from environment import start
    seen = []
    monkeypatch.setattr(start.run, "main", lambda argv: seen.append(argv) or 0)
    assert start.main(["--csv", str(CSV), "--assets", str(ASSETS), "--seed", "5", "--build-out",
                       str(tmp_path / "data"), "--fake"]) == 0
    argv = seen[0]
    assert argv[argv.index("--max-loops") + 1] == "1"
    assert "worst case" in capsys.readouterr().out


def test_start_checks_config_before_build(tmp_path):
    out = tmp_path / "data"
    p = subprocess.run([sys.executable, "environment/start.py", "--csv", str(CSV), "--assets", str(ASSETS),
                        "--build-out", str(out), "--fake", "--max-loops", "0"],
                       cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert p.returncode == 2
    assert not out.exists() or not any(out.iterdir())


def test_start_holdout_none(tmp_path):
    small = tmp_path / "small.json"
    small.write_text(json.dumps({"operation": {"agents": 3}}))
    p = subprocess.run([sys.executable, "environment/start.py", "--csv", str(CSV), "--assets", str(ASSETS),
                        "--time-gap", "7", "--holdout-year", "none", "--seed", "5", "--build-out",
                        str(tmp_path / "data"), "--fake", "--config", str(small), "--out", str(tmp_path / "runs")],
                       cwd=ROOT, capture_output=True, text=True, timeout=260)
    assert p.returncode == 0, p.stderr[-2000:]
    assert "holdout:" not in p.stdout and not list((tmp_path / "data").glob("holdout_*"))
