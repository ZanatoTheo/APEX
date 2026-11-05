"""The run log: one JSON line per event in <run>/log.jsonl, each with `t` and `event`.

Events: run_start, gen0, step, cycle_end, loop_end, generation, cleaner, stop; holdout_start, holdout_cleaner,
holdout_step and holdout_end for the held-out walk; budget for what CycleBudget.events held. A line is written whole
(open, write, close), so a killed run leaves a readable log.
"""
import json
from datetime import datetime, timezone
from pathlib import Path


class RunLog:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._drained = 0                     # budget events already written

    def event(self, kind: str, /, **fields) -> dict:      # positional-only: a field may be named "kind"
        entry = {"t": datetime.now(timezone.utc).isoformat(timespec="seconds"), "event": kind, **fields}
        with open(self.path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
        return entry

    def drain(self, budget) -> list:
        """Write the budget's new events as `budget` events (their own `event` key becomes `what`); return them."""
        new = budget.events[self._drained:]
        self._drained = len(budget.events)
        for e in new:
            fields = {("what" if k == "event" else k): v for k, v in e.items()}
            self.event("budget", **fields)
        return new
