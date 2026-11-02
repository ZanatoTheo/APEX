"""Run statistics from the public record: ledger.sqlite (opened read-only) and blobs/ only.

Used by `run.py probe` (and `stats`). It reads what selection may read, never the evaluator-only
store, so its numbers can be shown to anyone, including a mutation prompt.
"""
import collections
import json
import sqlite3
from pathlib import Path

from . import canonical
from .ledger import BlobStore


class StatsError(ValueError):
    """The ledger doesn't have the shape the engine writes (damaged or foreign); run `run.py verify` on it."""


def _blocks(run_dir: Path, kind: str) -> list[dict]:
    uri = Path(run_dir, "ledger.sqlite").resolve().as_uri() + "?mode=ro"
    db = sqlite3.connect(uri, uri=True)
    try:
        rows = db.execute("SELECT block_hash, body FROM blocks WHERE kind=? ORDER BY lamport_clock", (kind,)).fetchall()
    finally:
        db.close()
    return [{**canonical.loads(body), "block_hash": h} for h, body in rows]


def task_rows(run_dir) -> list[dict]:
    """One row per agent_run block (one agent on one task), in ledger order."""
    blobs = BlobStore(Path(run_dir) / "blobs", create=False)
    rows = []
    for block in _blocks(run_dir, "agent_run"):
        steps = block["state_transitions"]
        single = {t["action"]: t["result_hash"] for t in steps if t["action"] in ("end", "eval:public")}
        if len(single) != 2 or not steps:
            raise StatsError(f"agent_run block {block['block_hash'][:12]}… has no end/eval:public step "
                             "(run `run.py verify` on this run)")
        end, public = blobs.get(single["end"]), blobs.get(single["eval:public"])
        llm = [t for t in steps if t["action"].startswith("llm:")]
        rows.append({"agent_id": steps[0]["agent_id"], "task_id": end["task_id"], "outcome": end["outcome"],
                     "steps": end["steps"], "llm_steps": len(llm),
                     "parse_errors": sum(t["outcome"] == "error" for t in llm),
                     "tokens": end["tokens"], "latency_ms": end["latency_ms"],
                     "passed": public["passed"], "total": public["total"], "l0_failures": public["l0_failures"]})
    return rows


def run_summary(run_dir) -> dict:
    run_dir = Path(run_dir)
    rows = task_rows(run_dir)
    blobs = BlobStore(run_dir / "blobs", create=False)
    proposals = [blobs.get(t["result_hash"]) for b in _blocks(run_dir, "generation_event")
                 for t in b["state_transitions"] if t["action"] == "mutation_proposal"]
    try:   # a missing or unreadable summary.json only drops the per-generation token line
        done = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        spent = [g["tokens_spent"] for g in done["generations"]]
    except (OSError, ValueError, KeyError, TypeError):
        spent = []
    return {
        "task_runs": len(rows),
        "tasks_passed": sum(r["total"] > 0 and r["passed"] == r["total"] for r in rows),
        "public_passed": sum(r["passed"] for r in rows),
        "public_total": sum(r["total"] for r in rows),
        "l0_failed_runs": sum(bool(r["l0_failures"]) for r in rows),
        "llm_steps": sum(r["llm_steps"] for r in rows),
        "parse_errors": sum(r["parse_errors"] for r in rows),
        "outcomes": dict(collections.Counter(r["outcome"] for r in rows)),
        "tokens_task_runs": sum(r["tokens"] for r in rows),
        "proposals": len(proposals),
        "accepted": sum(bool(p["accepted"]) for p in proposals),
        "mutation_calls": sum(len(p["model_calls"]) for p in proposals),
        "tokens_per_generation": [b - a for a, b in zip([0] + spent, spent)],
    }


def run_tiers(run_dir, tasks) -> dict:
    """task_id → tier for the tasks whose task.json still matches the run's genesis public manifest; else '?'.

    Tiers live in task.json, so a retuned or edited task can't be shown with a tier the run never used.
    """
    blobs = BlobStore(Path(run_dir) / "blobs", create=False)
    genesis = _blocks(run_dir, "genesis")
    ref = next((t["result_hash"] for b in genesis for t in b["state_transitions"] if t["action"] == "public_manifest"),
               None)
    recorded = blobs.get(ref)["tasks"] if ref else {}
    tiers = {}
    for task in tasks:
        then = recorded.get(task.id, {}).get("files", {}).get("task.json")
        now = canonical.sha256_hex((task.root / "task.json").read_bytes())
        tiers[task.id] = task.difficulty if then == now else "?"
    return tiers

def _pct(part: int, whole: int) -> str:
    return f"{part / whole:.0%}" if whole else "–"


def format_rows(rows: list[dict], difficulty: dict | None = None) -> str:
    """One line per task run. `difficulty` (task_id → tier, from the public task.json files) adds a tier column."""
    tier = (lambda r: f"{difficulty.get(r['task_id'], '?'):<9}") if difficulty else (lambda r: "")
    agent_w = max([len("agent")] + [len(r["agent_id"]) for r in rows]) + 1
    task_w = max([len("task")] + [len(r["task_id"]) for r in rows]) + 1
    out_w = max([len("outcome")] + [len(r["outcome"]) for r in rows]) + 1
    head = (f"{'agent':<{agent_w}}{'task':<{task_w}}{'tier     ' if difficulty else ''}{'outcome':<{out_w}}"
            f"{'steps':>6}{'llm':>5}{'parse err':>10}{'tokens':>9}{'public':>9}  L0")
    lines = [head, "-" * len(head)]
    for r in rows:
        lines.append(f"{r['agent_id']:<{agent_w}}{r['task_id']:<{task_w}}{tier(r)}{r['outcome']:<{out_w}}{r['steps']:>6}"
                     f"{r['llm_steps']:>5}{r['parse_errors']:>10}{r['tokens']:>9,}"
                     f"{str(r['passed']) + '/' + str(r['total']):>9}  {', '.join(r['l0_failures']) or 'ok'}")
    return "\n".join(lines) + "\n"


def format_summary(s: dict) -> str:
    runs = s["task_runs"]
    outcomes = ", ".join(f"{k} {v}" for k, v in sorted(s["outcomes"].items(), key=lambda kv: (-kv[1], kv[0])))
    per_child = f"{s['mutation_calls'] / s['accepted']:.1f}" if s["accepted"] else "–"
    lines = [
        f"task runs: {runs} · fully passed: {s['tasks_passed']} ({_pct(s['tasks_passed'], runs)})"
        f" · public tests: {s['public_passed']}/{s['public_total']} ({_pct(s['public_passed'], s['public_total'])})",
        f"L0 failures: {s['l0_failed_runs']} runs",
        f"llm steps: {s['llm_steps']} · parse errors: {s['parse_errors']} ({_pct(s['parse_errors'], s['llm_steps'])})",
        f"end outcomes: {outcomes or '–'}",
        f"tokens: {s['tokens_task_runs']:,} in task runs"
        f" ({s['tokens_task_runs'] // runs if runs else 0:,} per run)"
        f" · per generation (incl. mutation): {', '.join(f'{t:,}' for t in s['tokens_per_generation']) or '–'}",
        f"mutation: {s['proposals']} proposals, {s['accepted']} accepted, {s['mutation_calls']} model calls"
        f" ({per_child} per accepted child)",
    ]
    return "\n".join(lines) + "\n"
