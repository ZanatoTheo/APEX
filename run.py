"""Apex command line. Only argument handling lives here; the loop is apex/operation.py.

  run.py run --connector <module> [--data <file>] [--holdout <file>] [--seeds <dir>] [--config <file>]
             [--max-loops N] [--max-cycles N] [--orch_wonder | --orch_spark] [--fake] [--out runs]
  run.py estimate [--connector <module> [--data <file>]] [--config <file>] [--orch_wonder | --orch_spark]
  run.py models [--config <file>] [--orch_wonder | --orch_spark]
  run.py stop [--run-dir <dir>] [--out runs]

Op. Orch's model: --orch_wonder = muse-wonder-1.0, --orch_spark = muse-spark-1.3-contributor; with neither, the
config's (Spark Contributor by default).
"""
import argparse
import secrets
import sys
from datetime import datetime
from pathlib import Path

from apex import config, envfile, llm
from apex.connector import ConnectorError, cycle_steps, load_connector
from apex.estimate import cycle_cost

ROOT = Path(__file__).resolve().parent
ORCH_MODELS = {"wonder": "muse-wonder-1.0", "spark": "muse-spark-1.3-contributor"}


def add_orch_flags(parser) -> None:
    """--orch_wonder / --orch_spark: Op. Orch's model for this run (neither: the config's)."""
    group = parser.add_mutually_exclusive_group()
    for name, model_id in ORCH_MODELS.items():
        group.add_argument(f"--orch_{name}", dest="orch", action="store_const", const=name,
                           help=f"Op. Orch on {model_id}")


def fail(message: str, code: int = 2):
    print(f"error: {message}", file=sys.stderr)
    sys.exit(code)


def load_config(args) -> dict:
    op = {name: getattr(args, name, None) for name in ("max_loops", "max_cycles")}
    op = {name: value for name, value in op.items() if value is not None}   # 0 is checked, not ignored
    overrides = {"operation": op} if op else {}
    orch = getattr(args, "orch", None)
    if orch is not None:
        overrides["models"] = {"roles": {"orchestrator": {"model_id": ORCH_MODELS[orch]}}}
    overrides = overrides or None
    try:
        return config.load(args.config, overrides)
    except config.ConfigError as e:
        fail(str(e))


def connector_for(args, cfg, required: bool):
    module = args.connector or cfg["task"]["connector"]
    if not module:
        if required:
            fail("no connector: pass --connector <module> or set task.connector in the config")
        return None
    try:
        return load_connector(module, cfg, args.data)
    except ConnectorError as e:
        fail(str(e))


def cmd_run(args) -> int:
    cfg = load_config(args)
    connector = connector_for(args, cfg, required=True)
    holdout = None
    if args.holdout is not None:                     # checked before training: a bad file costs nothing
        if args.data is not None and Path(args.holdout).resolve() == Path(args.data).resolve():
            fail("--holdout is the same file as --data: the check needs data the agents never trained on")
        try:
            holdout = load_connector(args.connector or cfg["task"]["connector"], cfg, args.holdout)
            if holdout.n_steps() < 1:
                raise ConnectorError("the held-out data has no steps")
            cycle_steps(holdout, cfg)
        except ConnectorError as e:
            fail(f"--holdout: {e}")
    if args.fake:
        from apex.fake_run import demo_model
        model = demo_model(cfg)
    else:
        envfile.load(ROOT / ".env")
        try:
            model = llm.LiveModel(cfg, llm.make_client(cfg))
        except llm.LLMError as e:
            fail(str(e))
    run_dir = Path(args.out) / f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
    print(f"run dir: {run_dir}", flush=True)       # flushed: a run under nohup shows progress at once

    from apex.operation import Operation
    operation = Operation(cfg, connector, model, run_dir, progress=lambda line: print(line, flush=True),
                          holdout=holdout)
    try:
        result = operation.run(args.seeds)
    except Exception as e:
        print(f"stopped: error: {type(e).__name__}: {e} · {run_dir}", file=sys.stderr, flush=True)
        return 1
    print(f"stopped: {result['reason']} · selected {result['selected']} · {run_dir}", flush=True)
    h = result.get("holdout")
    if h is not None:
        if "skipped" in h:
            print(f"holdout: skipped ({h['skipped']})")
        else:
            verdict = ("passed" if h["passed"] else "not passed") if h["passed"] is not None else \
                "no verdict: " + ("stopped early" if h["stopped"] != "done" else
                                  f"{h['step_errors']} step errors" if h["step_errors"] else "no target")
            print(f"holdout: {h['agent']} {h['stopped']} after {h['steps_done']}/{h['n_steps']} steps · "
                  f"loop score {h['loop_score']} vs target {h['target']} ({verdict})")
    return 0


def cmd_estimate(args) -> int:
    cfg = load_config(args)
    connector = connector_for(args, cfg, required=False)
    try:
        steps = cycle_steps(connector, cfg) if connector else cfg["operation"]["steps_per_cycle"]
    except ConnectorError as e:
        fail(str(e))
    cost = cycle_cost(cfg, steps)
    print(f"worst case for one cycle (steps per cycle: {steps}, agents: {cfg['operation']['agents']})")
    for role, usd in cost["roles"].items():
        print(f"  {role:<13} ${usd:8.4f}")
    print(f"  {'total':<13} ${cost['total']:8.4f}   cap budget.cycle_usd = ${cost['cap']:.2f}"
          + ("" if cost["total"] <= cost["cap"] else "   (over the cap: the budget will stop calls)"))
    return 0


def models_report(cfg: dict, client) -> list[tuple[str, str, str]]:
    """(role, model id, found|missing) for every role, against the models this key can use."""
    available = set(llm.list_models(client))
    return [(role, r["model_id"], "found" if r["model_id"] in available else "missing")
            for role, r in cfg["models"]["roles"].items()]


def cmd_stop(args) -> int:
    """Ask a running operation to stop: it ends before its next agent step, with a fallback pick and final.json."""
    if args.run_dir:
        target = Path(args.run_dir)
    else:
        root = Path(args.out)
        open_runs = sorted(p for p in root.iterdir() if p.is_dir() and (p / "log.jsonl").exists()
                           and not (p / "final.json").exists()) if root.is_dir() else []
        if not open_runs:
            print(f"no unfinished run under {root}", file=sys.stderr)
            return 1
        target = open_runs[-1]
    if not target.is_dir():
        print(f"no run folder {target}", file=sys.stderr)
        return 1
    (target / "STOP").write_text("stop requested\n")
    print(f"stop requested: {target} (it ends before its next agent step; final.json follows)")
    return 0


def cmd_models(args) -> int:
    cfg = load_config(args)
    envfile.load(ROOT / ".env")
    try:
        rows = models_report(cfg, llm.make_client(cfg))
    except llm.LLMError as e:
        fail(str(e))
    for role, model_id, state in rows:
        print(f"  {role:<13} {model_id:<30} {state}")
    return 0 if all(state == "found" for _, _, state in rows) else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="run.py", description="Apex: run, estimate, list models.")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run the operation")
    run.add_argument("--connector", default="", help="connector module (else config task.connector)")
    run.add_argument("--data", default=None, help="data file handed to the connector")
    run.add_argument("--holdout", default=None,
                     help="held-out data file: after the run, the picked agent walks it once (no evolution)")
    run.add_argument("--seeds", default=None, help="folder of seed agents (optional)")
    run.add_argument("--config", default=None, help="config JSON merged over the defaults")
    run.add_argument("--max-loops", type=int, default=None)
    run.add_argument("--max-cycles", type=int, default=None, help="stop after N cycles in all")
    add_orch_flags(run)
    run.add_argument("--fake", action="store_true", help="scripted fake model: no API calls")
    run.add_argument("--out", default=str(ROOT / "runs"), help="folder for run dirs")
    run.set_defaults(func=cmd_run)

    est = sub.add_parser("estimate", help="worst-case cost of one cycle")
    est.add_argument("--connector", default="")
    est.add_argument("--data", default=None)
    est.add_argument("--config", default=None)
    add_orch_flags(est)
    est.set_defaults(func=cmd_estimate)

    models = sub.add_parser("models", help="check the configured model ids against the API")
    models.add_argument("--config", default=None)
    add_orch_flags(models)
    models.set_defaults(func=cmd_models)

    stop = sub.add_parser("stop", help="ask a running operation to stop cleanly")
    stop.add_argument("--run-dir", default=None, help="the run folder (default: newest unfinished under --out)")
    stop.add_argument("--out", default=str(ROOT / "runs"), help="folder of run dirs")
    stop.set_defaults(func=cmd_stop)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
