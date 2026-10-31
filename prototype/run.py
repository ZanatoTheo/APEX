#!/usr/bin/env python3
"""Apex prototype CLI (MVP Operator Console): run | verify | report | corpus-check."""
import argparse
import datetime
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from apex import config, corpus, evaluation, evolution, ledger, report, sandbox  # noqa: E402
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
    run_dir = (args.runs_dir or config.resolve_path(cfg, "runs")) / run_id
    if run_dir.exists():
        print(f"run directory {run_dir} already exists", file=sys.stderr)
        return 2
    print(f"run {run_id}: P={cfg['population']['P']} mu={cfg['population']['mu']} K={cfg['batch']['K']} "
          f"G_max={cfg['run']['g_max']} model={cfg['models']['provider']}")
    try:
        summary = evolution.run(cfg, run_dir)
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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
