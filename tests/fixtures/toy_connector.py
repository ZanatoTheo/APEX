"""A tiny task for testing the core. It is test-only: the core never imports it.

Each step reveals one number. An agent keeps `ANSWER = <number>` in answer.py as its guess for the number of the
step being run; it scores minus the distance. Step 7 also carries SECRET, which must never reach a prompt before
step 7 is released.
"""
import json
import math
import re

from apex.connector import ConnectorError
from apex.tools.registry import Tool

VALUES = [3, 5, 4, 8, 6, 7, 9, 8]
SECRET = "TOY-SECRET-9f3a1c"
_ANSWER = re.compile(r"^\s*ANSWER\s*=\s*(-?\d+(?:\.\d+)?)\s*$", re.M)


class ToyConnector:
    def __init__(self, cfg=None, data=None):
        if isinstance(data, str):                     # from the CLI: a path to a JSON list of numbers
            try:
                with open(data) as f:
                    data = json.load(f)
            except (OSError, ValueError) as e:
                raise ConnectorError(f"toy data: {type(e).__name__}: {e}") from None
        self.values = list(data) if data is not None else list(VALUES)
        self.current = None
        self.totals: dict[str, float] = {}

    def brief(self) -> str:
        return ("Each step reveals one number. Keep `ANSWER = <number>` in answer.py as your guess for the number of "
                "the next step; you score minus the distance. Call read_values to see the numbers revealed so far.")

    def n_steps(self) -> int:
        return len(self.values)

    def release(self, step: int) -> None:
        if not isinstance(step, int) or not 0 <= step < len(self.values):
            raise ConnectorError(f"no step {step}")
        self.current = step

    def begin_cycle(self, agent_ids) -> None:
        self.totals = {a: 0.0 for a in agent_ids}

    def _records(self, upto: int):
        """Records of steps <= min(upto, current): a tool built at an older step never shows newer data."""
        last = -1 if self.current is None else min(upto, self.current)
        out = []
        for i in range(last + 1):
            out.append({"step": i, "value": self.values[i], "note": SECRET if i == 7 else ""})
        return out

    def run_step(self, agent_id: str, agent_dir, step: int) -> dict:
        if step != self.current:
            raise ConnectorError(f"step {step} is not the released step ({self.current})")
        from pathlib import Path
        try:
            m = _ANSWER.search((Path(agent_dir) / "answer.py").read_text(errors="replace"))
        except OSError:
            m = None
        answer = float(m.group(1)) if m else None
        if answer is not None and (not math.isfinite(answer) or abs(answer) > 1e9):
            answer = None
        score = -10.0 if answer is None else -abs(answer - self.values[step])
        self.totals[agent_id] = self.totals.get(agent_id, 0.0) + score
        return {"step": step, "answer": answer, "score": score}

    def cycle_score(self, agent_id: str) -> float:
        return self.totals.get(agent_id, 0.0)

    def tools(self, agent_id: str, agent_dir, step: int) -> list:
        return [Tool("read_values", "The numbers revealed so far, as JSON.", {"type": "object", "properties": {}},
                     lambda args, upto=step: json.dumps(self._records(upto)))]

    def cleaning_rules(self) -> dict:
        return {"data_file": "data.md", "what_counts_as_data": "any revealed value or note, e.g. v3=8",
                "patterns": [r"\bv\d+\s*=\s*-?\d+(?:\.\d+)?", r"TOY-SECRET-[0-9a-f]+"], "file_globs": ["*.csv"]}

    def starter_files(self) -> dict:
        return {"answer.py": "ANSWER = 0\n"}


def make_connector(cfg, data=None):
    return ToyConnector(cfg, data)
