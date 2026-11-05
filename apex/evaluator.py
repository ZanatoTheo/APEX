"""The Evaluator: hidden notes on each agent's logic.

Scores are public; these notes are not. They are written to <run>/hidden/eval/, outside every agent folder, and are
read only by Op. Orch and Mutation. They never go into an agent's report (call_agent keeps numbers only).
"""
import json
from pathlib import Path

from . import prompts
from .jsonreply import ask_json
from .orchestrator import _axis_key
from .selection import select

EVAL_FIELDS = ("strengths", "weaknesses", "axiom_flaws", "axiom_fixes")


class Evaluator:
    def __init__(self, cfg: dict, budget, model, hidden_dir):
        self.cfg, self.budget, self.model = cfg, budget, model
        self.op = cfg["operation"]
        self.hidden_dir = Path(hidden_dir)

    def check_note(self, obj, axes=None):
        for key in EVAL_FIELDS[:3]:
            v = obj.get(key)
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                return f"{key} must be a list of strings"
        fixes = obj.get("axiom_fixes")
        if not isinstance(fixes, list):
            return "axiom_fixes must be a list"
        axes = {_axis_key(a) for a in (axes or self.op["axes"])}
        for i, fix in enumerate(fixes):
            if not isinstance(fix, dict) or not all(isinstance(fix.get(k), str) for k in ("axis", "fix", "why")):
                return f"axiom_fixes[{i}] must have string axis, fix and why"
            if _axis_key(fix["axis"]) not in axes:
                return f"axiom_fixes[{i}] names an unknown axis: {fix['axis']}"
        return None

    def judge(self, cycle: int, agents, scores: dict, brief: str, axes=None) -> dict:
        axes = list(axes or self.op["axes"])     # Op. Orch's current axes (approved new ones included)
        out_dir = self.hidden_dir / "eval" / f"cycle-{cycle}"
        out_dir.mkdir(parents=True, exist_ok=True)
        sel = select({a.id: scores.get(a.id) for a in agents}, self.cfg)   # same rank and average as selection
        avg = sel["avg"]
        notes = {}
        for a in agents:
            rank = sel["ranking"].index(a.id) + 1
            messages = [{"role": "system", "content": prompts.eval_system()},
                        {"role": "user", "content": prompts.eval_message(
                            brief, axes, a.id, a.axioms, rank, len(agents), scores.get(a.id), avg,
                            a.step_summaries(), a.files_text(self.op["eval_files_chars"]))}]
            try:
                obj = ask_json(self.budget, self.model, "evaluator", messages, lambda o: self.check_note(o, axes),
                               self.op["eval_output_tokens"])
                note = {k: obj[k] for k in EVAL_FIELDS}
            except Exception as e:           # one agent's failed judgment never stops the cycle
                note = {"error": f"{type(e).__name__}: {e}"[:300]}
            note.update({"agent": a.id, "cycle": cycle, "score": scores.get(a.id), "rank": rank})
            (out_dir / f"{a.id}.json").write_text(json.dumps(note, indent=1))
            notes[a.id] = note
        return notes
