"""The scripted model behind `run.py run --fake`.

A FakeModel whose replies are valid for every role and know nothing about the task: agents write a note and finish,
Op. Orch and Mutation draft counter-named agents, Eval and the cleaner answer with empty lists. The counts each reply
needs are read from the prompt it answers.
"""
import ast
import json
import re

from .fake_model import FakeModel

_TOOL_OUTPUT = "function_call_output"


def _user_text(messages) -> str:
    """The first user message: the prompt being answered (a retry adds more messages after it)."""
    return next((m.get("content", "") for m in messages if m.get("role") == "user"), "")


def _number(pattern: str, text: str) -> int:
    m = re.search(pattern, text)
    if not m:
        raise ValueError(f"demo model: no match for {pattern!r} in the prompt")
    return int(m.group(1))


def demo_model(cfg: dict, threshold: float = 1e9, seed: int = 0) -> FakeModel:
    axes = list(cfg["operation"]["axes"])
    counter = {"n": 0}

    def draft(extra=None):
        counter["n"] += 1
        n = counter["n"]
        d = {"name": f"demo {n}", "approach": f"demo approach {n}",
             "axioms": {a: f"demo rule {n} for {a.split(':')[0]}" for a in axes}}
        d.update(extra or {})
        return d

    def agent(messages, offered, rng):
        names = {t["name"] for t in offered}
        if messages and messages[-1].get("type") == _TOOL_OUTPUT or "write_file" not in names:
            return {"tool_calls": [{"name": "finish", "arguments": {"summary": "worked on this step"}}]}
        return {"tool_calls": [{"name": "write_file",
                                "arguments": {"path": "notes.md", "content": "Worked on this step.\n"}}]}

    def mutation(messages, offered, rng):
        need = _number(r"Draft exactly (\d+) new agents", _user_text(messages))
        drafts = [draft({"parents": [], "start_files_from": None, "why": "demo"}) for _ in range(need)]
        return {"text": json.dumps({"axis_analysis": [], "drafts": drafts, "suggest_third_survivor": None,
                                    "third_reason": "", "new_axes": []})}

    def orchestrator(messages, offered, rng):
        text = _user_text(messages)
        if '"stop_threshold"' in text:
            need = _number(r"Draft (\d+) new agents", text)
            return {"text": json.dumps({"stop_threshold": threshold, "threshold_reason": "demo",
                                        "agents": [draft() for _ in range(need)]})}
        if '"decisions"' in text:
            n_agents = _number(r"always has (\d+) agents", text)
            survivors = ast.literal_eval(re.search(r"Survivors kept unchanged: (\[.*?\])\.", text).group(1))
            n_drafts = len(re.findall(r"^\[\d+\] ", text, re.M))
            free = n_agents - len(survivors)
            adopt = min(free, n_drafts)
            return {"text": json.dumps({
                "decisions": [{"draft": i, "adopt": i < adopt, "reason": "demo"} for i in range(n_drafts)],
                "third_survivor": False, "third_reason": "", "fills": [draft() for _ in range(free - adopt)],
                "axes": []})}
        if '"undo"' in text:
            return {"text": json.dumps({"undo": []})}
        if '"selected"' in text:
            ids = json.loads(re.search(r"Current agents, best loop score first: (\[.*?\])", text).group(1))
            return {"text": json.dumps({"selected": ids[0], "reason": "demo: best loop score",
                                        "report": "demo run"})}
        raise ValueError("demo model: unknown Op. Orch prompt")

    defaults = {
        "agent": agent,
        "subagent": {"text": "done"},
        "summarizer": {"text": "All agents ran this step."},
        "evaluator": {"text": json.dumps({"strengths": ["ran every step"], "weaknesses": [], "axiom_flaws": [],
                                          "axiom_fixes": []})},
        "cleaner": {"text": json.dumps({"facts": []})},
        "mutation": mutation,
        "orchestrator": orchestrator,
    }
    return FakeModel(cfg, {}, seed=seed, defaults=defaults)
