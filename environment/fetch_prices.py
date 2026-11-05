"""Download daily prices for the assets in assets.json to one long CSV. Run by the user only.

  python environment/fetch_prices.py [--start 2015-01-01] [--end 2025-12-31] [--out environment/data/prices.csv]
  python environment/fetch_prices.py --dry-run        # print the URLs, send nothing

Tradables come from Yahoo's chart JSON, with open/high/low/close scaled by adjclose/close, so returns include
dividends (most of a bond ETF's return); volume is kept as is. Context series come from FRED's CSV download. The
output is `date,series,open,high,low,close,volume`; a context row fills only `close`. Uses httpx (already installed);
`http(url) -> (status, text)` can be passed in, and tests never touch the network.
"""
import argparse
import csv
import json
import math
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets.json"
OUT = HERE / "data" / "prices.csv"
START, END = "2015-01-01", "2025-12-31"
HEADER = ["date", "series", "open", "high", "low", "close", "volume"]
YAHOO = ("https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?period1={p1}&period2={p2}&interval=1d"
         "&events=div%2Csplit")
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={id}&cosd={start}&coed={end}"
TIMEOUT_S, RETRIES = 20, 2
FATAL = {400, 401, 403, 404}


class FetchError(Exception):
    """A series could not be fetched; the message starts with its name."""


def _default_http(url: str):
    import httpx
    r = httpx.get(url, timeout=TIMEOUT_S, follow_redirects=True,
                  headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) apex-research/1.0"})
    return r.status_code, r.text


def _epoch(day: str) -> int:
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp())


def urls(assets: dict, start: str = START, end: str = END) -> list[tuple[str, str, str]]:
    """[(kind, series name, url)] for every tradable and context series."""
    after = (date.fromisoformat(end) + timedelta(days=1)).isoformat()
    out = [("tradable", t, YAHOO.format(ticker=t, p1=_epoch(start), p2=_epoch(after))) for t in assets["tradable"]]
    out += [("context", name, FRED.format(id=fid, start=start, end=end)) for name, fid in assets["context"].items()]
    return out


def _get(http, url: str, name: str, sleep=time.sleep) -> str:
    last = "no answer"
    for attempt in range(RETRIES + 1):
        try:
            status, text = http(url)
        except Exception as e:                       # network errors and timeouts: retried
            last = f"{type(e).__name__}: {e}"
        else:
            if status == 200:
                return text
            last = f"HTTP {status}"
            if status in FATAL:
                break
        if attempt < RETRIES:
            sleep(2 * (attempt + 1))
    raise FetchError(f"{name}: {last}"[:300])


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0


def _yahoo_rows(ticker: str, text: str) -> list[dict]:
    """One row per day: open/high/low/close × adjclose/close (dividends in). A day without a close, or without an
    adjclose while others have one, is dropped (mixing adjusted and raw prices would fake a jump)."""
    try:
        res = json.loads(text)["chart"]["result"][0]
        stamps, q = res["timestamp"], res["indicators"]["quote"][0]
        n = len(stamps)
        cols = {f: q.get(f) for f in ("open", "high", "low", "close", "volume")}
        if any(not isinstance(c, list) or len(c) != n for c in cols.values()):
            raise ValueError("the price arrays and the timestamps differ in length")
        adj = ((res["indicators"].get("adjclose") or [{}])[0] or {}).get("adjclose")
        if adj is not None and (not isinstance(adj, list) or len(adj) != n):
            raise ValueError("adjclose and the timestamps differ in length")
        offset = (res.get("meta") or {}).get("gmtoffset") or 0
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as e:
        raise FetchError(f"{ticker}: the reply is not a chart with prices ({e})"[:300]) from None
    if not adj:
        print(f"warning: {ticker} has no adjclose; prices without dividends", file=sys.stderr)
    by_day, dropped = {}, 0
    for i, ts in enumerate(stamps):
        close = cols["close"][i]
        if not _num(close) or not isinstance(ts, (int, float)):
            continue
        if adj:
            if not _num(adj[i]):
                dropped += 1
                continue
            k = adj[i] / close
        else:
            k = 1.0
        o = cols["open"][i] if _num(cols["open"][i]) else close
        h = max(x for x in (cols["high"][i], o, close) if _num(x))
        low = min(x for x in (cols["low"][i], o, close) if _num(x))
        v = cols["volume"][i]
        day = datetime.fromtimestamp(ts + offset, tz=timezone.utc).date().isoformat()
        by_day[day] = {"date": day, "series": ticker, "open": o * k, "high": h * k, "low": low * k,
                       "close": close * k, "volume": v if isinstance(v, (int, float)) and v >= 0 else 0}
    if dropped:
        print(f"warning: {ticker}: {dropped} bar(s) without adjclose dropped", file=sys.stderr)
    return list(by_day.values())                     # a repeated date (a live last bar) keeps the last one


def _fred_rows(name: str, text: str) -> list[dict]:
    rows = list(csv.reader(text.splitlines()))
    if not rows or len(rows[0]) < 2:
        raise FetchError(f"{name}: the reply is not a FRED CSV")
    out = []
    for r in rows[1:]:
        if len(r) < 2 or r[1].strip() in ("", "."):
            continue
        try:
            out.append({"date": r[0], "series": name, "open": "", "high": "", "low": "", "close": float(r[1]),
                        "volume": ""})
        except ValueError:
            continue
    return out


def fetch(assets: dict, start: str = START, end: str = END, http=None, sleep=time.sleep) -> list[dict]:
    """Every row of every series between start and end, sorted by (date, series). Raises FetchError."""
    http = http or _default_http
    rows = []
    for kind, name, url in urls(assets, start, end):
        text = _get(http, url, name, sleep)
        rows += _yahoo_rows(name, text) if kind == "tradable" else _fred_rows(name, text)
    rows = [r for r in rows if start <= r["date"] <= end]
    return sorted(rows, key=lambda r: (r["date"], r["series"]))


def write_csv(rows: list[dict], path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(HEADER)
        for r in rows:
            w.writerow([r["date"], r["series"]] + [round(r[k], 6) if isinstance(r[k], float) else r[k]
                                                    for k in ("open", "high", "low", "close", "volume")])


def main(argv=None, http=None) -> int:
    p = argparse.ArgumentParser(description="Download daily prices for assets.json (ask before running it).")
    p.add_argument("--assets", default=str(ASSETS))
    p.add_argument("--start", default=START)
    p.add_argument("--end", default=END)
    p.add_argument("--out", default=str(OUT))
    p.add_argument("--dry-run", action="store_true", help="print the URLs and send nothing")
    args = p.parse_args(argv)
    assets = json.loads(Path(args.assets).read_text())
    if args.dry_run:
        for _, _, url in urls(assets, args.start, args.end):
            print(url)
        return 0
    try:
        rows = fetch(assets, args.start, args.end, http=http)
    except FetchError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    write_csv(rows, args.out)
    print(f"{len(rows)} rows → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
