"""Mutation: reads every agent and drafts new ones for Op. Orch.

It ties strategies to axes, finds unaddressed variables on each axis, combines agents whose strengths cover each
other's weaknesses, and drafts free_slots + 2 agents. It may suggest a 3rd survivor and new axes. Its output is
hidden from agents (<run>/hidden/mutation/). A failure is never fatal: Op. Orch then fills the slots itself.
"""
import json
from pathlib import Path

from . import prompts
from .budget import CapReached
from .jsonreply import ask_json
from .orchestrator import _axis_key, check_drafts


class Mutation:
    def __init__(self, cfg: dict, budget, model, hidden_dir):
        self.cfg, self.budget, self.model = cfg, budget, model
        self.op = cfg["operation"]
        self.hidden_dir = Path(hidden_dir)

    def _check(self, obj, need: int, ids: set, survivors: list, taken: list, axes: list):
        drafts = obj.get("drafts")
        problem = check_drafts(axes, drafts, need, taken)
        if problem:
            return problem
        for i, d in enumerate(drafts):
            parents = d.get("parents", [])
            if not isinstance(parents, list) or not all(p in ids for p in parents):
                return f"draft {i} parents must be a list of agent ids from this cycle"
            start = d.get("start_files_from")
            if start is not None and start not in ids:
                return f"draft {i} start_files_from must be an agent id or null"
        third = obj.get("suggest_third_survivor")
        if third is not None and (third not in ids or third in survivors):
            return "suggest_third_survivor must be null or the id of an agent that is not already a survivor"
        new_axes = obj.get("new_axes", [])
        known = {_axis_key(a) for a in axes}
        if not isinstance(new_axes, list) or not all(
                isinstance(x, dict) and isinstance(x.get("axis"), str) and x["axis"].strip()
                and isinstance(x.get("why"), str) for x in new_axes):
            return "new_axes must be a list of {axis, why} strings"
        keys = [_axis_key(x["axis"]) for x in new_axes]
        if not all(keys) or len(set(keys)) != len(keys) or any(k in known for k in keys):
            return "new_axes need a name before ':' and must not repeat each other or an existing axis"
        return None

    def run(self, cycle: int, agents, eval_notes: dict, selection: dict, brief: str, axes: list) -> dict:
        survivors = list(selection["survivors"])
        need = self.op["agents"] - len(survivors) + 2
        ids = {a.id for a in agents}
        by_id = {a.id: a for a in agents}
        taken = [by_id[s].axioms for s in survivors if s in by_id]
        per_agent = max(1000, self.op["mutation_files_chars"] // max(1, len(agents)))
        blocks = []
        for aid in selection["ranking"]:
            a = by_id.get(aid)
            if a is None:
                continue
            blocks.append({"id": aid, "score": selection["scores"].get(aid),
                           "role": ("survivor" if aid in survivors else "base" if aid in selection["bases"]
                                    else "below"),
                           "axioms": a.axioms, "eval": eval_notes.get(aid, {}), "steps": a.step_summaries(),
                           "files": a.files_text(per_agent)})
        messages = [{"role": "system", "content": prompts.mutation_system()},
                    {"role": "user", "content": prompts.mutation_message(brief, axes, selection, blocks, need)}]
        try:
            obj = ask_json(self.budget, self.model, "mutation", messages,
                           lambda o: self._check(o, need, ids, survivors, taken, axes),
                           self.op["mutation_output_tokens"])
            result = {"cycle": cycle, "axis_analysis": obj.get("axis_analysis", []), "drafts": obj["drafts"],
                      "suggest_third_survivor": obj.get("suggest_third_survivor"),
                      "third_reason": obj.get("third_reason", ""), "new_axes": obj.get("new_axes", [])}
        except CapReached:                   # a budget stop is a stop
            raise
        except Exception as e:               # Op. Orch fills the slots itself
            result = {"cycle": cycle, "error": f"{type(e).__name__}: {e}"[:300], "axis_analysis": [], "drafts": [],
                      "suggest_third_survivor": None, "third_reason": "", "new_axes": []}
        out = self.hidden_dir / "mutation"
        out.mkdir(parents=True, exist_ok=True)
        (out / f"cycle-{cycle}.json").write_text(json.dumps(result, indent=1))
        return result
