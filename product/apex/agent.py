"""Swarm Subagent (design §6, §16 Graph Config; CODE_STRUCTURE §5.3): validation and the interpreter.

The interpreter is trusted orchestrator code on the host (JC-02 option 1). Only tools touch the workspace.
"""
import time
from collections import deque
from dataclasses import dataclass, field

from . import canonical, prompts
from .models import BudgetExceeded, ModelError

TOOL_OUTCOMES = {"read_file": {"ok", "error"}, "write_patch": {"applied", "rejected"},
                 "run_tests": {"pass", "fail", "timeout"}}
PREDICATES = {"has_patch": lambda ws: "yes" if ws.diff() else "no"}   # fixed set (JC-08)
PREDICATE_OUTCOMES = {"has_patch": {"yes", "no"}}
MAX_STEPS_CAP = 50


class GraphError(ValueError):
    pass


def validate_axioms(axioms, max_axioms: int, max_chars: int) -> None:
    if not isinstance(axioms, list) or not 1 <= len(axioms) <= max_axioms:
        raise GraphError(f"prompt axioms must be a list of 1..{max_axioms} strings")
    for i, a in enumerate(axioms):
        if not isinstance(a, str) or not a.strip() or len(a) > max_chars or "\n" in a:
            raise GraphError(f"axiom {i} must be a single non-empty line of at most {max_chars} characters")


def validate_graph(graph, n_axioms: int) -> None:
    """design §16: unique ids, existing targets, a terminal reachable from start, known tools."""
    if not isinstance(graph, dict):
        raise GraphError("graph config must be an object")
    for key, typ in (("graph_version", str), ("start", str), ("max_steps", int), ("nodes", list)):
        if not isinstance(graph.get(key), typ) or isinstance(graph.get(key), bool):
            raise GraphError(f"graph config needs {key} ({typ.__name__})")
    if not 1 <= graph["max_steps"] <= MAX_STEPS_CAP:
        raise GraphError(f"max_steps must be within 1..{MAX_STEPS_CAP}")
    nodes = {}
    for n in graph["nodes"]:
        if not isinstance(n, dict) or not isinstance(n.get("id"), str) or not isinstance(n.get("transitions"), list):
            raise GraphError("every node needs a string id and a transitions list")
        if n["id"] in nodes:
            raise GraphError(f"duplicate node id {n['id']!r}")
        nodes[n["id"]] = n
    if graph["start"] not in nodes:
        raise GraphError(f"start node {graph['start']!r} does not exist")
    for n in nodes.values():
        kind = n.get("kind")
        labels = []
        for t in n["transitions"]:
            if not isinstance(t, dict) or not isinstance(t.get("on"), str) or not isinstance(t.get("to"), str):
                raise GraphError(f"node {n['id']!r}: transitions need string 'on' and 'to'")
            if t["to"] not in nodes:
                raise GraphError(f"node {n['id']!r}: transition target {t['to']!r} does not exist")
            labels.append(t["on"])
        if len(labels) != len(set(labels)):
            raise GraphError(f"node {n['id']!r}: duplicate outcome labels")
        if kind == "llm":
            refs = n.get("axiom_refs")
            if refs is not None and (not isinstance(refs, list) or
                                     not all(isinstance(r, int) and 0 <= r < n_axioms for r in refs)):
                raise GraphError(f"node {n['id']!r}: axiom_refs must index the {n_axioms} axioms")
            if not [label for label in labels if label != "error"]:
                raise GraphError(f"llm node {n['id']!r} offers no actions")
        elif kind == "tool":
            if n.get("tool") not in TOOL_OUTCOMES:
                raise GraphError(f"node {n['id']!r}: unknown tool {n.get('tool')!r}")
            if not set(labels) <= TOOL_OUTCOMES[n["tool"]]:
                raise GraphError(f"node {n['id']!r}: {n['tool']} outcomes are {sorted(TOOL_OUTCOMES[n['tool']])}")
        elif kind == "check":
            pred = n.get("predicate", n["id"])
            if pred not in PREDICATES or not set(labels) <= PREDICATE_OUTCOMES[pred]:
                raise GraphError(f"node {n['id']!r}: unknown check predicate {pred!r}")
        elif kind == "terminal":
            if labels:
                raise GraphError(f"terminal node {n['id']!r} cannot have transitions")
        else:
            raise GraphError(f"node {n['id']!r}: unknown kind {kind!r}")
    seen, queue = {graph["start"]}, deque([graph["start"]])
    while queue:
        for t in nodes[queue.popleft()]["transitions"]:
            if t["to"] not in seen:
                seen.add(t["to"])
                queue.append(t["to"])
    if not any(nodes[i]["kind"] == "terminal" for i in seen):
        raise GraphError("no terminal node is reachable from start")


@dataclass
class Agent:
    agent_id: str
    lineage_id: str
    parent_agent_id: str | None
    generation: int
    graph: dict
    axioms: list
    branch_id: str = ""
    status: str = "active"

    @property
    def state_machine_version(self) -> str:
        return canonical.hash_obj({"graph": self.graph, "axioms": self.axioms})[:16]

    def record(self) -> dict:
        """Subagent Instance (design §16) plus the units, stored as a blob."""
        return {"agent_id": self.agent_id, "parent_agent_id": self.parent_agent_id, "generation": self.generation,
                "lineage_id": self.lineage_id, "state_machine_version": self.state_machine_version,
                "status": self.status, "graph_config": self.graph, "prompt_axioms": self.axioms}


@dataclass
class RunResult:
    task_id: str
    agent_id: str
    outcome: str                 # terminal:<id> | max_steps | token_budget | timeout | no_transition:<label> | infra_error
    steps: int
    tokens: int
    latency_ms: int
    patch: str
    transitions: list            # ledger state_transitions of the agent_run block
    violations: list = field(default_factory=list)
    infra_error: str | None = None
    test_output_hash: str | None = None   # last public run_tests output seen by the agent, if any


KEEP_RECENT = 4          # messages kept in full; older tool outputs are shortened
OLD_OUTPUT_CHARS = 600


def _compact(history: list[dict]) -> list[dict]:
    """Shorten older tool outputs so long runs stay within the per-run token budget."""
    out = []
    for i, m in enumerate(history):
        old = i < len(history) - KEEP_RECENT
        if old and m["role"] == "user" and len(m["content"]) > OLD_OUTPUT_CHARS:
            m = {**m, "content": m["content"][:OLD_OUTPUT_CHARS] + "\n…[older output shortened]…\n</tool_output>"}
        out.append(m)
    return out


def run_agent(agent: Agent, task, client, ws, blobs, token_budget: int, timeout_s: int) -> RunResult:
    graph = agent.graph
    nodes = {n["id"]: n for n in graph["nodes"]}
    node = nodes[graph["start"]]
    history, transitions = [], []
    steps = tokens = 0
    pending_args: dict = {}
    end, infra, test_output_hash = None, None, None
    started = time.monotonic()

    def record(action, outcome, result_hash):
        transitions.append({"agent_id": agent.agent_id, "step": len(transitions), "action": action,
                            "outcome": outcome, "result_hash": result_hash})

    while node["kind"] != "terminal":
        if steps >= graph["max_steps"]:
            end = "max_steps"
            break
        if tokens >= token_budget:
            end = "token_budget"
            break
        if time.monotonic() - started > timeout_s:
            end = "timeout"
            break
        kind = node["kind"]
        if kind == "llm":
            refs = node.get("axiom_refs")
            axioms = agent.axioms if refs is None else [agent.axioms[i] for i in refs]
            allowed = [t["on"] for t in node["transitions"] if t["on"] != "error"]
            if history and history[-1]["role"] == "assistant":   # llm → llm: every request must end on a user turn
                history.append({"role": "user", "content": f"Continue. You are now at step '{node['id']}'."})
            messages = ([{"role": "system", "content": prompts.subagent_system(axioms, node, nodes)},
                         {"role": "user", "content": prompts.task_message(task)}] + _compact(history))
            try:
                completion = client.complete("subagent", messages)
            except (BudgetExceeded, ModelError) as e:
                end, infra = "infra_error", str(e)
                break
            tokens += completion.tokens
            history.append({"role": "assistant", "content": completion.text})
            try:
                label, pending_args = prompts.parse_action(completion.text, allowed)
            except prompts.ParseError as e:
                label, pending_args = "error", {}
                history.append({"role": "user", "content": f"Your reply was not a valid action: {e}. "
                                                           "Reply with exactly one JSON object."})
            record(f"llm:{node['id']}", label, completion.record_hash)
        elif kind == "tool":
            result = ws.exec(node["tool"], pending_args)
            label = result.status
            history.append({"role": "user", "content": prompts.tool_output(node["tool"], result.status, result.output)})
            h = blobs.put({"tool": node["tool"], "args": pending_args, "status": result.status,
                           "output": result.output, "data": result.data})
            if node["tool"] == "run_tests":
                test_output_hash = h
            pending_args = {}
            record(f"tool:{node['tool']}", label, h)
        else:   # check
            label = PREDICATES[node.get("predicate", node["id"])](ws)
            record(f"check:{node['id']}", label, blobs.put({"check": node["id"], "outcome": label}))
        steps += 1
        target = next((t["to"] for t in node["transitions"] if t["on"] == label), None)
        if target is None and kind == "llm" and label == "error":
            target = node["id"]   # no error edge: retry the same step (bounded by max_steps)
        if target is None:
            end = f"no_transition:{label}"
            break
        node = nodes[target]
    else:
        end = f"terminal:{node['id']}"
    latency_ms = int((time.monotonic() - started) * 1000)
    patch = ws.diff()
    final = blobs.put({"task_id": task.id, "outcome": end, "patch": patch, "steps": steps, "tokens": tokens,
                       "latency_ms": latency_ms, "violations": list(ws.violations), "infra_error": infra})
    record("end", end, final)
    return RunResult(task.id, agent.agent_id, end, steps, tokens, latency_ms, patch, transitions,
                     list(ws.violations), infra, test_output_hash)
