#!/usr/bin/env python3
"""Live checks against Meta's endpoint: the steps that need a real MODEL_API_KEY (1_11_plan.md "Deferred live checks").

Usage (from anywhere):  python3 tools/live_checks.py <step> [--config configs/meta.json] [--run-id v1-meta-1]
Steps, in order:
  models    list the model IDs; copy the exact ones into the config (models.subagent / models.mutation .model_id)
  contract  4 live calls: reply shape, pinned IDs, a valid action, a valid mutation proposal
  probe     the baseline agent once on every public task (phase 6), with the per-task table
  estimate  worst-case tokens for a full run with the config (no API call, no key needed)
  run       the full evolution run (phase 7), then verify
  stats     failure modes of a finished run (phase 8; no key needed)
product/.env is read with apex/envfile.py, the same parser run.py uses; variables already exported win.
"""
import argparse
import datetime
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # product/
sys.path.insert(0, str(ROOT))

from apex import envfile  # noqa: E402

STEPS = ("models", "contract", "probe", "estimate", "run", "stats")
NEEDS_KEY = {"models", "contract", "probe", "run"}
PLACEHOLDERS = {"", "banana"}


def key_problem(env) -> str | None:
    if env.get("MODEL_API_KEY", "").strip() in PLACEHOLDERS:
        return "MODEL_API_KEY is empty or still the 'banana' placeholder: put the real key in product/.env"
    return None


def plan(step: str, config: str, run_id: str) -> list[tuple[list[str], dict]]:
    """The commands for one step, each with the extra environment it needs (run from product/)."""
    py = sys.executable
    if step == "models":
        return [([py, "run.py", "models", "--config", config], {})]
    if step == "contract":   # APEX_LLM_CONFIG is set only here, so a plain test run never goes live
        return [([py, "-m", "unittest", "tests.test_llm_contract", "-v"], {"APEX_LLM_CONFIG": config})]
    if step == "probe":
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        return [([py, "run.py", "probe", "--config", config, "--run-id", f"probe-{stamp}"], {})]
    if step == "estimate":
        return [([py, "run.py", "estimate", "--config", config], {})]
    if step == "run":
        return [([py, "run.py", "run", "--config", config, "--run-id", run_id], {}),
                ([py, "run.py", "verify", f"runs/{run_id}"], {})]
    if step == "stats":
        return [([py, "run.py", "stats", f"runs/{run_id}", "--tasks"], {})]
    raise ValueError(f"unknown step {step!r}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="live_checks.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=STEPS)
    parser.add_argument("--config", default="configs/meta.json")
    parser.add_argument("--run-id", default="v1-meta-1")
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:   # usage errors return 2 instead of exiting (tests call main)
        return e.code if isinstance(e.code, int) else 2
    if args.step in NEEDS_KEY:
        problem = key_problem(os.environ)
        if problem:
            print(problem, file=sys.stderr)
            return 2
    for cmd, extra in plan(args.step, args.config, args.run_id):
        code = subprocess.run(cmd, cwd=ROOT, env={**os.environ, **extra}).returncode
        if code:
            return code
    return 0


if __name__ == "__main__":
    envfile.load(ROOT / ".env")   # only as a command: tests call main() and never read .env
    sys.exit(main())
