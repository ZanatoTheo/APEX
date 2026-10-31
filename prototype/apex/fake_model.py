"""Fake model implementing the LLMService contract (JC-34). Deterministic for a given seed and prompt.

Subagent role: an oracle gated by the agent's axioms. It reads the editable file, then patches. If the axioms
(the "Operating principles" section of the system prompt) contain the skill keyword for the task's bug
family, the reference fix is likely; otherwise the patch is usually a harmless no-op. A retry that has seen
failing test output does better, which rewards graphs with a verify loop.

Mutation role: reads the failing output in the trace like a model would ("TypeError" → type advice, assertion
failures → boundary advice) and proposes axiom edits or graph edits, sometimes unhelpful, sometimes invalid.
"""
import hashlib
import json
import random
import re

from . import config as config_mod
from .prompts import ACTIONS_HEADER, AXIOMS_HEADER, TOOL_DOCS

SKILL_KEYWORDS = {"off_by_one": "boundar", "type_error": "type"}   # matched at a word start in the axioms only
SKILL_AXIOMS = {
    "off_by_one": "Check loop and slice boundaries for off-by-one errors: compare range ends and indexes "
                  "with the counts the docstring promises.",
    "type_error": "When an operation mixes value types, convert explicitly with str() or int() where the "
                  "values are used.",
}
NOISE_AXIOMS = [
    "Prefer clear, readable code over clever code.",
    "Keep the original function signature unchanged.",
    "Think about the whole module before acting, and consider several alternative fixes in detail.",
]
P_SKILLED, P_UNSKILLED, P_RETRY_AFTER_FAIL = 0.9, 0.1, 0.4
MAX_PATCH_ATTEMPTS = 3
TOOL_OUTPUT = re.compile(r'<tool_output tool="(\w+)" status="(\w+)">\n(.*?)\n</tool_output>', re.S)


class FakeModel:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.seed = cfg["run"]["seed"]
        self.oracle = config_mod.resolve_path(cfg, "oracle")
        self.index = json.loads((self.oracle / "index.json").read_text(encoding="utf-8"))

    def complete(self, role: str, messages: list[dict], max_tokens: int) -> dict:
        text = self._subagent(messages) if role == "subagent" else self._mutation(messages)
        return {"text": text, "model_id": self.cfg["models"][role]["model_id"],
                "usage": {"input_tokens": sum(len(m["content"]) for m in messages) // 4,
                          "output_tokens": max(len(text) // 4, 1)}}

    def _rng(self, *parts) -> random.Random:
        digest = hashlib.sha256(json.dumps([self.seed, *parts]).encode()).hexdigest()
        return random.Random(int(digest[:16], 16))

    @staticmethod
    def _wrap(obj: dict, rng: random.Random) -> str:
        text = json.dumps(obj)
        style = rng.randrange(4)
        if style == 0:
            return f"```json\n{text}\n```"
        if style == 1:
            return f"Here is my next action.\n{text}"
        return text

    # -- subagent ----------------------------------------------------------------------------------------
    def _subagent(self, messages: list[dict]) -> str:
        system, task_msg = messages[0]["content"], messages[1]["content"]
        axioms = system.split(AXIOMS_HEADER, 1)[-1].split(ACTIONS_HEADER, 1)[0].lower()
        labels = {}
        for label, desc in re.findall(r'^- "([^"]+)": (.*)$', system, re.M):
            for tool, (_, doc) in TOOL_DOCS.items():
                if desc.startswith(doc):
                    labels[tool] = label
            if desc.startswith("Stop working"):
                labels.setdefault("stop", label)
        task_id = re.search(r"^Task (\S+):", task_msg, re.M).group(1)
        files = re.search(r"^Editable files: (.*)$", task_msg, re.M).group(1).split(", ")
        outputs = TOOL_OUTPUT.findall("\n".join(m["content"] for m in messages[2:] if m["role"] == "user"))
        reads = [o for o in outputs if o[0] == "read_file" and o[1] == "ok"]
        attempts = sum(1 for o in outputs if o[0] == "write_patch")
        saw_fail = any(o[0] == "run_tests" and o[1] == "fail" for o in outputs)
        last = outputs[-1] if outputs else None
        rng = self._rng("subagent", task_id, axioms, attempts, saw_fail)

        def act(tool, args):
            return self._wrap({"outcome": labels[tool], "args": args}, rng)

        if "read_file" in labels and not reads:
            return act("read_file", {"path": files[0]})
        if last and last[0] == "run_tests" and last[1] == "pass" and "stop" in labels:
            return act("stop", {})
        if last and last[0] == "write_patch" and last[1] == "applied" and "run_tests" in labels:
            return act("run_tests", {})
        if "write_patch" in labels and attempts < MAX_PATCH_ATTEMPTS:
            family = self.index.get(task_id)
            skilled = family in SKILL_KEYWORDS and re.search(r"\b" + SKILL_KEYWORDS[family], axioms) is not None
            p = P_SKILLED if skilled else (P_RETRY_AFTER_FAIL if saw_fail else P_UNSKILLED)
            if rng.random() < p:
                diff = (self.oracle / f"{task_id}.diff").read_text(encoding="utf-8")
            else:
                first = (reads[-1][2].splitlines() or [""])[0] if reads else ""
                diff = (f"--- a/{files[0]}\n+++ b/{files[0]}\n@@ -1 +1,2 @@\n"
                        f"+# NOTE: reviewed for the reported bug\n {first}\n")
            return act("write_patch", {"diff": diff})
        if "stop" in labels:
            return act("stop", {})
        first_label = re.search(r'^- "([^"]+)"', system, re.M)
        return self._wrap({"outcome": first_label.group(1) if first_label else "error", "args": {}}, rng)

    # -- mutation ----------------------------------------------------------------------------------------
    def _mutation(self, messages: list[dict]) -> str:
        user = messages[1]["content"]
        scope = re.search(r"^Part to edit: (\w+)", user, re.M).group(1)
        current = json.loads(user.split("Current value:\n", 1)[1].split("\n\nTrace of", 1)[0])
        trace = user.split("Trace of the run", 1)[1]
        n_errors = sum("previous proposal was invalid" in m["content"] for m in messages[2:])
        max_axioms = int(re.search(r"Axioms: at most (\d+)", user).group(1))
        rng = self._rng("mutation", user, n_errors)
        if n_errors == 0 and rng.random() < 0.1:   # exercise the validation-retry path (design §10)
            bad = ([{"op": "move", "from": "/start", "path": "/x"}] if scope == "graph_config"
                   else [{"op": "replace", "index": 99, "text": "x"}])
            return self._wrap({"format": "json_patch" if scope == "graph_config" else "axiom_edit",
                               "content": bad, "rationale": "tighten the agent"}, rng)
        if scope == "graph_config":
            ops, why = self._graph_edit(current, rng)
            return self._wrap({"format": "json_patch", "content": ops, "rationale": why}, rng)
        ops, why = self._axiom_edit(current, trace, max_axioms, rng)
        return self._wrap({"format": "axiom_edit", "content": ops, "rationale": why}, rng)

    @staticmethod
    def _graph_edit(graph: dict, rng: random.Random):
        nodes = graph["nodes"]
        has_verify = any(n.get("tool") == "run_tests" for n in nodes)
        patch_i = next((i for i, n in enumerate(nodes) if n.get("tool") == "write_patch"), None)
        llm = next((n["id"] for n in nodes if n["kind"] == "llm"), None)
        done = next((n["id"] for n in nodes if n["kind"] == "terminal"), None)
        if not has_verify and patch_i is not None and llm and done and rng.random() < 0.7:
            j = next((j for j, t in enumerate(nodes[patch_i]["transitions"]) if t["on"] == "applied"), None)
            if j is not None:
                verify = {"id": "verify", "kind": "tool", "tool": "run_tests",
                          "transitions": [{"on": "pass", "to": done}, {"on": "fail", "to": llm},
                                          {"on": "timeout", "to": done}]}
                return ([{"op": "add", "path": "/nodes/-", "value": verify},
                         {"op": "replace", "path": f"/nodes/{patch_i}/transitions/{j}/to", "value": "verify"}],
                        "Run the public tests after patching and retry when they fail.")
        step = rng.choice([-2, 2])
        return ([{"op": "replace", "path": "/max_steps", "value": max(4, min(30, graph["max_steps"] + step))}],
                "Adjust the step cap to the observed run length.")

    @staticmethod
    def _axiom_edit(axioms: list[str], trace: str, max_axioms: int, rng: random.Random):
        failing = "TypeError" in trace or "AssertionError" in trace or "FAILED" in trace
        want = SKILL_AXIOMS["type_error"] if "TypeError" in trace else SKILL_AXIOMS["off_by_one"]
        other = next(a for a in SKILL_AXIOMS.values() if a != want)
        noise_idx = [i for i, a in enumerate(axioms) if a in NOISE_AXIOMS]

        def add(text):
            if len(axioms) >= max_axioms:
                victim = noise_idx[0] if noise_idx else 0
                return [{"op": "replace", "index": victim, "text": text}]
            return [{"op": "add", "index": len(axioms), "text": text}]

        r = rng.random()
        if not failing:   # all public tests passed: aim at cost
            if noise_idx:
                return [{"op": "remove", "index": noise_idx[0]}], "Drop a principle that only adds tokens."
            return add(rng.choice(NOISE_AXIOMS)), "Add a general principle."
        if r < 0.75:
            if want not in axioms:
                return add(want), "Give the agent the specific check this failure calls for."
            if other not in axioms:
                return add(other), "Cover the other common bug family as well."
            if noise_idx:
                return [{"op": "remove", "index": noise_idx[0]}], "Drop a principle that only adds tokens."
        return add(rng.choice(NOISE_AXIOMS)), "Add a general principle."
