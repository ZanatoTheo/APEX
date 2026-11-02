"""Evaluation Engine (design §9, §9.1, §13; CODE_STRUCTURE §5.4).

This is the only module that reads the holdout directory (JC-36). Each task run uses three workspaces:
  1. agent workspace: repo + public tests; the agent works here.
  2. public check: a fresh copy, the agent's final patch applied, public tests run → pass rate and L0 gates.
  3. hidden check: a fresh copy, the same patch, the task's hidden tests → written to blobs-holdout only.
Selection receives PublicResult objects, which have no hidden field, and opaque hidden hashes for the ledger.
Scores are integer ppm (JC-35).
"""
import math
from dataclasses import dataclass, field
from pathlib import Path

from . import canonical, corpus
from .agent import Agent, RunResult, run_agent
from .sandbox import Limits, Workspace

PPM = 1_000_000
# L0 gate definition, version 1 (design §9), recorded in Genesis.
GATES = {"version": 1, "gates": [
    "no_sandbox_violation",            # timeout / resource kill / tests modified inside the agent workspace
    "no_network_access",               # prototype: not enforceable on this host (JC-33); recorded as not checked
    "patch_applies_cleanly",           # the final patch passes the write_patch policy and applies to a fresh copy
    "tests_untouched",                 # test-directory hash unchanged
    "within_timeout",
    "within_token_budget",
]}


class EvaluationError(Exception):
    pass


class InfraError(Exception):
    """A task run failed for infrastructure reasons (model API, budget); the generation is aborted."""


# -- holdout reader ----------------------------------------------------------------------------------------

def hidden_tests_dir(holdout_dir: Path, task_id: str) -> Path:
    """Hidden tests of a public task: run against the agent's final patch, never mounted for the agent."""
    d = Path(holdout_dir) / "hidden_tests" / task_id
    if not d.is_dir():
        raise EvaluationError(f"no hidden tests for task {task_id}")
    return d


def heldout_tasks(holdout_dir: Path) -> list[corpus.Task]:
    return corpus.load_tasks(Path(holdout_dir) / "tasks")


def heldout_hidden_tests_dir(task: corpus.Task) -> Path:
    d = task.root / "hidden_tests"
    if not d.is_dir():
        raise EvaluationError(f"held-out task {task.id} has no hidden_tests/")
    return d


def holdout_manifest_hash(holdout_dir: Path) -> str:
    """Only the hash goes into Genesis, so a changed holdout is detectable without revealing it."""
    return canonical.hash_obj(corpus.dir_hashes(holdout_dir))


# -- scoring -----------------------------------------------------------------------------------------------

def clamp_ppm(x: int) -> int:
    return max(0, min(PPM, x))


def l1_components(pass_ppm: int, tokens: int, token_budget: int, latency_ms: int, timeout_s: int) -> dict:
    return {"pass_rate": clamp_ppm(pass_ppm),
            "token_term": clamp_ppm(PPM - tokens * PPM // token_budget),
            "latency_term": clamp_ppm(PPM - latency_ms * PPM // (timeout_s * 1000))}


def l1_ppm(components: dict, weights_ppm: dict) -> int:
    """design §9: L1 = 0.7·pass_rate + 0.2·(1 − tokens/budget) + 0.1·(1 − latency/timeout), each clamped."""
    return (weights_ppm["pass_rate"] * components["pass_rate"] + weights_ppm["tokens"] * components["token_term"]
            + weights_ppm["latency"] * components["latency_term"]) // PPM


@dataclass
class TaskPublic:
    task_id: str
    run: RunResult
    passed: int
    total: int
    l0_failures: list
    public_hash: str                  # blob with the public check result (incl. test output)
    block_hash: str = ""              # agent_run block, filled when the orchestrator appends it

    @property
    def pass_ppm(self) -> int:
        return self.passed * PPM // self.total if self.total else 0


@dataclass
class PublicResult:
    """What selection sees for one agent in one generation. Deliberately has no hidden field (§5.4)."""
    agent_id: str
    tasks: list = field(default_factory=list)
    l0_passed: bool = True
    components: dict = field(default_factory=dict)
    l1: int = 0
    tokens: int = 0
    tip_block_hash: str = ""

    @property
    def pass_ppm(self) -> int:
        return self.components.get("pass_rate", 0)


def _l0(run: RunResult, agent_ws_violations: list, policy_ok: bool, tests_ok: bool, cfg: dict) -> list[str]:
    limits = cfg["limits"]
    failures = []
    if agent_ws_violations:
        failures.append("sandbox_violation: " + ", ".join(sorted(set(agent_ws_violations))))
    if not policy_ok:
        failures.append("patch_applies_cleanly")
    if not tests_ok:
        failures.append("tests_untouched")
    if run.outcome == "timeout" or run.latency_ms > limits["timeout_s"] * 1000:
        failures.append("within_timeout")
    if run.outcome == "token_budget" or run.tokens > limits["token_budget"]:
        failures.append("within_token_budget")
    return failures


def evaluate_task(agent: Agent, task: corpus.Task, client, blobs, holdout_blobs, holdout_dir: Path,
                  cfg: dict, work_root: Path, hidden_dir: Path | None = None) -> tuple[TaskPublic, str]:
    """Run one agent on one task; return its public result and the hash of its hidden result."""
    limits = Limits(timeout_s=cfg["limits"]["test_timeout_s"], memory_mb=cfg["limits"]["memory_mb"])
    with Workspace.for_task(task, work_root, limits) as ws:
        run = run_agent(agent, task, client, ws, blobs, cfg["limits"]["token_budget"], cfg["limits"]["timeout_s"])
        agent_violations, tests_ok = list(ws.violations), ws.tests_intact()
    if run.infra_error:
        raise InfraError(f"{agent.agent_id} on {task.id}: {run.infra_error}")

    with Workspace.for_task(task, work_root, limits) as ws:
        applied = ws.write_patch(run.patch) if run.patch else None
        policy_ok = applied is None or applied.status == "applied"
        public = ws.run_tests() if policy_ok else None
    passed, total = (public.data["passed"], public.data["total"]) if public else (0, 1)
    l0 = _l0(run, agent_violations, policy_ok, tests_ok, cfg)
    public_hash = blobs.put({"agent_id": agent.agent_id, "task_id": task.id, "passed": passed, "total": total,
                             "l0_failures": l0, "tokens": run.tokens, "latency_ms": run.latency_ms,
                             "patch_status": applied.output if applied else "no patch",
                             "test_output": public.output if public else ""})
    outcome = "l0_fail" if l0 else ("pass" if total and passed == total else "fail")
    run.transitions.append({"agent_id": agent.agent_id, "step": len(run.transitions), "action": "eval:public",
                            "outcome": outcome, "result_hash": public_hash})

    hidden_dir = hidden_dir or hidden_tests_dir(holdout_dir, task.id)
    with Workspace.for_task(task, work_root, limits, tests_dir=hidden_dir) as ws:
        ok = (ws.write_patch(run.patch).status == "applied") if (run.patch and policy_ok) else not run.patch
        hidden = ws.run_tests().data if ok else {"passed": 0, "total": 1}
    hidden_hash = holdout_blobs.put({"agent_id": agent.agent_id, "task_id": task.id,
                                     "hidden_passed": hidden["passed"], "hidden_total": hidden["total"],
                                     "public_passed": passed, "public_total": total, "l0_failures": l0})
    return TaskPublic(task.id, run, passed, total, l0, public_hash), hidden_hash


def aggregate(agent_id: str, tasks: list[TaskPublic], cfg: dict) -> PublicResult:
    """Pass rate over the batch (fraction of public tests passed), tokens and latency summed over the batch."""
    passed = sum(t.passed for t in tasks)
    total = sum(t.total for t in tasks)
    tokens = sum(t.run.tokens for t in tasks)
    latency = sum(t.run.latency_ms for t in tasks)
    n = max(len(tasks), 1)
    comps = l1_components(passed * PPM // total if total else 0, tokens, cfg["limits"]["token_budget"] * n,
                          latency, cfg["limits"]["timeout_s"] * n)
    l0_passed = not any(t.l0_failures for t in tasks)
    return PublicResult(agent_id, tasks, l0_passed, comps,
                        l1_ppm(comps, cfg["l1_weights_ppm"]) if l0_passed else 0, tokens,
                        tasks[-1].block_hash if tasks else "")


def fitness_record(result: PublicResult, generation: int, batch_id: str) -> dict:
    """design §16 Fitness Record (public copy: hidden fields null). Values in ppm."""
    return {"agent_id": result.agent_id, "generation": generation, "rubric_window_id": "w0", "batch_id": batch_id,
            "l0_hard_gate_passed": result.l0_passed, "public_score": result.l1, "l1_components": result.components,
            "hidden_score": None, "divergence_metric": None, "units": "ppm"}


def write_hidden_fitness(public_record: dict, hidden_blob_hashes: list[str], holdout_blobs) -> str:
    """Evaluator-only copy with hidden_score and divergence_metric (L4). Returns only its hash, so the
    orchestrator can log it without ever holding a hidden value."""
    rows = [holdout_blobs.get(h) for h in hidden_blob_hashes]
    hp, ht = sum(r["hidden_passed"] for r in rows), sum(r["hidden_total"] for r in rows)
    pp, pt = sum(r["public_passed"] for r in rows), sum(r["public_total"] for r in rows)
    hidden = hp * PPM // ht if ht else 0
    public = pp * PPM // pt if pt else 0
    return holdout_blobs.put({**public_record, "hidden_score": hidden, "divergence_metric": public - hidden})


# -- final held-out evaluation and intervals ---------------------------------------------------------------

def _binom_cdf(k: int, n: int, p: float) -> float:
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))


def clopper_pearson(k: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    """Exact two-sided (1 − alpha) interval for k successes in n trials, by bisection on the binomial CDF."""
    if n == 0:
        return 0.0, 1.0

    def solve(cdf_k: int, target: float) -> float:
        """p where the binomial CDF at cdf_k equals target (the CDF decreases as p grows)."""
        lo, hi = 0.0, 1.0
        for _ in range(100):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if _binom_cdf(cdf_k, n, mid) > target else (lo, mid)
        return (lo + hi) / 2

    lower = 0.0 if k == 0 else solve(k - 1, 1 - alpha / 2)   # P(X ≥ k | p) = alpha/2
    upper = 1.0 if k == n else solve(k, alpha / 2)           # P(X ≤ k | p) = alpha/2
    return lower, upper


def holdout_report(run_dir: Path) -> dict:
    """Evaluator-side numbers for the operator report: L4 divergence per generation and held-out outcomes."""
    from .ledger import BlobStore, Ledger   # local import: ledger is not needed by the evaluation hot path
    ledger = Ledger(run_dir)
    try:
        events = [b for b in ledger.blocks() if b["kind"] == "generation_event"]
    finally:
        ledger.close()
    store = BlobStore(Path(run_dir) / "blobs-holdout", create=False)
    divergence, hidden_score, heldout = {}, {}, []
    for b in events:
        rows = [store.get(t["result_hash"]) for t in b["state_transitions"] if t["action"] == "hidden_fitness"]
        if rows:
            g = rows[0]["generation"]
            divergence[g] = sum(r["divergence_metric"] for r in rows) // len(rows)
            hidden_score[g] = sum(r["hidden_score"] for r in rows) // len(rows)
        for t in b["state_transitions"]:
            if t["action"] == "heldout_run":
                r = store.get(t["result_hash"])
                heldout.append({"agent_id": r["agent_id"], "task_id": r["task_id"], "success": r["success"]})
    return {"divergence_ppm": divergence, "hidden_score_ppm": hidden_score, "heldout": heldout}


def evaluate_heldout(agents: list[Agent], holdout_dir: Path, client, holdout_blobs, cfg: dict,
                     work_root: Path) -> list[str]:
    """Final survivors on the held-out tasks, once (design §9.1). Everything goes to blobs-holdout."""
    refs = []
    for agent in agents:
        for task in heldout_tasks(holdout_dir):
            tp, hidden_hash = evaluate_task(agent, task, client, holdout_blobs, holdout_blobs, holdout_dir, cfg,
                                            work_root, hidden_dir=heldout_hidden_tests_dir(task))
            row = holdout_blobs.get(hidden_hash)
            success = not tp.l0_failures and row["hidden_total"] > 0 and row["hidden_passed"] == row["hidden_total"]
            refs.append(holdout_blobs.put({"kind": "heldout_run", "agent_id": agent.agent_id, "task_id": task.id,
                                           "success": success, "hidden_ref": hidden_hash,
                                           "trace": [t["result_hash"] for t in tp.run.transitions]}))
    return refs
