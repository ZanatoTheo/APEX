"""Small synthetic chunk files for the market connector tests. Seeded, so the output never changes.

Run `python -m tests.fixtures.make_env_fixtures` to rewrite chunks_small_7.json, chunks_small_2.json and
chunks_holdout_7.json; a test
checks that the files match what this builds. Asset A (equity) and B (bond) trade on weekdays except holidays,
C (crypto) every day; context series are daily values on A's days. History: 2024-11-01..12-31; then 2025-01-01..
02-04, cut into steps with the anchor rule (ends anchor + k·gap, plus the last day), as environment/ will do.
"""
import json
import random
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ANCHOR = date(2025, 1, 5)
START, END = date(2025, 1, 1), date(2025, 2, 4)
HOLIDAYS = {date(2024, 11, 28), date(2024, 12, 25), date(2025, 1, 1)}
FIRST = date(2024, 11, 1)
# the held-out fixture: the same shape two years earlier, another seed, no day in common
HOLDOUT = {"anchor": date(2023, 1, 1), "start": date(2023, 1, 1), "end": date(2023, 2, 4), "first": date(2022, 11, 1),
           "holidays": {date(2022, 11, 24), date(2022, 12, 26), date(2023, 1, 2)}, "seed": 23}
ASSETS = {"Asset A": {"class": "equity"}, "Asset B": {"class": "bond"}, "Asset C": {"class": "crypto"}}
CONTEXT = ["Oil", "US 10y yield"]


def _days(first=FIRST, end=END, holidays=HOLIDAYS, seed=11):
    rng = random.Random(seed)
    close = {"Asset A": 100.0, "Asset B": 100.0, "Asset C": 100.0}
    vol = {"Asset A": 0.01, "Asset B": 0.003, "Asset C": 0.03}
    ctx = {"Oil": 70.0, "US 10y yield": 4.2}
    d, out = first, []
    while d <= end:
        weekday = d.weekday() < 5 and d not in holidays
        day = {"date": d.isoformat(), "tradable": {}, "context": {}}
        for name in ASSETS:
            if name != "Asset C" and not weekday:
                continue
            o = close[name] * (1 + rng.gauss(0, vol[name] / 3))
            c = o * (1 + rng.gauss(0, vol[name]))
            day["tradable"][name] = {"open": round(o, 4), "high": round(max(o, c) * (1 + rng.random() * 0.005), 4),
                                     "low": round(min(o, c) * (1 - rng.random() * 0.005), 4), "close": round(c, 4),
                                     "volume": rng.randint(1000, 9000)}
            close[name] = round(c, 4)
        if weekday:
            for name in CONTEXT:
                ctx[name] = round(ctx[name] * (1 + rng.gauss(0, 0.01)), 4)
                day["context"][name] = ctx[name]
        out.append(day)
        d += timedelta(days=1)
    return out


def build(time_gap: int, cycle_days: int = 28, anchor=ANCHOR, start=START, end=END, first=FIRST, holidays=HOLIDAYS,
          seed=11) -> dict:
    ANCHOR, START, END = anchor, start, end            # noqa: N806 (the cut below reads as before)
    days = _days(first, end, holidays, seed)
    history = [x for x in days if x["date"] < START.isoformat()]
    year = [x for x in days if x["date"] >= START.isoformat()]
    k = -((ANCHOR - START).days // time_gap)          # the earliest anchor + k·gap on or after START
    ends = []
    while ANCHOR + timedelta(days=k * time_gap) <= END:
        e = ANCHOR + timedelta(days=k * time_gap)
        if e >= START:
            ends.append(e.isoformat())
        k += 1
    if not ends or ends[-1] < END.isoformat():
        ends.append(END.isoformat())
    steps, i = [], 0
    for e in ends:
        chunk = []
        while i < len(year) and year[i]["date"] <= e:
            chunk.append(year[i])
            i += 1
        if chunk:                                      # an empty chunk's end is skipped: it joins the next one
            steps.append({"step_end": e, "days": chunk})
    meta = {"time_gap": time_gap, "cycle_days": cycle_days, "anchor": ANCHOR.isoformat(),
            "step_ends": [s["step_end"] for s in steps], "assets": ASSETS, "context": CONTEXT}
    return {"meta": meta, "history": history, "steps": steps}


def build_holdout(time_gap: int = 7) -> dict:
    return build(time_gap, **HOLDOUT)


def main():
    for gap in (7, 2):
        (HERE / f"chunks_small_{gap}.json").write_text(json.dumps(build(gap), indent=None) + "\n")
    (HERE / "chunks_holdout_7.json").write_text(json.dumps(build_holdout(), indent=None) + "\n")


if __name__ == "__main__":
    main()
