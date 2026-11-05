"""The backtest engine, pure Python."""
import json
import math
from pathlib import Path

import pytest

from apex.env_connector.backtest import (FEE, BuyAndHold, Portfolio, clip_weights, equal_weight, run_days,
                                         sixty_forty, trade_day)
from apex.env_connector.feed import load

FIX = Path(__file__).resolve().parent / "fixtures"


def bar(o, c):
    return {"open": o, "high": max(o, c), "low": min(o, c), "close": c, "volume": 1}


def day(date, **bars):
    return {"date": date, "tradable": bars, "context": {}}


def test_clip_weights():
    w = clip_weights({"A": 0.7, "B": 0.6}, ["A", "B"])
    assert w["A"] == pytest.approx(0.7 / 1.3) and w["B"] == pytest.approx(0.6 / 1.3)
    assert clip_weights({"A": -1, "B": True, "C": math.nan, "Z": 0.5}, ["A", "B", "C"]) == {"A": 0, "B": 0, "C": 0}
    assert clip_weights("x", ["A"]) == {}
    assert clip_weights({"A": "0.5", "B": math.inf}, ["A", "B"]) == {"A": 0, "B": 0}
    assert clip_weights({"A": 0.3}, ["A", "B"]) == {"A": 0.3}


def test_three_day_buy_and_hold_with_fee():
    p, lc = Portfolio(100_000.0), {}
    days = [day("d1", X=bar(100, 102)), day("d2", X=bar(101, 104)), day("d3", X=bar(105, 103))]
    plan = iter([{"X": 1.0}, None, None])
    rows = run_days(lambda d: next(plan), days, p, lc, FEE)
    assert rows[0]["fee"] == pytest.approx(99.9001, abs=1e-4)
    assert p.cash == pytest.approx(0.0, abs=1e-6)
    assert p.shares["X"] == pytest.approx(999.000999, abs=1e-6)
    assert [r["value_close"] for r in rows] == pytest.approx([101898.1019, 103896.1039, 102897.1029], abs=1e-3)
    assert rows[1]["trades"] == 0 and rows[1]["fee"] == 0


def test_weekend_asset_without_bar_is_held():
    p = Portfolio(50_000.0, {"X": 500.0})
    lc = {"X": 100.0}
    row = trade_day(p, {"X": 0.5, "Y": 0.5}, {"Y": bar(50, 50)}, lc, FEE, "sat")
    assert row["value_open"] == pytest.approx(100_000.0)
    assert p.shares["X"] == 500.0                                       # no bar: not traded
    assert p.shares["Y"] * 50 == pytest.approx(50_000 / 1.001, abs=1e-3)
    assert row["fee"] == pytest.approx(49.95005, abs=1e-4) and p.cash == pytest.approx(0.0, abs=1e-6)
    assert row["value_close"] == pytest.approx(500 * 100 + p.shares["Y"] * 50)


def test_sell_gets_cash_and_pays_fee():
    p = Portfolio(0.0, {"X": 10.0})
    lc = {"X": 100.0}
    row = trade_day(p, {}, {"X": bar(100, 100)}, lc, FEE, "d")
    assert p.shares.get("X", 0) == pytest.approx(0) and p.cash == pytest.approx(1000 - 1.0)
    assert row["cash_share"] == pytest.approx(1.0)


def test_equal_weight_by_hand_no_fee():
    p, lc = Portfolio(100_000.0), {}
    days = [day("d1", A=bar(10, 10), C=bar(20, 20)), day("d2", A=bar(10, 11), C=bar(20, 18))]
    rows = run_days(BuyAndHold(equal_weight(["A", "C"])), days, p, lc, 0.0)
    assert p.shares == pytest.approx({"A": 5000.0, "C": 2500.0})
    assert rows[-1]["value_close"] == pytest.approx(100_000.0)
    assert rows[1]["trades"] == 0


def test_buy_and_hold_waits_for_a_bar():
    p, lc = Portfolio(100_000.0), {}
    days = [day("sat", C=bar(20, 20)), day("mon", A=bar(10, 10), C=bar(20, 20))]
    run_days(BuyAndHold(equal_weight(["A", "C"])), days, p, lc, 0.0)
    assert p.shares == pytest.approx({"A": 5000.0, "C": 2500.0})       # A bought Monday, C kept from Saturday


def test_none_holds():
    p, lc = Portfolio(0.0, {"X": 3.0}), {"X": 5.0}
    row = trade_day(p, None, {"X": bar(6, 7)}, lc, FEE, "d")
    assert p.shares == {"X": 3.0} and row["trades"] == 0 and row["value_close"] == 21.0


def test_sixty_forty_weights():
    assets = {"A": {"class": "equity"}, "A2": {"class": "equity"}, "B": {"class": "bond"}, "C": {"class": "crypto"}}
    assert sixty_forty(assets) == pytest.approx({"A": 0.3, "A2": 0.3, "B": 0.4, "C": 0.0})


def test_same_values_at_7_and_2_days():
    values = []
    for gap in (7, 2):
        f = load(json.loads((FIX / f"chunks_small_{gap}.json").read_text()))
        p, lc = Portfolio(100_000.0), dict(f.last_close(-1))
        rows = []
        for k in range(f.n_steps()):
            rows += run_days(lambda d: {"Asset A": 0.5, "Asset C": 0.5}, f.days(k), p, lc, FEE)
        values.append({r["date"]: r["value_close"] for r in rows})
    assert values[0].keys() == values[1].keys()
    assert all(values[0][d] == pytest.approx(values[1][d], abs=1e-9) for d in values[0])


def test_clip_weights_huge_values():
    assert clip_weights({"A": 1e308, "B": 1e308}, ["A", "B"]) == pytest.approx({"A": 0.5, "B": 0.5})
