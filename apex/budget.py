"""Caps on model use.

- CycleBudget: dollars per cycle, for all roles together. `.call` is the path for the non-agent roles
  (orchestrator, summarizer, evaluator, mutation, cleaner). Their prompts can be larger than an agent's token cap,
  so only dollars are checked for them.
- CallBudget: one per call_agent. The agent's own tokens and turns, plus one token pool shared by all its subagents.

Every call is checked *before* it is sent, with the worst case: the input estimate plus the full output allowed.
Output is capped by max_output_tokens, so a cap can only be passed by an input estimate that was too low,
never by a whole extra reply.

The input estimate is the length of the messages and tools as JSON, divided by 4. For an agent or subagent call, the
output allowed is min(max_output_tokens, cap - used - estimate); below min_output_tokens the call isn't sent.
A call that fails is logged and charged nothing, since its cost is unknown. An input above the estimate is logged as
`estimate_low`, since a cap can be passed by that much.
"""
import json


class CapReached(Exception):
    """A cap would be passed by the next call. kind: call_tokens | call_turns | subagent_tokens | cycle_usd."""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind} cap reached{': ' + detail if detail else ''}")
        self.kind = kind


def estimate_input(messages: list, tools=None) -> int:
    return (len(json.dumps(messages)) + len(json.dumps(list(tools or [])))) // 4


class CycleBudget:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.limit = cfg["budget"]["cycle_usd"]
        self.cycle = 1
        self.spent_usd = 0.0
        self.events = []                      # written to the run log by runlog.py

    def _rates(self, role: str) -> dict:
        return self.cfg["pricing"][self.cfg["models"]["roles"][role]["model_id"]]

    def _check(self, role: str, est: int, allowed: int, agent_id=None) -> None:
        """Raise CapReached("cycle_usd") if the worst case of this call would pass the cycle's dollars."""
        rates = self._rates(role)
        worst = (est * rates["input"] + allowed * rates["output"]) / 1_000_000
        if self.spent_usd + worst > self.limit:
            self.events.append({"event": "cap", "kind": "cycle_usd", "agent_id": agent_id, "role": role,
                                "spent_usd": self.spent_usd, "worst_usd": worst, "cap": self.limit})
            raise CapReached("cycle_usd", f"spent {self.spent_usd:.4f} + worst {worst:.4f} > {self.limit}")

    def _send(self, model, role: str, messages: list, tools, allowed: int, effort, est: int,
              agent_id=None, scope=None) -> dict:
        """Call the model and charge the reply. A call that raises is logged and charged nothing (its cost is
        unknown). An input above the estimate is logged, since it means the caps can be passed by that much."""
        try:
            reply = model(role, messages, tools=tools, max_output_tokens=allowed, reasoning_effort=effort)
        except Exception as e:
            self.events.append({"event": "call_failed", "role": role, "agent_id": agent_id, "scope": scope,
                                "error": str(e)[:300]})
            raise
        actual = reply["usage"]["input_tokens"]
        if actual > est:
            self.events.append({"event": "estimate_low", "role": role, "agent_id": agent_id, "est": est,
                                "actual": actual})
        self.spent_usd += reply["cost_usd"]
        return reply

    def call(self, model, role: str, messages: list, *, tools=None, max_output_tokens: int | None = None,
             reasoning_effort=None) -> dict:
        """A non-agent role's call: only the cycle's dollars are checked."""
        if max_output_tokens is None:
            max_output_tokens = self.cfg["limits"]["max_output_tokens"]
        if type(max_output_tokens) is not int or max_output_tokens < 1:
            raise ValueError(f"max_output_tokens must be an int >= 1, got {max_output_tokens!r}")
        tools = list(tools or [])
        est = estimate_input(messages, tools)
        self._check(role, est, max_output_tokens)
        return self._send(model, role, messages, tools, max_output_tokens, reasoning_effort, est)

    def new_cycle(self) -> None:
        self.events.append({"event": "cycle_end", "cycle": self.cycle, "spent_usd": self.spent_usd})
        self.cycle += 1
        self.spent_usd = 0.0


class CallBudget:
    """One call_agent: the agent's own tokens and turns, and one pool shared by every subagent it spawns."""

    def __init__(self, cfg: dict, cycle: CycleBudget, agent_id: str):
        lim = cfg["limits"]
        self.cfg = cfg
        self.cycle = cycle
        self.agent_id = agent_id
        self.caps = {"agent": lim["call_tokens"], "subagent": lim["subagent_tokens"]}
        self.used = {"agent": 0, "subagent": 0}
        self.turns = 0

    def _stop(self, kind: str, scope: str, used: int, cap: int):
        self.cycle.events.append({"event": "cap", "kind": kind, "agent_id": self.agent_id, "scope": scope,
                                  "used": used, "cap": cap})
        raise CapReached(kind, f"{scope} used {used} of {cap}")

    def call(self, model, role: str, messages: list, *, tools=None, scope: str = "agent",
             reasoning_effort=None) -> dict:
        if scope not in self.caps:
            raise ValueError(f"scope must be 'agent' or 'subagent', got {scope!r}")
        lim = self.cfg["limits"]
        if scope == "agent" and self.turns >= lim["call_turns"]:
            self._stop("call_turns", scope, self.turns, lim["call_turns"])
        tools = list(tools or [])
        est = estimate_input(messages, tools)
        remaining = self.caps[scope] - self.used[scope]
        allowed = min(lim["max_output_tokens"], remaining - est)
        if allowed < lim["min_output_tokens"]:
            self._stop("call_tokens" if scope == "agent" else "subagent_tokens", scope, self.used[scope],
                       self.caps[scope])
        self.cycle._check(role, est, allowed, self.agent_id)
        if scope == "agent":
            self.turns += 1               # counted before sending: a call that fails still uses a turn
        reply = self.cycle._send(model, role, messages, tools, allowed, reasoning_effort, est, self.agent_id, scope)
        self.used[scope] += reply["usage"]["input_tokens"] + reply["usage"]["output_tokens"]
        return reply
