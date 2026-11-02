"""Run report (design §17 Phase 1; CODE_STRUCTURE §3 report.py): survivors, held-out rates with 95% intervals,
published heads. Hidden numbers come from evaluation.holdout_report; this module only formats them."""
import json
from pathlib import Path

from . import evaluation
from .fake_model import SKILL_AXIOMS


def _pct(ppm) -> str:
    return "–" if ppm is None else f"{ppm / 10_000:.1f}%"


def _skills(axioms: list[str], has_verify: bool) -> str:
    tags = [name for name, text in (("boundary", SKILL_AXIOMS["off_by_one"]), ("types", SKILL_AXIOMS["type_error"]))
            if text in axioms]
    if has_verify:
        tags.append("verify-loop")
    return ", ".join(tags) or "—"


def build(run_dir: Path, verify_problems: list[str]) -> str:
    run_dir = Path(run_dir)
    s = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    baseline_axioms = s["seed_agent"]["axioms"]   # this run's own seed, not the current config's
    h = evaluation.holdout_report(run_dir)
    out = [f"# Apex run report — `{run_dir.name}`", "",
           f"- Seed: {s['seed']} · stop reason: {s['stop_reason']}",
           f"- Tokens spent: {s['tokens_spent']:,} of {s['budget']['tokens_total']:,} "
           f"(holdout reserve {s['budget']['holdout_reserve']:,})",
           f"- Ledger verification: {'**OK**' if not verify_problems else '**FAIL** (' + str(len(verify_problems)) + ' problems)'}",
           "- Scores are public-test L1 (design §9). Hidden numbers are evaluator-only and never fed to selection.", "",
           "## Generations", "",
           "| Gen | Batch | Best L1 | Mean L1 (L0 pass) | Best agent's skills | Survivors | L4 divergence |",
           "|---|---|---|---|---|---|---|"]
    for g in s["generations"]:
        res = g["results"]
        passing = [r for r in res.values() if r["l0"]]
        best = max(passing, key=lambda r: r["l1_ppm"]) if passing else None
        out.append("| {} | {} | {} | {} | {} | {}{} | {} |".format(
            g["generation"], ", ".join(g["batch"]),
            _pct(best["l1_ppm"]) if best else "–",
            _pct(sum(r["l1_ppm"] for r in passing) // len(passing)) if passing else "–",
            _skills(best["axioms"], best["has_verify"]) if best else "–",
            ", ".join(g["survivors"]), " (rollback)" if g["rollback"] else "",
            _pct(h["divergence_ppm"].get(g["generation"]))))
    out += ["", "L4 divergence = mean over the population of (public − hidden) pass rate on the batch (§9 L4).", "",
            "## Final survivors", ""]
    for a in s["final_survivors"]:
        added = [x for x in a["prompt_axioms"] if x not in baseline_axioms]
        nodes = " → ".join(n["id"] for n in a["graph_config"]["nodes"])
        out += [f"### {a['agent_id']} (lineage {a['lineage_id']}, generation {a['generation']})",
                f"- Graph nodes: {nodes} · max_steps {a['graph_config']['max_steps']}",
                "- Axioms added since the baseline:" + ("" if added else " none")]
        out += [f"  - {x}" for x in added]
        out.append("")
    out += ["## Held-out tasks (final survivors, run once)", "",
            "| Agent | Successes | Rate | 95% interval (Clopper–Pearson) |", "|---|---|---|---|"]
    by_agent: dict[str, list[bool]] = {}
    for row in h["heldout"]:
        by_agent.setdefault(row["agent_id"], []).append(row["success"])
    for agent_id, rows in list(by_agent.items()) + ([("pooled*", [x for r in by_agent.values() for x in r])]
                                                    if len(by_agent) > 1 else []):
        k, n = sum(rows), len(rows)
        lo, hi = evaluation.clopper_pearson(k, n)
        out.append(f"| {agent_id} | {k}/{n} | {k / n:.0%} | [{lo:.3f}, {hi:.3f}] |")
    if not by_agent:
        out.append("| – | no held-out runs | – | – |")
    else:
        out += ["", "With only a few held-out tasks per agent the intervals are wide; read them as a sanity check, not "
                "an estimate. *The pooled row treats every (agent, task) run as independent, but the agents share the "
                "same tasks, so its interval is optimistic."]
    out += ["", "## Published heads (design §8)", "",
            f"Each generation's branch heads are appended to `{run_dir.name}/heads.jsonl`; `run.py verify` compares the "
            "ledger against every entry. Keep a copy elsewhere (`--heads`) to detect a rewrite of the whole run directory.", ""]
    for g in s["generations"]:
        out.append(f"- generation {g['generation']}: {len(g['heads'])} heads, root `{g['heads'].get('root', '')[:16]}…`")
    if verify_problems:
        out += ["", "## Verification problems", ""] + [f"- {p}" for p in verify_problems]
    return "\n".join(out) + "\n"


def write(run_dir: Path, verify_problems: list[str]) -> Path:
    path = Path(run_dir) / "report.md"
    path.write_text(build(run_dir, verify_problems), encoding="utf-8")
    return path
