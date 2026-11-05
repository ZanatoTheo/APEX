"""The per-step summary Op. Orch reads. It never stops the operation: if the model call fails, the plain rows are the
summary.
"""
import json

from . import prompts
from .tools.files import cut

_CHARS = 3000


class Summarizer:
    def __init__(self, cfg: dict, budget, model):
        self.cfg, self.budget, self.model = cfg, budget, model

    def summarize(self, agents, step: int, results: dict) -> str:
        rows = []
        for a in agents:
            r = results.get(a.id) or {}
            call = r.get("call") or {}
            rows.append({"agent": a.id, "report": prompts.report_numbers(r.get("report") or {}),
                         "ended_by": call.get("ended_by"), "turns": call.get("turns"),
                         "files_changed": list(call.get("files_changed") or [])[:20],
                         "summary": cut(call.get("summary") or "", 500)})
        plain = "\n".join(json.dumps(row) for row in rows)
        messages = [{"role": "system", "content": prompts.summary_system()},
                    {"role": "user", "content": prompts.summary_prompt(step, plain)}]
        try:
            reply = self.budget.call(self.model, "summarizer", messages,
                                     max_output_tokens=self.cfg["operation"]["summary_output_tokens"])
            text = reply["text"].strip() or "(empty model summary)\n" + plain
        except Exception as e:                       # CapReached, LLMError, anything: fall back to the rows
            text = f"(no model summary: {type(e).__name__}: {e})\n{plain}"
        return cut(text, _CHARS)
