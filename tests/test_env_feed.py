"""The chunk file and the feed."""
import copy
import csv
import json
from pathlib import Path

import pytest

from apex.connector import ConnectorError
from apex.env_connector.feed import load
from tests.fixtures import make_env_fixtures

FIX = Path(__file__).resolve().parent / "fixtures"


def raw(gap=7):
    return json.loads((FIX / f"chunks_small_{gap}.json").read_text())


def last_date(path):
    rows = list(csv.reader(open(path)))
    return max(r[0] for r in rows[1:])


def test_fixtures_are_reproducible():
    for gap in (7, 2):
        assert make_env_fixtures.build(gap) == raw(gap)


def test_both_cuts_load():
    f7, f2 = load(FIX / "chunks_small_7.json"), load(raw(2))          # a path or a dict
    assert f7.n_steps() == 6 and f2.n_steps() == 18
    assert f7.step_end(0) == "2025-01-05" and f2.step_end(0) == "2025-01-01"
    assert f7.step_end(-1) == "2024-12-31"
    days7 = [d["date"] for k in range(6) for d in f7.days(k)]
    days2 = [d["date"] for k in range(18) for d in f2.days(k)]
    assert days7 == days2 and len(days7) == 35


def test_released_never_passes_the_step_end():
    for gap in (7, 2):
        f = load(raw(gap))
        assert f.released(-1)[-1]["date"] == "2024-12-31"
        for k in range(f.n_steps()):
            assert f.released(k)[-1]["date"] == f.step_end(k)          # every fixture step ends on a day
            assert all(d["date"] <= f.step_end(k) for d in f.released(k))


def test_last_close():
    f = load(raw(7))
    lc = f.last_close(0)
    assert set(lc) == {"Asset A", "Asset B", "Asset C"}
    c_last = [d for d in f.days(0) if "Asset C" in d["tradable"]][-1]["tradable"]["Asset C"]["close"]
    assert lc["Asset C"] == c_last


@pytest.mark.parametrize("break_it, words", [
    (lambda d: d.pop("meta"), "meta"),
    (lambda d: d["steps"][1]["days"].reverse(), "increasing"),
    (lambda d: d["steps"][0]["days"].append(copy.deepcopy(d["steps"][1]["days"][0])), "outside its step"),
    (lambda d: d["meta"]["assets"]["Asset B"].update({"class": "other"}), "equity and one bond"),
    (lambda d: d["meta"].update({"time_gap": 0}), "time_gap"),
    (lambda d: d["steps"][0]["days"][0]["tradable"]["Asset C"].update({"close": float("nan")}), "finite"),
    (lambda d: d["steps"][0]["days"][0]["tradable"].update({"Asset Z": {"open": 1, "high": 1, "low": 1,
                                                                         "close": 1, "volume": 1}}), "unknown"),
    (lambda d: d["meta"]["step_ends"].pop(), "step_ends"),
    (lambda d: d["steps"][0]["days"][0]["tradable"]["Asset C"].update({"high": 1e-3}), "high"),
])
def test_bad_files_are_refused(break_it, words):
    d = raw(7)
    break_it(d)
    with pytest.raises(ConnectorError, match=words):
        load(d)


def test_bad_path():
    with pytest.raises(ConnectorError):
        load("/nonexistent/chunks.json")


def test_write_files(tmp_path):
    f = load(raw(7))
    files = f.write_files(4, tmp_path / "w4")
    assert set(files) == {"/data/prices.csv", "/data/context.csv"}
    assert last_date(files["/data/prices.csv"]) == f.step_end(4)
    assert last_date(files["/data/context.csv"]) <= f.step_end(4)
    head = open(files["/data/prices.csv"]).readline().strip()
    assert head == "date,asset,open,high,low,close,volume"
    files = f.write_files(-1, tmp_path / "wh")
    assert last_date(files["/data/prices.csv"]) == "2024-12-31"


# ---- changes after the review ----------------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["2025-02-30", "2025-13-45", "0000-00-00"])
def test_impossible_dates_refused(bad):
    d = raw(7)
    d["steps"][-1]["days"][-1]["date"] = bad if bad > d["steps"][-2]["step_end"] else d["steps"][-1]["days"][-1]["date"]
    d["steps"][-1]["step_end"] = d["meta"]["step_ends"][-1] = "2025-02-30" if bad == "0000-00-00" else bad
    with pytest.raises(ConnectorError, match="date"):
        load(d)
