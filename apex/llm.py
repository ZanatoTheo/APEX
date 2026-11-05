"""One way to call a model for every role: call_llm, on the OpenAI Python SDK pointed at Meta's Responses API.

- Only function tools are sent. The built-in `web_search` tool has no date gate, so it is refused before sending.
- store=False: the server keeps no history, so callers send back `raw_output` items on the next turn.
- The SDK never retries (max_retries=0); call_llm does, so retries can be counted and logged.
- The API key comes only from $MODEL_API_KEY and never appears in an error message.
"""
import json
import os
import time

import openai

API_KEY_ENV = "MODEL_API_KEY"
FATAL_STATUS = frozenset({400, 401, 403, 404, 422})   # the same request can never succeed


class LLMError(Exception):
    """A failed call. `retryable` is False when sending it again can't help (bad key, bad request, no pricing)."""

    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


def _key() -> str:
    return (os.environ.get(API_KEY_ENV) or "").strip()   # a CR from a Windows-saved .env would break the header


def _clean(text: str, key: str) -> str:
    """Remove the key (raw or repr-escaped) in case an error echoes it back."""
    if not key:
        return text
    text = text.replace(key, "***")
    escaped = repr(key)[1:-1]
    return text.replace(escaped, "***") if escaped != key else text


def make_client(cfg: dict, http_client=None) -> openai.OpenAI:
    key = _key()
    if not key:
        raise LLMError(f"set the {API_KEY_ENV} environment variable to your Meta API key", retryable=False)
    m = cfg["models"]
    return openai.OpenAI(api_key=key, base_url=m["base_url"], timeout=m["request_timeout_s"], max_retries=0,
                         http_client=http_client)


def cost_usd(cfg: dict, model_id: str, usage: dict) -> float:
    row = cfg["pricing"].get(model_id)
    if row is None:
        raise LLMError(f"no pricing row for model {model_id}", retryable=False)
    cached = usage.get("cached_tokens", 0)
    fresh = usage["input_tokens"] - cached
    return (fresh * row["input"] + cached * row["cached_input"] + usage["output_tokens"] * row["output"]) / 1_000_000


def _body(cfg: dict, role: str, messages: list, tools, max_output_tokens: int, reasoning_effort) -> dict:
    tools = list(tools or [])                       # once: a generator would be used up by the check below
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            raise ValueError(f"only function tools are allowed, got {tool!r}")
    spec = cfg["models"]["roles"][role]
    body = {"model": spec["model_id"]}
    rest = list(messages)
    if rest and isinstance(rest[0], dict) and rest[0].get("role") == "system":
        body["instructions"] = rest[0]["content"]
        rest = rest[1:]
    body["input"] = rest
    body["max_output_tokens"] = max_output_tokens
    body["store"] = False
    if tools:
        body["tools"] = tools
    effort = reasoning_effort or spec["reasoning_effort"]
    if effort:
        body["reasoning"] = {"effort": effort}
    return body


def _tool_call(item: dict) -> dict:
    call = {"call_id": item.get("call_id"), "name": item.get("name"), "arguments": None, "error": None}
    raw = item.get("arguments")
    try:
        args = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError as e:
        call["error"] = f"arguments are not a JSON object: {e}"
        return call
    if not isinstance(args, dict):
        call["error"] = f"arguments are not a JSON object: got {type(args).__name__}"
        return call
    call["arguments"] = args
    return call


def _parse(cfg: dict, data, requested_model: str) -> dict:
    """The one place that reads the reply's shape. Shape errors are retryable: the server sent something broken."""
    if not isinstance(data, dict):
        raise LLMError(f"reply is a {type(data).__name__}, expected an object")
    model_id, output, usage = data.get("model"), data.get("output"), data.get("usage")
    if not isinstance(model_id, str) or not model_id:
        raise LLMError("reply has no model")
    if not isinstance(output, list):
        raise LLMError("reply has no output list")
    if not isinstance(usage, dict):
        raise LLMError("reply has no usage")
    counts = {}
    for name in ("input_tokens", "output_tokens"):
        value = usage.get(name)
        if type(value) is not int or value < 0:
            raise LLMError(f"usage.{name} must be a non-negative integer, got {value!r}")
        counts[name] = value
    details = usage.get("input_tokens_details")
    cached = details.get("cached_tokens") if isinstance(details, dict) else None
    usage_out = {"input_tokens": counts["input_tokens"],
                 "cached_tokens": cached if type(cached) is int and 0 <= cached <= counts["input_tokens"] else 0,
                 "output_tokens": counts["output_tokens"]}
    parts, calls = [], []
    for item in output:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "message" and isinstance(item.get("content"), list):
            parts += [p["text"] for p in item["content"]
                      if isinstance(p, dict) and p.get("type") == "output_text" and isinstance(p.get("text"), str)]
        elif item.get("type") == "function_call":
            calls.append(_tool_call(item))
        # reasoning and any other item type: skipped
    status = data.get("status") or "completed"
    reason = None
    if status == "incomplete":
        inc = data.get("incomplete_details")
        reason = inc.get("reason") if isinstance(inc, dict) else None
    rate_model = model_id if model_id in cfg["pricing"] else requested_model   # a dated alias falls back
    return {"text": "".join(parts), "tool_calls": calls, "status": status, "incomplete_reason": reason,
            "raw_output": output, "usage": usage_out, "cost_usd": cost_usd(cfg, rate_model, usage_out),
            "model_id": model_id}


KNOWN_STATUS = frozenset({"completed", "incomplete"})


def _send_once(client, cfg: dict, body: dict, key: str) -> dict:
    """One request. Every error message is cleaned of the key *before* it is cut, and every LLMError is raised
    outside the `except` block, so the SDK error (whose text can hold the key) is not chained as __context__."""
    error = None
    try:
        raw = client.responses.with_raw_response.create(**body)
    except openai.APIStatusError as e:
        error = LLMError(f"HTTP {e.status_code}: {_clean(str(e), key)[:300]}",
                         retryable=e.status_code not in FATAL_STATUS)
    except openai.APIConnectionError as e:          # includes APITimeoutError
        error = LLMError(f"{type(e).__name__}: {_clean(str(e), key)[:300]}")
    except openai.APIError as e:                    # any other SDK error: retry it, never let it skip _clean
        error = LLMError(f"{type(e).__name__}: {_clean(str(e), key)[:300]}")
    if error:
        raise error
    try:
        data = raw.http_response.json()
    except ValueError:
        data, error = None, LLMError(f"reply is not JSON: {_clean(raw.http_response.text, key)[:200]}")
    if error:
        raise error
    if isinstance(data, dict) and (data.get("status") == "failed" or data.get("error")):
        err = data.get("error")
        detail = err.get("message") if isinstance(err, dict) else err
        raise LLMError(f"response failed: {_clean(str(detail), key)[:300]}")
    if isinstance(data, dict) and data.get("status") not in KNOWN_STATUS | {None}:
        raise LLMError(f"reply status is {_clean(str(data.get('status')), key)[:50]!r}, not a finished reply")
    return _parse(cfg, data, body["model"])


def call_llm(client, cfg: dict, role: str, messages: list, *, tools=None, max_output_tokens: int,
             reasoning_effort=None, sleep=time.sleep) -> dict:
    """One model call for `role`, with retries. Returns {text, tool_calls, status, incomplete_reason, raw_output,
    usage, cost_usd, model_id}. Raises ValueError for a non-function tool, LLMError when the call fails."""
    body = _body(cfg, role, messages, tools, max_output_tokens, reasoning_effort)
    key = _key()
    m = cfg["models"]
    attempts = m["retries"] + 1
    for attempt in range(attempts):
        try:
            return _send_once(client, cfg, body, key)
        except LLMError as e:
            last = e
        if not last.retryable:
            raise LLMError(_clean(str(last), key), retryable=False)
        if attempt + 1 == attempts:
            raise LLMError(f"{role} call failed after {attempts} attempts: {_clean(str(last), key)}", retryable=True)
        sleep(m["retry_backoff_s"] * 2 ** attempt)


def list_models(client) -> list[str]:
    """The model IDs this key can use, sorted."""
    error = None
    try:
        return sorted(m.id for m in client.models.list())
    except openai.APIError as e:
        error = LLMError(_clean(f"listing models failed: {e}", _key()), retryable=False)
    raise error                                   # outside the except: the SDK error is not chained


class LiveModel:
    """The real model as a callable: model(role, messages, *, tools, max_output_tokens, reasoning_effort) -> reply.
    FakeModel (apex/fake_model.py) has the same signature, so no later code knows which one it has."""

    def __init__(self, cfg: dict, client):
        self.cfg = cfg
        self.client = client

    def __call__(self, role: str, messages: list, *, tools=None, max_output_tokens: int,
                 reasoning_effort=None) -> dict:
        return call_llm(self.client, self.cfg, role, messages, tools=tools, max_output_tokens=max_output_tokens,
                        reasoning_effort=reasoning_effort)
