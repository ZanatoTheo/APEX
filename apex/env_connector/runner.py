"""Runs inside the sandbox for one backtested step. Stand-alone: it never imports apex.

Protocol (JSON lines; the host writes to stdin, this answers on the real stdout):
  host: {"assets": [...], "context": [...]}      → {"ready": true} or {"fatal": "..."}
  host: {"date": d, "add": [days before d]}      → {"weights": {...}} | {"hold": true} | {"error": "..."}
The host sends a day's bar only after it has the weights for that day, so `history` never holds the day being
traded or a later one. A strategy's print() goes to stderr: only this file writes protocol lines.
"""
import importlib.util
import json
import math
import numbers
import os
import sys

FIELDS = ("open", "high", "low", "close", "volume")


class History:
    """What weights(history) gets: wide DataFrames (date × asset) .open .high .low .close .volume, .context
    (date × series), .assets, and .today (the day being traded; every row is earlier)."""

    def __init__(self, pd, assets, context):
        self._pd, self.assets, self.today = pd, list(assets), None
        prices = pd.read_csv("/data/prices.csv", parse_dates=["date"])
        for f in FIELDS:
            frame = prices.pivot(index="date", columns="asset", values=f) if len(prices) else pd.DataFrame()
            setattr(self, f, frame.reindex(columns=self.assets).astype(float))
        ctx = pd.read_csv("/data/context.csv", parse_dates=["date"])
        frame = ctx.pivot(index="date", columns="series", values="value") if len(ctx) else pd.DataFrame()
        self.context = frame.reindex(columns=list(context)).astype(float)

    def add(self, days) -> None:
        for d in days:
            ts = self._pd.Timestamp(d["date"])
            if d.get("tradable"):
                for f in FIELDS:
                    frame = getattr(self, f)
                    frame.loc[ts] = [d["tradable"].get(a, {}).get(f, math.nan) for a in self.assets]
            if d.get("context"):
                self.context.loc[ts] = [d["context"].get(c, math.nan) for c in self.context.columns]


def _number(v) -> float:
    if isinstance(v, bool) or not isinstance(v, numbers.Real):
        return math.nan
    try:
        return float(v)
    except (OverflowError, TypeError, ValueError):   # 10**400 and the like: the host clips NaN to 0
        return math.nan


def main() -> None:
    proto = os.fdopen(os.dup(1), "w", buffering=1)
    os.dup2(2, 1)                                   # fd 1 (and print) now go to stderr
    sys.stdout = sys.stderr

    def say(obj):
        proto.write(json.dumps(obj) + "\n")
        proto.flush()

    try:
        first = json.loads(sys.stdin.readline())
        import pandas as pd
        history = History(pd, first["assets"], first["context"])
    except Exception as e:
        say({"fatal": f"could not load /data: {type(e).__name__}: {e}"[:500]})
        return
    try:
        sys.path.insert(0, "/work")
        spec = importlib.util.spec_from_file_location("strategy", "/work/strategy.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        weights = getattr(module, "weights", None)
        if not callable(weights):
            raise AttributeError("strategy.py has no weights(history) function")
    except BaseException as e:                      # SyntaxError, ImportError, SystemExit, …
        say({"fatal": f"strategy.py failed to load: {type(e).__name__}: {e}"[:500]})
        return
    say({"ready": True})
    for line in sys.stdin:
        msg = json.loads(line)
        history.add(msg.get("add") or [])
        history.today = pd.Timestamp(msg["date"])
        try:
            w = weights(history)
        except Exception as e:
            say({"error": f"{type(e).__name__}: {e}"[:500]})
            continue
        if w is None:
            say({"hold": True})
        elif isinstance(w, dict):
            try:
                reply = {"weights": {str(k): _number(v) for k, v in w.items()}}
            except Exception as e:
                reply = {"error": f"could not read the weights: {type(e).__name__}: {e}"[:500]}
            say(reply)
        else:
            say({"error": f"weights() must return a dict or None, got {type(w).__name__}"})


if __name__ == "__main__":
    main()
