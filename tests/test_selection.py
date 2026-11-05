"""Selection on cycle scores: survivors, bases, below."""
import random

import pytest

from apex import config
from apex.selection import select


@pytest.fixture
def cfg():
    return config.load()


# 1
def test_positive_average(cfg):
    s = select({"a": 10, "b": 20, "c": 0, "d": 10}, cfg)
    assert s["avg"] == 10 and s["threshold"] == 12
    assert s["bases"] == ["b"] and s["survivors"] == ["b", "a"] and s["below"] == ["a", "d", "c"]
    assert s["ranking"] == ["b", "a", "d", "c"] and s["bases_fallback"] is False


# 2
def test_negative_average(cfg):
    s = select({"x": -10, "y": -5, "z": -15}, cfg)
    assert s["avg"] == -10 and s["threshold"] == -8 and s["bases"] == ["y"]


# 3
def test_zero_average(cfg):
    s = select({"p": -1, "q": 1, "r": 0}, cfg)
    assert s["threshold"] == 0 and s["bases"] == ["q", "r"]


# 4
def test_ties_fixed_rule(cfg):
    scores = {f"g0-{i:02d}": float(i % 3) for i in range(1, 11)}
    first = select(scores, cfg)
    items = list(scores.items())
    for seed in range(5):
        random.Random(seed).shuffle(items)
        assert select(dict(items), cfg) == first
    assert first["survivors"] == ["g0-02", "g0-05"]


# 5
def test_survivor_count(cfg):
    scores = {f"g0-{i:02d}": float(i) for i in range(1, 11)}
    assert select(scores, cfg)["survivors"] == ["g0-10", "g0-09"]
    cfg3 = config.load(overrides={"operation": {"survivors": 3}})
    assert len(select(scores, cfg3)["survivors"]) == 3
    assert select({"only": 1.0}, cfg)["survivors"] == ["only"]


# 6
def test_nan_ranks_last(cfg):
    s = select({"a": float("nan"), "b": 1.0, "c": 3.0}, cfg)
    assert s["ranking"] == ["c", "b", "a"] and s["avg"] == 2.0 and s["threshold"] == 2.4
    assert s["bases"] == ["c"]


# 7
def test_no_bases_falls_back_to_survivors(cfg):
    s = select({"a": 5.0, "b": 5.0, "c": 5.0}, cfg)
    assert s["bases"] == ["a", "b"] and s["bases_fallback"] is True


# ---- review fixes ----------------------------------------------------------------------------------------------
# 13
def test_odd_scores(cfg):
    s = select({"a": True, "b": 0.5, "c": 10 ** 400, "d": None, "e": "3"}, cfg)
    assert s["ranking"] == ["b", "a", "c", "d", "e"] and s["avg"] == 0.5


# 14
def test_average_does_not_overflow(cfg):
    s = select({"a": 1e308, "b": 1e308, "c": -1e308}, cfg)
    assert s["avg"] < float("inf") and s["bases"] == ["a", "b"]


# 15
def test_natural_tie_order(cfg):
    assert select({"g0-10": 1.0, "g0-2": 1.0, "g0-1": 0.0}, cfg)["survivors"] == ["g0-2", "g0-10"]


# 16
def test_non_finite_never_survives(cfg):
    s = select({"a": float("nan"), "b": float("nan"), "c": 1.0}, cfg)
    assert s["survivors"] == ["c"]
