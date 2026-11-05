"""Replay your strategy.py over the days released so far. Read-only at /data/replay.py.

From a script in your folder, run with run_script (args: [days], default 120):
    import runpy; runpy.run_path("/data/replay.py", run_name="__main__")

Each replayed day, weights(history) gets only the rows before that day (the same history the real backtest
gives), trades at the open with a 0.1% fee, and is valued at the close. An error that day → cash; None → hold.
Prints one JSON line: days, from, to, strategy_return, equal_weight_return (buy and hold, no fees), excess, fees,
trades, errors, first_error. Stand-alone: it never imports apex.
"""
import importlib.util
import json
import math
import sys

FIELDS = ("open", "high", "low", "close", "volume")
FEE = 0.001


class View:
    """What weights(history) gets: .open .high .low .close .volume (date × asset), .context, .assets, .today."""

    def __init__(self, frames, context, assets, today):
        for f in FIELDS:
            setattr(self, f, frames[f][frames[f].index < today])
        self.context = context[context.index < today]
        self.assets, self.today = list(assets), today


def _clip(w, assets) -> dict:
    out = {}
    for a, v in (w or {}).items():
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        if a in assets and math.isfinite(v) and v > 0:
            out[a] = v
    total = sum(out.values())
    return {a: v / total for a, v in out.items()} if total > 1 else out


def _load(pd, data_dir):
    prices = pd.read_csv(f"{data_dir}/prices.csv", parse_dates=["date"])
    assets = sorted(prices["asset"].unique())
    frames = {f: prices.pivot(index="date", columns="asset", values=f).reindex(columns=assets).astype(float)
              for f in FIELDS}
    ctx = pd.read_csv(f"{data_dir}/context.csv", parse_dates=["date"])
    context = (ctx.pivot(index="date", columns="series", values="value").astype(float) if len(ctx)
               else pd.DataFrame(index=frames["close"].index))
    return frames, context, assets


def replay(data_dir="/data", strategy="/work/strategy.py", days=120) -> dict:
    import pandas as pd
    frames, context, assets = _load(pd, data_dir)
    spec = importlib.util.spec_from_file_location("strategy", str(strategy))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    dates = list(frames["close"].index)
    test = dates[-int(days):] if len(dates) > 1 else dates
    if test and test[0] == dates[0]:
        test = test[1:]                                   # the first day has no history before it
    opens, closes = frames["open"].ffill(), frames["close"].ffill()
    cash, shares, fees, trades, errors, first_error = 1.0, {}, 0.0, 0, 0, ""
    bench = None
    for d in test:
        o, c = opens.loc[d], closes.loc[d]
        price = {a: (o[a] if o[a] == o[a] else c[a]) for a in assets}
        value_open = cash + sum(n * price[a] for a, n in shares.items() if price[a] == price[a])
        try:
            w = module.weights(View(frames, context, assets, d))
            w = None if w is None else _clip(w, assets)
        except Exception as e:                             # the real backtest holds cash that day
            errors += 1
            first_error = first_error or f"{d.date()}: {type(e).__name__}: {e}"[:300]
            w = {}
        if w is not None:
            for a in assets:
                if price[a] != price[a] or price[a] <= 0:
                    continue
                target = w.get(a, 0.0) * value_open / price[a]
                delta = target - shares.get(a, 0.0)
                if abs(delta) > 1e-12:
                    cost = abs(delta) * price[a]
                    fees += cost * FEE
                    cash -= delta * price[a] + cost * FEE
                    shares[a] = target
                    trades += 1
        if bench is None:                                 # equal weight, bought at the first open, no fees
            live = [a for a in assets if price[a] == price[a] and price[a] > 0]
            bench = {a: (1.0 / len(live)) / price[a] for a in live}
    value = cash + sum(n * closes.loc[test[-1]][a] for a, n in shares.items()) if test else 1.0
    bench_value = sum(n * closes.loc[test[-1]][a] for a, n in (bench or {}).items()) if test else 1.0
    out = {"days": len(test), "from": str(test[0].date()) if test else None,
           "to": str(test[-1].date()) if test else None, "strategy_return": value - 1.0,
           "equal_weight_return": bench_value - 1.0, "excess": value - bench_value, "fees": fees,
           "trades": trades, "errors": errors, "first_error": first_error}
    return out


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 120
    print(json.dumps(replay(days=n)))
