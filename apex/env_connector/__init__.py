"""The 2025 market test behind the connector interface. Only this package and environment/
know the task; to change the test, only they change.

Agents write strategy.py; each step releases `time_gap` days of daily prices of renamed assets; the connector
backtests each strategy day by day on those days inside the sandbox (one day at a time over a pipe, so a strategy
never holds the day it trades or a later one). Score: cycle return minus an equal-weight buy-and-hold's.
"""
import atexit
import threading
import json
import re
import shutil
import tempfile
from pathlib import Path

from apex.connector import ConnectorError
from apex.operation import split_cycles
from apex.tools.files import ToolError
from apex.tools.registry import Tool
from apex.tools.sandbox import Session

from . import wayback
from .backtest import FEE, START_CASH, BuyAndHold, Portfolio, clip_weights, equal_weight, run_days, sixty_forty, \
    trade_day
from .feed import load

HERE = Path(__file__).resolve().parent
RUNNER = "/opt/apex/runner.py"           # where runner.py is mounted (read-only) inside the sandbox
TARGET_MARGIN = 0.02                     # the stop target: the 60/40 mix's loop excess + this
READ_ROWS = 400                          # rows per read_prices call
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}")
_GLOBS = ["*.csv", "*.tsv", "*.json", "*.txt", "*.parquet", "*.pkl", "*.pickle", "*.npy", "*.npz", "*.feather",
          "*.h5"]
_PATTERNS = [r"\b20\d\d([-/.]?)[01]\d\1[0-3]\d\b",           # 2025-03-04, 2025/03/04, 2025.03.04, 20250304
             r"\b(\d{3,7}\.(?!0\b)\d+|\d{2}\.\d{2,})\b",   # prices: 512.3, 87.43, 512.00 (not 12.5, 0.05, 252.0)
             r"\bAsset [A-Z]{1,2}\b"]                     # asset names: Asset C, Asset AB (user, run 5)


class Connector:
    def __init__(self, cfg: dict, data):
        if data is None:
            raise ConnectorError("the market connector needs a chunk file: --data <file>")
        self.cfg = cfg
        self.feed = load(data)
        self.meta = self.feed.meta
        self.assets = list(self.meta["assets"])
        self.current = None
        self.http = None                 # wayback's HTTP function (tests pass a fake)
        self._wayback_cache = {}
        self._tmp = Path(tempfile.mkdtemp(prefix="apex-env-"))
        atexit.register(shutil.rmtree, self._tmp, True)
        self._files = {}                 # upto -> {"/data/<name>": host path}
        self._files_lock = threading.Lock()   # agents may ask for /data at the same time (parallel_agents)
        self._closes = {}                # step -> last closes before it
        self.portfolios, self.scores, self.reports = {}, {}, {}
        self._target = None
        self._reset_benchmark()

    # ---- the interface --------------------------------------------------------------------------------------
    def brief(self) -> str:
        m = self.meta
        return (HERE / "brief.md").read_text().format(
            time_gap=m["time_gap"], cycle_days=m["cycle_days"], steps_per_cycle=self.steps_per_cycle(),
            n_assets=len(self.assets), assets=", ".join(self.assets), context=", ".join(m["context"]) or "none",
            timeout=self.cfg["tools"]["script_timeout_s"], globs=" ".join(_GLOBS))

    def n_steps(self) -> int:
        return self.feed.n_steps()

    def steps_per_cycle(self) -> int:
        return max(1, round(self.meta["cycle_days"] / self.meta["time_gap"]))

    def release(self, step: int) -> None:
        if type(step) is not int or not 0 <= step < self.n_steps():
            raise ConnectorError(f"no step {step}")
        self.current = step
        self._data(step - 1)
        self._data(step)

    def begin_cycle(self, agent_ids) -> None:
        self.portfolios = {a: Portfolio(START_CASH) for a in agent_ids}
        self.scores = {a: 0.0 for a in agent_ids}
        self._reset_benchmark()

    def run_step(self, agent_id: str, agent_dir, step: int) -> dict:
        if step != self.current:
            raise ConnectorError(f"step {step} is not the released step ({self.current})")
        self.reports.pop(agent_id, None)             # a step that fails midway never shows the previous report
        p = self.portfolios.setdefault(agent_id, Portfolio(START_CASH))
        bench_return = self._benchmark(step)
        closes = dict(self._last_close(step))
        before = p.value(closes)
        rows, errors, stderr = self._backtest(Path(agent_dir), step, p, closes)
        end = rows[-1]["value_close"]
        cycle_return = end / START_CASH - 1
        self.scores[agent_id] = cycle_return - bench_return
        self.reports[agent_id] = {"step": step, "days": rows, "errors": errors, "stderr": stderr}
        return {"step_return": end / before - 1 if before > 0 else 0.0, "cycle_return": cycle_return,
                "benchmark_cycle_return": bench_return, "excess_return": cycle_return - bench_return,
                "fees": sum(r["fee"] for r in rows), "trades": sum(r["trades"] for r in rows),
                "cash_share": rows[-1]["cash_share"], "errors": len(errors), "days": len(rows)}

    def cycle_score(self, agent_id: str) -> float:
        return self.scores.get(agent_id, 0.0)

    def tools(self, agent_id: str, agent_dir, step: int) -> list:
        upto = lambda: step if self.current is None else min(step, self.current)   # never past the built step
        return [
            Tool("read_prices", "Released daily prices as JSON rows (at most 400 per call; ask again from "
                 "next_start). Without series: the series names and the released date range.",
                 {"type": "object", "properties": {
                     "series": {"type": "array", "items": {"type": "string"}},
                     "start": {"type": "string", "description": "YYYY-MM-DD"},
                     "end": {"type": "string", "description": "YYYY-MM-DD"}}},
                 lambda a: self._read_prices(a, upto())),
            Tool("wayback_fetch", "An archived web page (Wayback Machine) from an allowed news or statistics site, "
                 "the latest snapshot dated no later than the released step's end, as plain text.",
                 {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
                 lambda a: wayback.fetch(a["url"], self.feed.step_end(upto()), http=self.http,
                                         cache=self._wayback_cache)),
            Tool("backtest_report", "Your strategy's last backtested step, day by day: value, cash share, "
                 "weights applied, fee, and any errors.", {"type": "object", "properties": {}},
                 lambda a: self._report(agent_id, upto())),
        ]

    def cleaning_rules(self) -> dict:
        return {"data_file": "data.md",
                "what_counts_as_data": "prices, dated moves, hard-coded dates or price levels, asset names (Asset A, Asset B, ...), e.g. "
                                       "'2025-03-04: Asset C closed at 512.34' or a list of past closes",
                "patterns": list(_PATTERNS),
                "file_globs": list(_GLOBS)}

    def starter_files(self) -> dict:
        return {"strategy.py": (HERE / "starter_strategy.py").read_text()}

    # ---- optional methods -----------------------------------------------------------------------------------
    def script_files(self, agent_id: str, step: int) -> dict:
        files = dict(self._data(step if self.current is None else min(step, self.current)))
        return {**files, "/data/replay.py": HERE / "replay.py"}

    def target_score(self) -> float:
        if self._target is None:
            total = 0.0
            for steps in split_cycles(self.n_steps(), self.steps_per_cycle()):
                days = [d for k in steps for d in self.feed.days(k)]
                ref, bench = Portfolio(START_CASH), Portfolio(START_CASH)
                r = run_days(BuyAndHold(sixty_forty(self.meta["assets"])), days, ref,
                             dict(self._last_close(steps[0])), FEE)
                b = run_days(BuyAndHold(equal_weight(self.assets)), days, bench, dict(self._last_close(steps[0])), 0.0)
                total += (r[-1]["value_close"] - b[-1]["value_close"]) / START_CASH
            self._target = total + TARGET_MARGIN
        return self._target

    # ---- helpers --------------------------------------------------------------------------------------------
    def _data(self, upto: int) -> dict:
        """The /data files with every day released up to `upto` (kept for the last few `upto`s)."""
        with self._files_lock:
            return self._data_locked(upto)

    def _data_locked(self, upto: int) -> dict:
        if upto not in self._files:
            keep = {self.current, (self.current or 0) - 1}
            while len(self._files) >= 3:
                old = next((k for k in self._files if k not in keep), next(iter(self._files)))
                shutil.rmtree(self._tmp / f"upto{old + 1}", ignore_errors=True)
                del self._files[old]
            self._files[upto] = self.feed.write_files(upto, self._tmp / f"upto{upto + 1}")
        return self._files[upto]

    def _last_close(self, step: int) -> dict:
        if step not in self._closes:
            self._closes[step] = self.feed.last_close(step - 1)
        return self._closes[step]

    def _reset_benchmark(self) -> None:
        self._bench = Portfolio(START_CASH)
        self._bench_decide = BuyAndHold(equal_weight(self.assets))
        self._bench_step, self._bench_return = None, 0.0

    def _benchmark(self, step: int) -> float:
        """The equal-weight buy-and-hold's cycle return after `step` (advanced once per step, not per agent)."""
        if self._bench_step != step:
            rows = run_days(self._bench_decide, self.feed.days(step), self._bench, dict(self._last_close(step)), 0.0)
            self._bench_step, self._bench_return = step, rows[-1]["value_close"] / START_CASH - 1
        return self._bench_return

    def _backtest(self, agent_dir: Path, step: int, p: Portfolio, closes: dict):
        days, errors, stderr, rows = self.feed.days(step), [], "", []
        session, alive = None, False
        strategy = agent_dir / "strategy.py"
        if not strategy.is_file() or strategy.is_symlink():
            errors.append("fatal: no strategy.py in your folder")
        else:
            try:
                session = Session(agent_dir, self.cfg, RUNNER, {RUNNER: HERE / "runner.py", **self._data(step - 1)})
                first = session.ask({"assets": self.assets, "context": self.meta["context"]})
                alive = bool(first and first.get("ready"))
                if not alive:
                    errors.append(f"fatal: {(first or {}).get('fatal') or session.error}")
            except Exception as e:
                errors.append(f"fatal: could not start the backtest: {type(e).__name__}: {e}"[:500])
        try:
            for i, d in enumerate(days):
                w = {}
                if alive:
                    answer = session.ask({"date": d["date"], "add": [days[i - 1]] if i else []})
                    if answer is None:
                        alive = False
                        errors.append(f"{d['date']}: {session.error}; cash from here to the step's end")
                    elif "weights" in answer:
                        w = clip_weights(answer["weights"], self.assets)
                    elif answer.get("hold"):
                        w = None
                    else:
                        errors.append(f"{d['date']}: {answer.get('error', 'a reply the backtest cannot read')}")
                rows.append(trade_day(p, w, d["tradable"], closes, FEE, d["date"]))
        finally:
            if session is not None:
                stderr = session.close()["stderr"]
        return rows, errors, stderr

    def _report(self, agent_id: str, upto: int) -> str:
        rep = self.reports.get(agent_id)
        if not rep or rep["step"] > upto:
            return "no backtest yet"
        days = [{"date": r["date"], "value_close": round(r["value_close"], 2), "fee": round(r["fee"], 2),
                 "trades": r["trades"], "cash_share": round(r["cash_share"], 4),
                 "weights_applied": {a: (None if w is None else round(w, 4)) for a, w in r["weights_applied"].items()}}
                for r in rep["days"]]
        return json.dumps({"step": rep["step"], "days": days, "errors": rep["errors"],
                           "stderr": rep["stderr"][-2000:]})

    def _read_prices(self, args: dict, upto: int) -> str:
        last = self.feed.step_end(upto)
        released = self.feed.released(upto)
        first = released[0]["date"] if released else last
        series = args.get("series")
        if series is None:
            return json.dumps({"tradable": self.assets, "context": self.meta["context"], "first_date": first,
                               "last_date": last})
        known = set(self.assets) | set(self.meta["context"])
        if not isinstance(series, list) or not series or not all(isinstance(s, str) and s in known for s in series):
            raise ToolError(f"series must be a list of names from: {', '.join(sorted(known))}")
        start, end = args.get("start", first), args.get("end", last)
        if not all(isinstance(x, str) and _ISO.fullmatch(x) for x in (start, end)):
            raise ToolError("start and end must be YYYY-MM-DD")
        end = min(end, last)
        rows, next_start = [], None
        for d in released:
            if not start <= d["date"] <= end:
                continue
            day_rows = []
            for s in series:
                if s in d["tradable"]:
                    day_rows.append({"date": d["date"], "series": s, **d["tradable"][s]})
                elif s in d.get("context", {}):
                    day_rows.append({"date": d["date"], "series": s, "value": d["context"][s]})
            if rows and len(rows) + len(day_rows) > READ_ROWS:
                next_start = d["date"]
                break
            rows += day_rows
        return json.dumps({"rows": rows, "next_start": next_start, "last_date": last})


def make_connector(cfg, data=None):
    return Connector(cfg, data)
