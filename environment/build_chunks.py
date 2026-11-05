"""Build the chunk files the market connector reads (format: apex/env_connector/feed.py).

  python environment/build_chunks.py [--csv environment/data/prices.csv] [--time-gap 1] [--holdout-year 2022|none]

From fetch_prices.py's long CSV it writes, into environment/data/:
- chunks_<YEAR>_gap<g>.json: steps of `time_gap` days in YEAR; history = the days after the held-out year;
- holdout_<HOLDOUT_YEAR>_gap<g>.json: steps in HOLDOUT_YEAR; history = HISTORY_START to the year before;
- mapping.json: {"Asset A": ticker, ...}, one shuffled mapping for both files. It stays here, outside apex/ and every
  run folder: no agent can read it.
Tradables are renamed and rebased to 100 at their first close in each file; context series keep their names.
TIME_GAP below is the one place the step length is set.
"""
import argparse
import csv
import json
import math
import random
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:                        # run as a script: the apex package lives one level up
    sys.path.insert(0, str(ROOT))

from apex.env_connector.feed import load as load_feed   # noqa: E402  (the connector's checks, reused)

DATA = HERE / "data"
ASSETS = HERE / "assets.json"
TIME_GAP = 1                 # days per step: 28 steps per 28-day cycle (user, 2026-11-04)
CYCLE_DAYS = 28
YEAR = 2025
HOLDOUT_YEAR = 2022
HISTORY_START = "2015-01-01"
_FIELDS = ("open", "high", "low", "close", "volume")


def _letter(i: int) -> str:
    name = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        name = chr(65 + r) + name
    return f"Asset {name}"


def load_csv(path, assets: dict) -> dict:
    """{date: {"tradable": {ticker: bar}, "context": {name: value}}} for the series named in assets."""
    tickers, context = set(assets["tradable"]), set(assets["context"])
    days, seen = {}, set()
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            s, d = r["series"], r["date"]
            try:
                if s in tickers:
                    bar = {k: float(r[k]) for k in _FIELDS}
                    if not all(math.isfinite(v) for v in bar.values()) or bar["volume"] < 0 or \
                            min(bar[k] for k in ("open", "high", "low", "close")) <= 0:
                        continue
                    prices = (bar["open"], bar["high"], bar["low"], bar["close"])
                    bar["high"], bar["low"] = max(prices), min(prices)       # a swapped or short bar is repaired
                    bar["volume"] = int(bar["volume"]) if bar["volume"].is_integer() else bar["volume"]
                    days.setdefault(d, {"tradable": {}, "context": {}})["tradable"][s] = bar
                elif s in context:
                    v = float(r["close"])
                    if not math.isfinite(v):
                        continue
                    days.setdefault(d, {"tradable": {}, "context": {}})["context"][s] = v
                else:
                    continue
            except (ValueError, TypeError):
                continue
            seen.add(s)
    missing = sorted((tickers | context) - seen)
    if missing:
        raise ValueError(f"no rows in {path} for: {', '.join(missing)}")
    return days


def make_mapping(tickers, seed=None) -> dict:
    """A shuffled {"Asset A": ticker, ...}; SystemRandom unless a seed is given, so the order says nothing."""
    order = sorted(tickers)
    (random.Random(seed) if seed is not None else random.SystemRandom()).shuffle(order)
    return {_letter(i): t for i, t in enumerate(order)}


def _select(days: dict, lo: str, hi: str, rename: dict, context: list) -> list[dict]:
    """The days in [lo, hi] that have at least one tradable bar, renamed."""
    out = []
    for d in sorted(days):
        if not lo <= d <= hi or not days[d]["tradable"]:
            continue
        tradable = {rename[t]: dict(bar) for t, bar in days[d]["tradable"].items()}
        out.append({"date": d, "tradable": dict(sorted(tradable.items())),
                    "context": {n: days[d]["context"][n] for n in context if n in days[d]["context"]}})
    return out


def rebase(day_list: list[dict]) -> list[dict]:
    """Every asset's prices × 100 / its first close in these days (volume untouched). Changes the days in place."""
    first = {}
    for d in day_list:
        for a, bar in d["tradable"].items():
            k = first.setdefault(a, 100.0 / bar["close"])
            for f in ("open", "high", "low", "close"):
                bar[f] = round(bar[f] * k, 8)
    return day_list


def first_sunday(year: int) -> date:
    d = date(year, 1, 1)
    return d + timedelta(days=(6 - d.weekday()) % 7)


def cut(step_days: list[dict], year: int, time_gap: int) -> list[dict]:
    """[{step_end, days}]: ends at first_sunday + k·time_gap within the year, the last on min(Dec 31, the last day);
    an empty chunk's end is skipped (its days join the next)."""
    if not step_days:
        raise ValueError(f"no data days in {year}")
    anchor, start = first_sunday(year), date(year, 1, 1)
    last = min(date(year, 12, 31), date.fromisoformat(step_days[-1]["date"]))
    k = -((anchor - start).days // time_gap)
    ends = []
    while anchor + timedelta(days=k * time_gap) <= last:
        e = anchor + timedelta(days=k * time_gap)
        if e >= start:
            ends.append(e.isoformat())
        k += 1
    if not ends or ends[-1] < last.isoformat():
        ends.append(last.isoformat())
    steps, i = [], 0
    for e in ends:
        chunk = []
        while i < len(step_days) and step_days[i]["date"] <= e:
            chunk.append(step_days[i])
            i += 1
        if chunk:
            steps.append({"step_end": e, "days": chunk})
    return steps


def _dates(chunk: dict) -> list[str]:
    return [d["date"] for d in chunk["history"]] + [d["date"] for s in chunk["steps"] for d in s["days"]]


def check_apart(train: dict, held: dict) -> None:
    """Refuse a held-out file that shares a date with the training file or doesn't end before it starts."""
    tr, hd = _dates(train), _dates(held)
    shared = sorted(set(tr) & set(hd))
    if shared:
        raise ValueError(f"the training and held-out files share {len(shared)} dates (first {shared[0]})")
    if tr and hd and min(tr) <= max(hd):
        raise ValueError(f"the training data must start after the held-out data ends ({min(tr)} <= {max(hd)})")


def _chunk_file(days, lo, year, time_gap, rename, classes, context) -> dict:
    """History = the days from lo to the end of year − 1; steps = the days in year."""
    history = _select(days, lo, f"{year - 1}-12-31", rename, context)
    in_year = _select(days, f"{year}-01-01", f"{year}-12-31", rename, context)
    rebase(history + in_year)
    steps = cut(in_year, year, time_gap)
    meta = {"time_gap": time_gap, "cycle_days": CYCLE_DAYS, "anchor": first_sunday(year).isoformat(),
            "step_ends": [s["step_end"] for s in steps], "assets": classes, "context": list(context)}
    return {"meta": meta, "history": history, "steps": steps}


def _mapping_for(tickers, out: Path, seed, new_mapping: bool) -> dict:
    """The mapping.json already in `out` when it names the same tickers (letters stay stable across rebuilds, so
    older runs can still be decoded); else a new one. A seed always gives the seeded mapping (tests)."""
    path = out / "mapping.json"
    if seed is None and not new_mapping and path.is_file():
        try:
            old = json.loads(path.read_text())
            if isinstance(old, dict) and sorted(old.values()) == sorted(tickers):
                return old
        except ValueError:
            pass
    return make_mapping(tickers, seed)


def build(csv_path, assets_path=ASSETS, time_gap: int = TIME_GAP, year: int = YEAR, holdout_year=HOLDOUT_YEAR,
          out=DATA, seed=None, history_start: str = HISTORY_START, new_mapping: bool = False) -> dict:
    """Write the training file, the held-out file (unless holdout_year is None) and mapping.json into `out`.
    Returns {"train", "holdout", "mapping"} paths. Raises ValueError (or the feed's ConnectorError) on bad input;
    a file that fails the feed's checks is never left on disk."""
    if type(time_gap) is not int or time_gap < 1:
        raise ValueError(f"time_gap must be an int >= 1, got {time_gap!r}")
    if holdout_year is not None and holdout_year >= year:
        raise ValueError(f"the held-out year ({holdout_year}) must be before the training year ({year})")
    assets = json.loads(Path(assets_path).read_text())
    days = load_csv(csv_path, assets)
    out = Path(out)
    mapping = _mapping_for(list(assets["tradable"]), out, seed, new_mapping)
    rename = {t: a for a, t in mapping.items()}
    # only equity and bond matter (the 60/40 target); a rarer class could name its single asset
    classes = {a: {"class": assets["tradable"][t] if assets["tradable"][t] in ("equity", "bond") else "other"}
               for a, t in sorted(mapping.items())}
    context = list(assets["context"])
    train_lo = f"{holdout_year + 1}-01-01" if holdout_year is not None else history_start
    train = _chunk_file(days, train_lo, year, time_gap, rename, classes, context)
    held = None
    if holdout_year is not None:
        held = _chunk_file(days, history_start, holdout_year, time_gap, rename, classes, context)
        check_apart(train, held)
    out.mkdir(parents=True, exist_ok=True)
    paths = {"train": out / f"chunks_{year}_gap{time_gap}.json", "holdout": None, "mapping": out / "mapping.json"}
    if held is not None:
        paths["holdout"] = out / f"holdout_{holdout_year}_gap{time_gap}.json"
    for key, chunk in (("train", train), ("holdout", held)):
        if chunk is not None:
            tmp = paths[key].with_name(paths[key].name + ".tmp")
            tmp.write_text(json.dumps(chunk) + "\n")
            try:
                load_feed(tmp)                       # the connector's own checks, on the written file
            except BaseException:
                tmp.unlink(missing_ok=True)
                raise
            tmp.replace(paths[key])
    paths["mapping"].write_text(json.dumps(mapping, indent=1) + "\n")
    return paths


def parse_holdout_year(text: str):
    return None if str(text).lower() == "none" else int(text)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Build the chunk files for apex.env_connector.")
    p.add_argument("--csv", default=str(DATA / "prices.csv"))
    p.add_argument("--assets", default=str(ASSETS))
    p.add_argument("--time-gap", type=int, default=TIME_GAP)
    p.add_argument("--year", type=int, default=YEAR)
    p.add_argument("--holdout-year", default=str(HOLDOUT_YEAR), help="a year, or none")
    p.add_argument("--out", default=str(DATA))
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--new-mapping", action="store_true", help="draw a new mapping even if mapping.json fits")
    args = p.parse_args(argv)
    try:
        paths = build(args.csv, args.assets, args.time_gap, args.year, parse_holdout_year(args.holdout_year),
                      args.out, args.seed, new_mapping=args.new_mapping)
    except Exception as e:
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    for key, path in paths.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
