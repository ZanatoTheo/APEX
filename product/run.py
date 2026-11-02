#!/usr/bin/env python3
"""Apex v1.0 CLI (MVP Operator Console): run | probe | verify | report | stats | estimate | corpus-check | models."""
import argparse
import datetime
import json
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from apex import config, corpus, costs, envfile, evaluation, evolution, ledger, report, sandbox, stats  # noqa: E402
from apex.models import LLMServiceMissing  # noqa: E402

WORK_ROOT = ROOT / ".tmp" / "work"
GENESIS_ACTIONS = {"config", "gate_definition", "public_manifest", "holdout_manifest", "rng_seed", "seed_agent"}


def cmd_run(args) -> int:
    overrides = {"models": {"provider": args.model}} if args.model else {}   # else the config's provider
    if args.seed is not None:
        overrides["run"] = {"seed": args.seed}
    if args.g_max is not None:
        overrides.setdefault("run", {})["g_max"] = args.g_max
    try:
        cfg = config.load(args.config, overrides)
    except config.ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    run_id = args.run_id or f"{datetime.datetime.now():%Y%m%d-%H%M%S}-s{cfg['run']['seed']}"
    return _execute(cfg, run_id, args.runs_dir)


def _execute(cfg: dict, run_id: str, runs_dir: Path | None, heldout: bool = True) -> int:
    """Run the loop into runs/<run_id>, verify the ledger and write report.md. Shared by `run` and `probe`."""
    run_dir = (runs_dir or config.resolve_path(cfg, "runs")) / run_id
    if run_dir.exists():
        print(f"run directory {run_dir} already exists", file=sys.stderr)
        return 2
    print(f"run {run_id}: P={cfg['population']['P']} mu={cfg['population']['mu']} K={cfg['batch']['K']} "
          f"G_max={cfg['run']['g_max']} model={cfg['models']['provider']}")
    try:
        summary = evolution.run(cfg, run_dir, heldout=heldout)
    except Exception as e:   # startup failures (missing llm_service, missing API key, …) and unexpected errors
        print(f"{'cannot start' if isinstance(e, LLMServiceMissing) else 'run failed'}: "
              f"{e if isinstance(e, LLMServiceMissing) else f'{type(e).__name__}: {e}'}", file=sys.stderr)
        if run_dir.exists() and not any(run_dir.glob("blobs/*/*")):   # nothing recorded yet: free the run id
            shutil.rmtree(run_dir, ignore_errors=True)
        else:
            print(f"partial run kept in {run_dir}", file=sys.stderr)
        return 2
    problems = ledger.verify(run_dir, required_genesis_actions=GENESIS_ACTIONS)
    path = report.write(run_dir, problems)
    print(f"stop reason: {summary['stop_reason']}; tokens spent: {summary['tokens_spent']:,}")
    print(f"verify: {'OK' if not problems else 'FAIL'}")
    print(f"report: {path}")
    return 0 if not problems else 1


def cmd_probe(args) -> int:
    """One agent (default: the baseline) once on every public task: P=1, μ=1, one generation, K = all tasks."""
    agent = args.agent
    if not agent.is_file():
        print(f"agent file {agent} not found", file=sys.stderr)
        return 2
    overrides = {"population": {"P": 1, "mu": 1}, "run": {"g_max": 1},
                 "paths": {"seed_agent": str(agent.resolve())}}
    if args.model:
        overrides["models"] = {"provider": args.model}
    try:
        cfg = config.load(args.config, overrides)
        public = corpus.load_public(config.resolve_path(cfg, "corpus"))
        cfg = config.load(args.config, {**overrides, "batch": {"K": len(public)}})
    except (config.ConfigError, corpus.CorpusError) as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    run_id = args.run_id or f"probe-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    code = _execute(cfg, run_id, args.runs_dir, heldout=False)   # design §9.1: no held-out feedback from probes
    run_dir = (args.runs_dir or config.resolve_path(cfg, "runs")) / run_id
    if code == 2 or not (run_dir / "summary.json").is_file():
        return code
    if code == 1:
        print("probe: the ledger failed verification, so no statistics are printed (see report.md)", file=sys.stderr)
        return 1
    try:
        rows, summary = stats.task_rows(run_dir), stats.run_summary(run_dir)
    except stats.StatsError as e:
        print(f"probe: {e}", file=sys.stderr)
        return 1
    if not rows:   # e.g. an infra error (429 after retries) aborted the generation: nothing was recorded
        stop = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))["stop_reason"]
        print(f"probe failed: no task run was recorded ({stop})", file=sys.stderr)
        return 1
    print()
    print(stats.format_rows(rows, {t.id: t.difficulty for t in public}), end="")
    print()
    print(stats.format_summary(summary), end="")
    print("held-out: not run by probe (design §9.1: held-out tasks are for a full run's final survivors only)")
    return code


def cmd_verify(args) -> int:
    problems = ledger.verify(args.run_dir, heads_file=args.heads, required_genesis_actions=GENESIS_ACTIONS)
    if problems:
        print("FAIL")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("OK")
    return 0


def cmd_report(args) -> int:
    if not (args.run_dir / "summary.json").is_file():
        print(f"{args.run_dir} has no summary.json (not a finished run)", file=sys.stderr)
        return 2
    problems = ledger.verify(args.run_dir, required_genesis_actions=GENESIS_ACTIONS)
    print(f"report: {report.write(args.run_dir, problems)}")
    return 0


def cmd_corpus_check(args) -> int:
    """Each task: buggy code fails its public tests; the oracle fix passes public and hidden tests."""
    limits = sandbox.Limits(timeout_s=30)
    rows, ok = [], True
    jobs = [(t, evaluation.hidden_tests_dir(args.holdout, t.id), "public") for t in corpus.load_public(args.corpus)]
    jobs += [(t, evaluation.heldout_hidden_tests_dir(t), "held-out") for t in evaluation.heldout_tasks(args.holdout)]
    for task, hidden_dir, kind in jobs:
        fix = (args.oracle / f"{task.id}.diff").read_text(encoding="utf-8")
        with sandbox.Workspace.for_task(task, WORK_ROOT, limits) as ws:
            before = ws.run_tests().data
            applied = ws.write_patch(fix)
            after = ws.run_tests().data
        with sandbox.Workspace.for_task(task, WORK_ROOT, limits, tests_dir=hidden_dir) as ws:
            ws.write_patch(fix)
            hidden = ws.run_tests().data
        good = (before["passed"] < before["total"] and applied.status == "applied"
                and after["passed"] == after["total"] > 0 and hidden["passed"] == hidden["total"] > 0)
        ok &= good
        rows.append(f"{'OK  ' if good else 'FAIL'} {kind:8} {task.id:22} buggy {before['passed']}/{before['total']}"
                    f"  fixed {after['passed']}/{after['total']}  hidden {hidden['passed']}/{hidden['total']}"
                    + ("" if applied.status == "applied" else f"  ({applied.output})"))
    print("\n".join(rows))
    print(f"network isolation: {'unshare -rn' if sandbox.network_isolated() else 'unavailable (JC-33)'}; "
          f"resource caps: {'prlimit' if sandbox.limits_enforced() else 'unavailable (prlimit missing)'}")
    print("corpus-check:", "OK" if ok else "FAIL")
    return 0 if ok else 1


def cmd_models(args) -> int:
    """List the model IDs the endpoint offers this key, and whether the pinned IDs are among them."""
    try:
        cfg = config.load(args.config)
        from apex.llm_service import LLMService
        ids = LLMService(cfg).list_models()
    except config.ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    except Exception as e:   # no key, HTTP error, unreachable endpoint
        print(f"models failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    print(f"{len(ids)} models at {cfg['models']['base_url']}:")
    for model_id in ids:
        print(f"  {model_id}")
    for role in ("subagent", "mutation"):
        pin = cfg["models"][role]["model_id"]
        print(f"pinned {role}: {pin} ({'listed' if pin in ids else 'NOT listed'})")
    return 0


def cmd_estimate(args) -> int:
    """Worst-case token use of a run with this config. No key, no model call."""
    try:
        cfg = config.load(args.config)
        n_heldout = len(evaluation.heldout_tasks(config.resolve_path(cfg, "holdout")))   # a count only
    except (config.ConfigError, corpus.CorpusError) as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    print(f"config: {args.config or 'defaults'} · P={cfg['population']['P']} mu={cfg['population']['mu']}"
          f" K={cfg['batch']['K']} g_max={cfg['run']['g_max']} · {n_heldout} held-out tasks")
    print(costs.format_estimate(costs.estimate(cfg, n_heldout)), end="")
    return 0


def cmd_stats(args) -> int:
    """Statistics of a run from its public record (logic: ../LOGIC.md, phase 7). Held-out results are in report.md."""
    run_dir = args.run_dir
    if not (run_dir / "ledger.sqlite").is_file():
        print(f"{run_dir} is not a run directory (no ledger.sqlite)", file=sys.stderr)
        return 2
    out = []
    try:   # read and format everything first: damage → exit 1 with no partial output
        rows, summary = stats.task_rows(run_dir), stats.run_summary(run_dir)
        try:
            done = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
            head = f"stop: {done['stop_reason']} · tokens spent: {done['tokens_spent']:,}"
        except FileNotFoundError:
            head = "unfinished run (no summary.json)"
        except (OSError, ValueError, KeyError, TypeError) as e:
            head = f"summary.json unreadable ({type(e).__name__})"
        out.append(f"run: {run_dir} · {head}\n")
        if args.tasks:
            try:
                tiers = stats.run_tiers(run_dir, corpus.load_public(ROOT / "corpus"))
                note = "tier: from task.json when it matches the run's genesis manifest, else ?"
            except (corpus.CorpusError, TypeError, ValueError, KeyError) as e:
                tiers, note = None, f"tier: not shown, the current corpus can't be loaded ({type(e).__name__})"
            out += ["\n", stats.format_rows(rows, tiers), note + "\n"]
        out += ["\n", stats.format_summary(summary),
                "held-out results: see report.md (stats reads the public record only)\n"]
    except (stats.StatsError, sqlite3.DatabaseError, OSError, KeyError, TypeError, ValueError) as e:
        print(f"stats: {type(e).__name__}: {e} (run `run.py verify` on this run)", file=sys.stderr)
        return 1
    print("".join(out), end="")
    return 0

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="run.py", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", help="run the evolution loop, verify the ledger, write report.md")
    p.add_argument("--config", type=Path, help="JSON config overriding apex/config.py DEFAULTS")
    p.add_argument("--seed", type=int)
    p.add_argument("--g-max", type=int)
    p.add_argument("--model", choices=["fake", "llm"],
                   help="override models.provider: fake (the default config) or llm, which loads apex/llm_service.py")
    p.add_argument("--run-id")
    p.add_argument("--runs-dir", type=Path, help="parent directory for run directories (default: runs/)")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("probe", help="run one agent once on every public task and print a per-task table")
    p.add_argument("--config", type=Path, help="JSON config overriding apex/config.py DEFAULTS")
    p.add_argument("--agent", type=Path, default=ROOT / "seeds" / "baseline.json",
                   help="agent JSON (graph + axioms) to probe (default: the baseline)")
    p.add_argument("--model", choices=["fake", "llm"], help="override models.provider")
    p.add_argument("--run-id")
    p.add_argument("--runs-dir", type=Path, help="parent directory for run directories (default: runs/)")
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("verify", help="verify a run's ledger, blobs and published heads")
    p.add_argument("run_dir", type=Path)
    p.add_argument("--heads", type=Path, help="a copy of heads.jsonl kept outside the run directory")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("report", help="rebuild report.md for a run")
    p.add_argument("run_dir", type=Path)
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("corpus-check", help="check every task against its oracle fix")
    p.add_argument("--corpus", type=Path, default=ROOT / "corpus")
    p.add_argument("--holdout", type=Path, default=ROOT / "holdout")
    p.add_argument("--oracle", type=Path, default=ROOT / "oracle")
    p.set_defaults(func=cmd_corpus_check)

    p = sub.add_parser("models", help="list the model IDs the endpoint offers (needs MODEL_API_KEY)")
    p.add_argument("--config", type=Path, default=ROOT / "configs" / "meta.json")
    p.set_defaults(func=cmd_models)

    p = sub.add_parser("estimate", help="worst-case token use of a run with a config (no key, no model call)")
    p.add_argument("--config", type=Path, help="JSON config overriding apex/config.py DEFAULTS")
    p.set_defaults(func=cmd_estimate)

    p = sub.add_parser("stats", help="statistics of a run from its public record (per-task rows with --tasks)")
    p.add_argument("run_dir", type=Path)
    p.add_argument("--tasks", action="store_true", help="also print one row per agent and task")
    p.set_defaults(func=cmd_stats)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    envfile.load(ROOT / ".env")   # only as a command: tests call main() and stay offline
    sys.exit(main())
