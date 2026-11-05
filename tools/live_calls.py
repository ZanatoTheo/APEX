"""Five checks of the live API before a long run. Sends real requests: about a cent in all.

  python tools/live_calls.py [--config configs/live.json] [--env-file .env] [--dry-run]

Every check goes through call_llm, the path a run uses:
  1. plain            agent role: a completed text reply
  2. tool_round_trip  agent role: a call to `lookup_code`, then its output (a random code the model can't guess)
                      sent back with the replayed items; the reply must hold the code (2 requests)
  3. cut_reply        agent role at limits.min_output_tokens: the reply comes back `incomplete`
  4. orchestrator     orchestrator role (its model and effort): the JSON object {"ok": true}
  5. bad_model_id     a model that doesn't exist, no retries: HTTP 400, 404 or 422 (a rejected key is 401/403, a
                      fail), and the error text holds no key
Exit 0 when all 5 pass, 1 when one fails, 2 when the config or the key is missing.
"""
import argparse
import copy
import os
import secrets
import string
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apex import config, envfile, llm               # noqa: E402
from apex.call_agent import replay_items            # noqa: E402
from apex.jsonreply import extract_json             # noqa: E402

BAD_MODEL = "muse-no-such-model-apex-check"
CODE_TOOL = {"type": "function", "name": "lookup_code", "description": "Return the access code stored under a name.",
             "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}
NOT_FOUND = ("HTTP 400", "HTTP 404", "HTTP 422")    # an unknown model; 401/403 would mean the key was rejected


def new_code() -> str:
    """A code like K7Q2-48XZ: the model can only repeat it if it read the tool's output."""
    chars = string.ascii_uppercase + string.digits
    return "-".join("".join(secrets.choice(chars) for _ in range(4)) for _ in range(2))


def checks(cfg: dict) -> list[dict]:
    """The 5 checks: name, role, the first request's messages, tools and max output tokens."""
    user = lambda text: [{"role": "user", "content": text}]   # noqa: E731
    return [
        {"name": "plain", "role": "agent", "tools": None, "max_output_tokens": 2000,
         "messages": user("Reply with the single word: ready")},
        {"name": "tool_round_trip", "role": "agent", "tools": [CODE_TOOL], "max_output_tokens": 2000,
         "messages": [{"role": "system", "content": "You can call tools."},
                      *user("Call the lookup_code tool with name 'apex', then reply with exactly the code it "
                            "returns.")]},
        {"name": "cut_reply", "role": "agent", "tools": None, "max_output_tokens": cfg["limits"]["min_output_tokens"],
         "messages": user("Write a 600-word story about a lighthouse keeper.")},
        {"name": "orchestrator", "role": "orchestrator", "tools": None, "max_output_tokens": 2000,
         "messages": user('Reply with only this JSON object and nothing else: {"ok": true}')},
        {"name": "bad_model_id", "role": "agent", "tools": None, "max_output_tokens": 256,
         "messages": user("Reply with the single word: ready")},
    ]


def _send(client, cfg, chk, messages, sleep):
    return llm.call_llm(client, cfg, chk["role"], messages, tools=chk["tools"],
                        max_output_tokens=chk["max_output_tokens"], sleep=sleep)


def _short(text: str, n: int = 60) -> str:
    return " ".join(str(text).split())[:n]


def _judge(name: str, r: dict, max_out: int) -> tuple[bool, str]:
    text, status = r["text"], r["status"]
    if name == "plain":
        return status == "completed" and bool(text.strip()), f"{status}: {_short(text)!r}"
    if name == "cut_reply":
        if status == "incomplete":
            return True, f"incomplete ({r['incomplete_reason']})"
        return False, f"{status}: not cut at {max_out} output tokens"
    if name == "orchestrator":
        obj = extract_json(text)
        return status == "completed" and isinstance(obj, dict) and obj.get("ok") is True, \
            f"{status}: {_short(text)!r}"
    raise ValueError(name)


def _round_trip(client, cfg, chk, sleep, replies) -> tuple[bool, str]:
    first = _send(client, cfg, chk, chk["messages"], sleep)
    replies.append(first)
    calls = [c for c in first["tool_calls"] if c["name"] == "lookup_code" and c["error"] is None]
    if not calls:
        return False, f"no call to lookup_code ({first['status']}: {_short(first['text'])!r})"
    code = new_code()
    messages = list(chk["messages"]) + replay_items(first["raw_output"])
    for c in first["tool_calls"]:                    # every call needs an output, or the request is refused
        messages.append({"type": "function_call_output", "call_id": c["call_id"], "output": code})
    second = _send(client, cfg, chk, messages, sleep)
    replies.append(second)
    ok = second["status"] == "completed" and code in second["text"]
    return ok, f"code {code} → {second['status']}: {_short(second['text'])!r}"


def _bad_model(client, cfg, chk, sleep, replies) -> tuple[bool, str]:
    bad = copy.deepcopy(cfg)
    bad["models"]["retries"] = 0
    bad["models"]["roles"][chk["role"]]["model_id"] = BAD_MODEL
    bad["pricing"][BAD_MODEL] = {"input": 0.0, "cached_input": 0.0, "output": 0.0}
    try:
        replies.append(_send(client, bad, chk, chk["messages"], sleep))
    except llm.LLMError as e:
        key = os.environ.get(llm.API_KEY_ENV, "").strip()
        text = str(e)
        if key and key in text:
            return False, "the error text holds the key"
        if e.retryable:
            return False, f"retryable error (a run would retry it): {_short(text, 100)}"
        if not text.startswith(NOT_FOUND):
            return False, f"not a model-not-found error: {_short(text, 100)}"
        return True, f"clean error: {_short(text, 100)}"
    return False, "the bad model ID was accepted"


def run_check(cfg: dict, client, chk: dict, sleep=time.sleep, clock=time.monotonic) -> dict:
    replies, t0 = [], clock()
    try:
        if chk["name"] == "tool_round_trip":
            ok, detail = _round_trip(client, cfg, chk, sleep, replies)
        elif chk["name"] == "bad_model_id":
            ok, detail = _bad_model(client, cfg, chk, sleep, replies)
        else:
            replies.append(_send(client, cfg, chk, chk["messages"], sleep))
            ok, detail = _judge(chk["name"], replies[-1], chk["max_output_tokens"])
    except llm.LLMError as e:
        ok, detail = False, f"LLMError: {_short(e, 150)}"
    return {"name": chk["name"], "ok": ok, "detail": detail, "seconds": clock() - t0,
            "requests": max(1, len(replies)),
            "input_tokens": sum(r["usage"]["input_tokens"] for r in replies),
            "output_tokens": sum(r["usage"]["output_tokens"] for r in replies),
            "cost_usd": sum(r["cost_usd"] for r in replies)}


def _model(cfg, chk) -> str:
    return BAD_MODEL if chk["name"] == "bad_model_id" else cfg["models"]["roles"][chk["role"]]["model_id"]


def main(argv=None, client=None) -> int:
    p = argparse.ArgumentParser(description="Five checks of the live API (real requests; about a cent).")
    p.add_argument("--config", default=None, help="config JSON merged over the defaults")
    p.add_argument("--env-file", default=str(ROOT / ".env"), help="file holding MODEL_API_KEY")
    p.add_argument("--dry-run", action="store_true", help="print the checks and send nothing")
    args = p.parse_args(argv)
    try:
        cfg = config.load(args.config)
    except config.ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    plan = checks(cfg)
    if args.dry_run:
        for i, chk in enumerate(plan, 1):
            print(f"{i}. {chk['name']:<16} {chk['role']:<13} {_model(cfg, chk):<30} "
                  f"max_output_tokens {chk['max_output_tokens']:<5} {_short(chk['messages'][-1]['content'])!r}")
        print("dry run: nothing sent (check 2 sends a second request with the tool's output)")
        return 0
    if client is None:
        envfile.load(args.env_file)
        try:
            client = llm.make_client(cfg)
        except llm.LLMError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
    print(f"5 checks against {cfg['models']['base_url']}", flush=True)
    results = []
    for i, chk in enumerate(plan, 1):
        r = run_check(cfg, client, chk)
        results.append(r)
        print(f"{i}. {r['name']:<16} {'ok' if r['ok'] else 'FAIL':<4} {r['seconds']:7.2f} s  "
              f"in {r['input_tokens']:>6} out {r['output_tokens']:>5}  ${r['cost_usd']:.6f}  {r['detail']}",
              flush=True)
    passed = sum(r["ok"] for r in results)
    requests = sum(r["requests"] for r in results)
    mean = sum(r["seconds"] for r in results) / requests
    print(f"total: {passed}/{len(results)} ok · ${sum(r['cost_usd'] for r in results):.6f} · "
          f"mean latency {mean:.2f} s per request ({requests} requests)")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
