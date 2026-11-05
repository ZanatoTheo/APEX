"""A small synthetic price CSV in fetch_prices.py's long format, for the environment/ tests.

Seeded, so the output never changes. Run `python -m tests.fixtures.make_prices_small` to rewrite prices_small.csv and
assets_small.json; a test checks the CSV matches what this builds. Real ticker names on purpose: the tests check none
of them reaches a chunk file. SPY (equity) and TLT (bond) trade on weekdays except Jan 1; BTC-USD every day; Oil and
US 10y yield on weekdays. Two spans: 2021-11-01..2022-02-15 (the held-out year 2022 and its history) and
2024-11-01..2025-02-04 (the training year 2025 and its history).
"""
import csv
import io
import json
import random
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPANS = [(date(2021, 11, 1), date(2022, 2, 15)), (date(2024, 11, 1), date(2025, 2, 4))]
TRADABLE = {"SPY": ("equity", 450.0, 0.01, False), "TLT": ("bond", 95.0, 0.004, False),
            "BTC-USD": ("crypto", 40000.0, 0.03, True)}          # class, first close, daily vol, trades weekends
CONTEXT = {"Oil": ("DCOILWTICO", 75.0), "US 10y yield": ("DGS10", 4.1)}
HEADER = ["date", "series", "open", "high", "low", "close", "volume"]


def rows() -> list[list]:
    rng = random.Random(7)
    out = []
    for first, last in SPANS:
        close = {t: v[1] for t, v in TRADABLE.items()}
        ctx = {n: v[1] for n, v in CONTEXT.items()}
        d = first
        while d <= last:
            weekday = d.weekday() < 5 and not (d.month == 1 and d.day == 1)
            for t, (_, _, vol, weekends) in TRADABLE.items():
                if not (weekday or weekends):
                    continue
                o = close[t] * (1 + rng.gauss(0, vol / 3))
                c = o * (1 + rng.gauss(0, vol))
                out.append([d.isoformat(), t, round(o, 4), round(max(o, c) * 1.002, 4), round(min(o, c) * 0.998, 4),
                            round(c, 4), rng.randint(1000, 90000)])
                close[t] = round(c, 4)
            if weekday:
                for n in CONTEXT:
                    ctx[n] = round(ctx[n] * (1 + rng.gauss(0, 0.01)), 4)
                    out.append([d.isoformat(), n, "", "", "", ctx[n], ""])
            d += timedelta(days=1)
    return out


def csv_text() -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(HEADER)
    w.writerows(rows())
    return buf.getvalue()


def assets() -> dict:
    return {"tradable": {t: v[0] for t, v in TRADABLE.items()}, "context": {n: v[0] for n, v in CONTEXT.items()}}


def main():
    (HERE / "prices_small.csv").write_text(csv_text())
    (HERE / "assets_small.json").write_text(json.dumps(assets(), indent=1) + "\n")


if __name__ == "__main__":
    main()
