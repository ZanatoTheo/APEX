"""The chunk file and the feed of released days.

`load(data)` takes a path or a dict in the format environment/ writes, checks it and names any problem. `Feed` only
hands out days up to a step: `released(upto)` = history + the days of steps <= upto. Step -1 is history only.

Format: {meta, history, steps}. meta holds time_gap, cycle_days, anchor, step_ends, assets ({name: {class}}) and context
(names). A day is {date, tradable: {name: {open, high, low, close, volume}}, context: {name: value}} and lists only
the assets that traded that day. history is the days before the first step; steps is [{step_end, days}]. At least
one equity and one bond asset are required, because the 60/40 target needs both.
"""
import csv
import json
import math
import os
import re
from datetime import date as _date
from pathlib import Path

from apex.connector import ConnectorError

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _is_date(x) -> bool:
    """A YYYY-MM-DD string that is a real calendar day (2025-02-30 is not)."""
    if not isinstance(x, str) or not _DATE.fullmatch(x):
        return False
    try:
        _date.fromisoformat(x)
    except ValueError:
        return False
    return True
_FIELDS = ("open", "high", "low", "close", "volume")


def _bad(msg: str):
    raise ConnectorError(f"chunk file: {msg}")


def _check_day(day, where: str, assets: set, context: set) -> str:
    if not isinstance(day, dict) or not _is_date(day.get("date")):
        _bad(f"{where}: a day needs an ISO date")
    d = day["date"]
    tradable = day.get("tradable")
    if not isinstance(tradable, dict) or not isinstance(day.get("context", {}), dict):
        _bad(f"{where} {d}: tradable and context must be objects")
    for name, bar in tradable.items():
        if name not in assets:
            _bad(f"{where} {d}: unknown asset {name!r} (not in meta.assets)")
        if not isinstance(bar, dict) or set(bar) != set(_FIELDS):
            _bad(f"{where} {d} {name}: a bar has exactly {', '.join(_FIELDS)}")
        for f, v in bar.items():
            ok = not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v)
            if not ok or (v <= 0 if f != "volume" else v < 0):
                _bad(f"{where} {d} {name}.{f} must be a finite number (prices > 0, volume >= 0)")
        top, bottom = max(bar["open"], bar["close"]), min(bar["open"], bar["close"])
        if bar["high"] < top * (1 - 1e-9) or bar["low"] > bottom * (1 + 1e-9):
            _bad(f"{where} {d} {name}: high must be >= open and close, low <= them")
    for name, v in day.get("context", {}).items():
        if name not in context:
            _bad(f"{where} {d}: unknown context series {name!r}")
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            _bad(f"{where} {d} context {name} must be a finite number")
    return d


def load(data) -> "Feed":
    if isinstance(data, (str, Path)):
        try:
            data = json.loads(Path(data).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise ConnectorError(f"cannot read chunk file {data}: {e}") from None
    if not isinstance(data, dict):
        _bad("must be a JSON object")
    for key in ("meta", "history", "steps"):
        if key not in data:
            _bad(f"missing key {key}")
    meta = data["meta"]
    if not isinstance(meta, dict):
        _bad("meta must be an object")
    for key in ("time_gap", "cycle_days", "anchor", "step_ends", "assets", "context"):
        if key not in meta:
            _bad(f"missing key meta.{key}")
    for key in ("time_gap", "cycle_days"):
        if type(meta[key]) is not int or meta[key] < 1:
            _bad(f"meta.{key} must be an int >= 1")
    assets = meta["assets"]
    if not isinstance(assets, dict) or not assets or not all(
            isinstance(m, dict) and isinstance(m.get("class"), str) for m in assets.values()):
        _bad("meta.assets must map each asset to {class}")
    classes = {m["class"] for m in assets.values()}
    if "equity" not in classes or "bond" not in classes:
        _bad("meta.assets needs at least one equity and one bond asset (the 60/40 target)")
    if not isinstance(meta["context"], list) or not all(isinstance(c, str) for c in meta["context"]):
        _bad("meta.context must be a list of names")
    steps = data["steps"]
    if not isinstance(steps, list) or not steps or not isinstance(data["history"], list):
        _bad("history must be a list and steps a non-empty list")
    ends = [s.get("step_end") if isinstance(s, dict) else None for s in steps]
    if meta["step_ends"] != ends:
        _bad("meta.step_ends must equal the steps' step_end, in order")
    names, ctx = set(assets), set(meta["context"])
    previous = None
    for d in data["history"]:
        date = _check_day(d, "history", names, ctx)
        if previous is not None and date <= previous:
            _bad(f"days must be strictly increasing (history {date})")
        previous = date
    prev_end = previous or ""
    for k, s in enumerate(steps):
        end = s["step_end"]
        if not _is_date(end) or end <= prev_end:
            _bad(f"step {k}: step_end must be an ISO date after the previous one")
        if not isinstance(s.get("days"), list) or not s["days"]:
            _bad(f"step {k} has no days")
        for d in s["days"]:
            date = _check_day(d, f"step {k}", names, ctx)
            if not prev_end < date <= end:
                _bad(f"step {k}: day {date} is outside its step ({prev_end}, {end}]")
        for a, b in zip(s["days"], s["days"][1:]):
            if b["date"] <= a["date"]:
                _bad(f"step {k}: days must be strictly increasing ({b['date']})")
        prev_end = end
    return Feed(data)


class Feed:
    def __init__(self, data: dict):
        self.meta = data["meta"]
        self.history = data["history"]
        self.steps = data["steps"]

    def n_steps(self) -> int:
        return len(self.steps)

    def step_end(self, k: int) -> str:
        if k < 0:
            return self.history[-1]["date"] if self.history else "0000-00-00"
        return self.steps[k]["step_end"]

    def days(self, k: int) -> list:
        return self.steps[k]["days"]

    def released(self, upto: int) -> list:
        out = list(self.history)
        for k in range(min(upto, self.n_steps() - 1) + 1):
            out += self.steps[k]["days"]
        return out

    def last_close(self, upto: int) -> dict:
        """{asset: its latest close} over the days released up to `upto`."""
        out = {}
        for d in self.released(upto):
            for a, b in d["tradable"].items():
                out[a] = b["close"]
        return out

    def write_files(self, upto: int, folder) -> dict:
        """Write prices.csv and context.csv (every released day up to `upto`) into `folder`; return
        {"/data/<name>": host path} for the sandbox."""
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        days = self.released(upto)
        paths = {"/data/prices.csv": folder / "prices.csv", "/data/context.csv": folder / "context.csv"}
        tmp = folder / "prices.csv.tmp"
        with open(tmp, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date", "asset", *_FIELDS])
            for d in days:
                for a in sorted(d["tradable"]):
                    b = d["tradable"][a]
                    w.writerow([d["date"], a, *(b[x] for x in _FIELDS)])
        os.replace(tmp, paths["/data/prices.csv"])
        tmp = folder / "context.csv.tmp"
        with open(tmp, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date", "series", "value"])
            for d in days:
                for name in sorted(d.get("context", {})):
                    w.writerow([d["date"], name, d["context"][name]])
        os.replace(tmp, paths["/data/context.csv"])
        return {k: str(v) for k, v in paths.items()}
