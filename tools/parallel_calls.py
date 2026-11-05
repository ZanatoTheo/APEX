"""Can the API take run 5's calls at the same time? Sends real requests (well under a cent per model).

  python tools/parallel_calls.py [--config configs/run5.json] [--orch wonder|spark] [--n N] [--env-file .env]
                                 [--dry-run]

For every model the config's roles use (Op. Orch's from --orch, like start.py), through call_llm, the path a run uses
(same retries):
  1. alone:    one call, timed;
  2. together: N calls at once per model, every model at the same time (N = operation.parallel_agents), timed.
A call that needed a retry (a 429 or a 5xx) is counted. Parallel works when `together` takes about as long as the
slowest `alone`, not N times as long, and no call fails.
Exit 0 when every call succeeds, 1 when one fails, 2 when the config or the key is missing.
"""
import argparse
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import run                                          # noqa: E402
from apex import config, envfile, llm               # noqa: E402

PROMPT = [{"role": "user", "content": "Reply with the single word: ready"}]
MAX_OUT = 2000


def models_used(cfg: dict) -> dict:
    """{model_id: a role that uses it}, the orchestrator first."""
    out = {}
    for role in ("orchestrator", *[r for r in config.ROLES if r != "orchestrator"]):
        out.setdefault(cfg["models"]["roles"][role]["model_id"], role)
    return out


def one(client, cfg: dict, role: str) -> dict:
    """One timed call; counts the retries call_llm made (through its sleep hook)."""
    retries = []

    def counted_sleep(s):
        retries.append(s)
        time.sleep(s)

    t0 = time.monotonic()
    try:
        reply = llm.call_llm(client, cfg, role, PROMPT, max_output_tokens=MAX_OUT,
                             reasoning_effort=cfg["models"]["roles"][role]["reasoning_effort"], sleep=counted_sleep)
        ok, note = True, f"{reply['status']} {reply['text'].strip()[:20]!r}"
    except Exception as e:                          # LLMError after the retries, or anything else
        ok, note = False, f"{type(e).__name__}: {e}"[:160]
    return {"ok": ok, "s": time.monotonic() - t0, "retries": len(retries), "note": note}


def main(argv=None, client=None) -> int:
    p = argparse.ArgumentParser(description="Time calls alone and at the same time, for every model run 5 uses.")
    p.add_argument("--config", default=str(ROOT / "configs" / "run5.json"))
    p.add_argument("--orch", choices=sorted(run.ORCH_MODELS), default="wonder", help="Op. Orch's model (default wonder)")
    p.add_argument("--n", type=int, default=None, help="calls at once per model (default operation.parallel_agents)")
    p.add_argument("--env-file", default=str(ROOT / ".env"), help="file holding MODEL_API_KEY")
    p.add_argument("--dry-run", action="store_true", help="print the plan and send nothing")
    args = p.parse_args(argv)
    try:
        cfg = config.load(args.config, {"models": {"roles": {"orchestrator":
                                                             {"model_id": run.ORCH_MODELS[args.orch]}}}})
    except config.ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    n = args.n or cfg["operation"]["parallel_agents"]
    if n < 1:
        print("error: --n must be >= 1", file=sys.stderr)
        return 2
    models = models_used(cfg)
    print(f"models: {', '.join(f'{m} (as {r})' for m, r in models.items())}; {n} at once per model, "
          f"{n * len(models)} together", flush=True)
    if args.dry_run:
        print(f"dry run: nothing sent (would send {len(models)} alone + {n * len(models)} together)")
        return 0
    if client is None:
        envfile.load(args.env_file)
        try:
            client = llm.make_client(cfg)
        except llm.LLMError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2

    alone = {}
    for m, role in models.items():                  # 1. one call per model, one after another
        alone[m] = one(client, cfg, role)
        a = alone[m]
        print(f"alone     {m:<28} {'ok' if a['ok'] else 'FAIL'} {a['s']:6.1f} s  retries {a['retries']}  {a['note']}",
              flush=True)

    jobs = [(m, role) for m, role in models.items() for _ in range(n)]
    start = threading.Barrier(len(jobs))

    def go(job):
        start.wait()                                # every call leaves at the same moment
        return job[0], one(client, cfg, job[1])

    t0 = time.monotonic()                           # 2. every model's n calls at the same time
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        results = list(pool.map(go, jobs))
    wall = time.monotonic() - t0

    failed = 0
    for m in models:
        rs = [r for mm, r in results if mm == m]
        bad = [r for r in rs if not r["ok"]]
        failed += len(bad) + (0 if alone[m]["ok"] else 1)
        print(f"together  {m:<28} {len(rs) - len(bad)}/{len(rs)} ok  slowest {max(r['s'] for r in rs):6.1f} s  "
              f"mean {sum(r['s'] for r in rs) / len(rs):6.1f} s  retries {sum(r['retries'] for r in rs)}"
              + (f"  first error: {bad[0]['note']}" if bad else ""), flush=True)
    slowest_alone = max(a["s"] for a in alone.values())
    print(f"wall: together {wall:.1f} s for {len(jobs)} calls; slowest alone {slowest_alone:.1f} s "
          f"(ratio {wall / max(slowest_alone, 0.001):.1f}; near 1-2 = parallel works, near {n} = calls wait in line)")
    print(f"total: {'all ok' if not failed else f'{failed} failed'}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
