"""Build the chunk files, then start the operation on them.

  python environment/start.py [--csv environment/data/prices.csv] [--time-gap 1] [--holdout-year <year>|none]
                              [--fake] [--max-loops N] [--max-cycles N] [--skip-holdout] [--config <file>] [--out runs]
                              [--orch_wonder | --orch_spark]

The training file goes to `run.py run --connector apex.env_connector --data <file>`, and the held-out file to
`--holdout <file>` (unless --skip-holdout: the file is still built, so training history starts after the held-out
year, but the walk doesn't run). Without --fake this makes real model calls, exactly like run.py.
"""
import argparse
import copy
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import run                                                  # noqa: E402
from apex.connector import cycle_steps, load_connector      # noqa: E402
from apex.estimate import cycle_cost                        # noqa: E402
from apex.operation import split_cycles                     # noqa: E402
from environment import build_chunks                        # noqa: E402


def _cycle_costs(cfg: dict, path, loops: int) -> list[float]:
    """Each cycle's worst case, in run order (loops × cycles), at the lower of its estimate and the cycle cap."""
    conn = load_connector("apex.env_connector", cfg, str(path))
    one_loop = [min(cycle_cost(cfg, len(steps))["total"], cfg["budget"]["cycle_usd"])
                for steps in split_cycles(conn.n_steps(), cycle_steps(conn, cfg))]
    return one_loop * loops


def worst_case(cfg: dict, paths: dict) -> str:
    """The most the run can spend: the training cycles that can run (every loop, cut at operation.max_cycles),
    plus the held-out walk (one agent) when it runs."""
    costs = _cycle_costs(cfg, paths["train"], cfg["operation"]["max_loops"])
    limit = cfg["operation"].get("max_cycles")
    if limit is not None:
        costs = costs[:limit]
    if paths.get("holdout") is not None:
        one = copy.deepcopy(cfg)
        one["operation"]["agents"] = 1
        costs += _cycle_costs(one, paths["holdout"], 1)
    cap = cfg["budget"]["cycle_usd"]
    return f"worst case: {len(costs)} cycles, at most ${sum(costs):.2f} (each cycle capped at ${cap:.2f})"


def years(settings: dict, holdout_flag=None) -> tuple:
    """(year, holdout_year) from the config's task.settings; the --holdout-year flag beats the setting.
    ValueError when a value is the wrong type or the held-out year is not earlier."""
    year = settings.get("year", build_chunks.YEAR)
    if type(year) is not int:
        raise ValueError(f"task.settings.year must be an int, got {year!r}")
    if holdout_flag is not None:
        source = "--holdout-year"
        try:
            held = build_chunks.parse_holdout_year(holdout_flag)
        except ValueError:
            raise ValueError(f"--holdout-year must be a year or none, got {holdout_flag!r}") from None
    else:
        source = "task.settings.holdout_year"
        held = settings.get("holdout_year", build_chunks.HOLDOUT_YEAR)
        if held is not None and type(held) is not int:
            raise ValueError(f"task.settings.holdout_year must be an int or null, got {held!r}")
    if held is not None and held >= year:
        raise ValueError(f"the held-out year {held} is not before the year {year}: set {source} "
                         f"to {'none' if source.startswith('--') else 'null'} or an earlier year")
    return year, held


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Build the market chunks and run Apex 2 on them.")
    p.add_argument("--csv", default=str(build_chunks.DATA / "prices.csv"))
    p.add_argument("--assets", default=str(build_chunks.ASSETS))
    p.add_argument("--time-gap", type=int, default=build_chunks.TIME_GAP)
    p.add_argument("--holdout-year", default=None,
                   help="a year, or none (default: task.settings.holdout_year, else 2022)")
    p.add_argument("--seed", type=int, default=None, help="fixed asset mapping (tests); default: random")
    p.add_argument("--build-out", default=str(build_chunks.DATA), help="folder for the chunk files and mapping")
    p.add_argument("--fake", action="store_true", help="scripted fake model: no API calls")
    p.add_argument("--max-loops", type=int, default=1, help="loops over the training year (default 1)")
    p.add_argument("--max-cycles", type=int, default=None, help="stop after N cycles in all")
    p.add_argument("--skip-holdout", action="store_true",
                   help="build the held-out file (training history stays after its year) but don't walk it")
    p.add_argument("--new-mapping", action="store_true", help="draw a new asset mapping even if one fits")
    p.add_argument("--config", default=None)
    run.add_orch_flags(p)                       # Op. Orch's model; neither flag: the config's (Spark Contributor)
    p.add_argument("--out", default=None, help="folder for run dirs (run.py's default if not given)")
    args = p.parse_args(argv)
    cfg = run.load_config(SimpleNamespace(config=args.config, max_loops=args.max_loops,
                                          max_cycles=args.max_cycles, orch=args.orch))  # a bad one exits 2 here
    try:
        year, holdout_year = years(cfg["task"]["settings"], args.holdout_year)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    try:
        paths = build_chunks.build(args.csv, args.assets, args.time_gap, year, holdout_year, args.build_out, args.seed,
                                   new_mapping=args.new_mapping)
    except Exception as e:
        print(f"error: could not build the chunks: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    if args.skip_holdout:
        paths = {**paths, "holdout": None}
    try:
        print(worst_case(cfg, paths), flush=True)
    except Exception as e:
        print(f"worst case: unknown ({type(e).__name__}: {e})"[:300])
    cmd = ["run", "--connector", "apex.env_connector", "--data", str(paths["train"])]
    if paths["holdout"] is not None:
        cmd += ["--holdout", str(paths["holdout"])]
    if args.fake:
        cmd.append("--fake")
    if args.orch is not None:
        cmd.append(f"--orch_{args.orch}")
    for flag, value in (("--max-loops", args.max_loops), ("--max-cycles", args.max_cycles), ("--config", args.config),
                        ("--out", args.out)):
        if value is not None:
            cmd += [flag, str(value)]
    return run.main(cmd)


if __name__ == "__main__":
    sys.exit(main())
