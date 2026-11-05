"""A fake model with the same signature and reply shape as LiveModel / call_llm, for tests and `--fake` runs.

It knows nothing about any task: per role it plays back the steps a test (or a connector's fixtures) gives it.

A step is a dict {text?, tool_calls?: [{name, arguments}], status?, incomplete_reason?, usage?}, or a function
(messages, tools, rng) -> such a dict, for replies that depend on the prompt.
"""
import copy
import json
import random

from . import llm


class FakeModelError(Exception):
    """The script doesn't fit the call (no step left, or a tool that wasn't offered): a bug in the test."""


class FakeModel:
    def __init__(self, cfg: dict, scripts: dict, seed: int = 0, defaults: dict | None = None):
        self.cfg = cfg
        self.queues = {role: list(steps) for role, steps in scripts.items()}
        self.defaults = dict(defaults or {})
        self.rng = random.Random(seed)
        self.calls = []                       # [{role, body}], every request as call_llm would send it

    def __call__(self, role: str, messages: list, *, tools=None, max_output_tokens: int,
                 reasoning_effort=None) -> dict:
        body = llm._body(self.cfg, role, messages, tools, max_output_tokens, reasoning_effort)  # same tool guard
        body = copy.deepcopy(body)            # a record of what was sent, not of what the caller edits later
        self.calls.append({"role": role, "body": body})
        step = self._next_step(role)
        offered = body.get("tools", [])
        if callable(step):
            step = step(messages, offered, self.rng)
        return self._reply(role, body, copy.deepcopy(step), offered)   # replies never share the script's dicts

    def _next_step(self, role: str):
        queue = self.queues.get(role)
        if queue:
            return queue.pop(0)
        if role in self.defaults:
            return self.defaults[role]
        raise FakeModelError(f"no scripted step left for role {role}")

    def _reply(self, role: str, body: dict, step: dict, offered: list) -> dict:
        names = {t["name"] for t in offered}
        text = step.get("text", "")
        output, calls, args_chars = [], [], 0
        if text:
            output.append({"type": "message", "role": "assistant",
                           "content": [{"type": "output_text", "text": text}]})
        for spec in step.get("tool_calls", []):
            if spec["name"] not in names:
                raise FakeModelError(f"scripted tool {spec['name']} was not offered (offered: {sorted(names)})")
            call_id = f"fc_{self.rng.getrandbits(32):08x}"
            raw_args = json.dumps(spec["arguments"])
            args_chars += len(raw_args)
            output.append({"type": "function_call", "call_id": call_id, "name": spec["name"],
                           "arguments": raw_args})
            calls.append({"call_id": call_id, "name": spec["name"], "arguments": spec["arguments"], "error": None})

        status = step.get("status", "completed")
        reason = step.get("incomplete_reason")
        if "usage" in step:
            usage = {"input_tokens": step["usage"]["input_tokens"],
                     "cached_tokens": step["usage"].get("cached_tokens", 0),
                     "output_tokens": step["usage"]["output_tokens"]}
        else:
            instructions = body.get("instructions", "")
            usage = {"input_tokens": max(1, (len(json.dumps(body["input"])) + len(instructions)
                                             + len(json.dumps(offered))) // 4),
                     "cached_tokens": 0,
                     "output_tokens": max(1, (len(text) + args_chars) // 4)}
        if usage["output_tokens"] > body["max_output_tokens"]:     # the real API cuts the reply here
            usage["output_tokens"] = body["max_output_tokens"]
            status, reason = "incomplete", "max_output_tokens"
            if calls:                         # the last tool call is cut mid-arguments, as a real cut would leave it
                last = output[-1]
                last["arguments"] = last["arguments"][: len(last["arguments"]) // 2]
                calls[-1] = llm._tool_call(last)

        model_id = body["model"]
        return {"text": text, "tool_calls": calls, "status": status,
                "incomplete_reason": reason if status == "incomplete" else None,
                "raw_output": output, "usage": usage, "cost_usd": llm.cost_usd(self.cfg, model_id, usage),
                "model_id": model_id}
