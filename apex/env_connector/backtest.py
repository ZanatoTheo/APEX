"""The backtest engine: trades a portfolio day by day. Pure Python: no sandbox, no files.

Weights are decided before the day, executed at the day's open, valued at its close. An asset with no bar that day
is not traded (its shares are held, valued at its last close). A fee is paid on the traded value; buys are scaled
down so cash never goes below zero.
"""
import math
from dataclasses import dataclass, field

START_CASH = 100_000.0
FEE = 0.001                      # 0.1% of traded value


@dataclass
class Portfolio:
    cash: float = START_CASH
    shares: dict = field(default_factory=dict)

    def value(self, marks: dict) -> float:
        return self.cash + sum(n * marks.get(a, 0.0) for a, n in self.shares.items())


def _number(v) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return 0.0
    try:
        f = float(v)
    except OverflowError:
        return 0.0
    return f if math.isfinite(f) and f > 0 else 0.0


def clip_weights(weights, assets) -> dict:
    """A strategy's answer made safe: long only, known assets, finite numbers, sum <= 1 (the rest is cash)."""
    if not isinstance(weights, dict):
        return {}
    out = {a: _number(w) for a, w in weights.items() if a in assets}
    top = max(out.values(), default=0.0)
    if top > 1:                                       # first bring each weight to <= 1, so the sum stays finite
        out = {a: w / top for a, w in out.items()}
    total = sum(out.values())
    if total > 1:
        out = {a: w / total for a, w in out.items()}
    return out


def trade_day(p: Portfolio, weights, bar: dict, last_close: dict, fee: float, date: str = "") -> dict:
    """One day. `weights`: None (hold), or {asset: target share of the value at open}; a None weight holds that
    asset; an asset missing from the dict is sold. `bar`: {asset: {open, high, low, close, volume}} of the assets
    that traded today. `last_close` is updated with today's closes."""
    marks = {a: (bar[a]["open"] if a in bar else last_close.get(a, 0.0)) for a in set(p.shares) | set(bar)}
    value_open = p.value(marks)
    trades = {}
    if weights is not None:
        for a in bar:
            w = weights.get(a, 0.0)
            if w is None:
                continue
            delta = w * value_open - p.shares.get(a, 0.0) * bar[a]["open"]
            if abs(delta) > 1e-9:
                trades[a] = delta
    buys = sum(d for d in trades.values() if d > 0)
    sells = -sum(d for d in trades.values() if d < 0)
    if buys > 0 and p.cash + sells - buys - fee * (buys + sells) < 0:
        f = max(0.0, min(1.0, (p.cash + sells * (1 - fee)) / (buys * (1 + fee))))
        trades = {a: (d * f if d > 0 else d) for a, d in trades.items()}
        buys *= f
    paid = fee * (buys + sells)
    p.cash += sells - buys - paid
    if abs(p.cash) < 1e-6:
        p.cash = 0.0
    for a, d in trades.items():
        p.shares[a] = p.shares.get(a, 0.0) + d / bar[a]["open"]
        if abs(p.shares[a]) < 1e-12:
            del p.shares[a]
    for a, b in bar.items():
        last_close[a] = b["close"]
    value_close = p.value(last_close)
    applied = {} if weights is None else {a: w for a, w in weights.items() if a in trades or w}
    return {"date": date, "value_open": value_open, "value_close": value_close, "fee": paid,
            "trades": sum(1 for d in trades.values() if abs(d) > 1e-9), "weights_applied": applied,
            "cash_share": p.cash / value_close if value_close > 0 else 1.0}


def run_days(decide, days: list, p: Portfolio, last_close: dict, fee: float) -> list[dict]:
    """decide(day) -> weights or None for each day, then trade_day. Returns one row per day."""
    return [trade_day(p, decide(d), d["tradable"], last_close, fee, d["date"]) for d in days]


class BuyAndHold:
    """Each asset is bought to its target weight on the first day it has a bar, then held."""

    def __init__(self, targets: dict):
        self.targets = dict(targets)
        self.bought = set()

    def __call__(self, day):
        if self.bought >= set(self.targets):
            return None
        today = set(day["tradable"])
        w = {a: (None if a in self.bought or a not in today else t) for a, t in self.targets.items()}
        self.bought |= today & set(self.targets)
        return w


def equal_weight(assets) -> dict:
    assets = list(assets)
    return {a: 1 / len(assets) for a in assets}


def sixty_forty(asset_meta: dict) -> dict:
    """60% split equally over the equity assets, 40% over the bond assets, 0 for the rest."""
    eq = [a for a, m in asset_meta.items() if m.get("class") == "equity"]
    bd = [a for a, m in asset_meta.items() if m.get("class") == "bond"]
    return {a: (0.6 / len(eq) if a in eq else 0.4 / len(bd) if a in bd else 0.0) for a in asset_meta}
