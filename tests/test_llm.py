"""call_llm against a mocked HTTP layer (httpx.MockTransport). No network."""
import json

import httpx
import pytest

from apex import config
from apex.llm import LLMError, call_llm, cost_usd, make_client

KEY = "sk-test-secret"


@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", KEY)


@pytest.fixture
def cfg():
    return config.load()


class Server:
    """Answers each request with the next reply in `replies`; records every request body."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.bodies = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content))
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        status, body = reply
        return httpx.Response(status, json=body)


def ok(output, usage=None, status="completed", **extra):
    body = {"model": "muse-spark-1.3-contributor", "status": status, "output": output,
            "usage": usage or {"input_tokens": 1000, "output_tokens": 200}}
    body.update(extra)
    return 200, body


def message(text):
    return {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}


def fcall(call_id, name, arguments):
    return {"type": "function_call", "call_id": call_id, "name": name, "arguments": arguments}


WRITE_TOOL = {"type": "function", "name": "write_file", "description": "Write a file.",
              "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}


def run(cfg, server, messages=None, role="agent", sleeps=None, **kw):
    client = make_client(cfg, http_client=httpx.Client(transport=httpx.MockTransport(server)))
    sleeps = [] if sleeps is None else sleeps
    kw.setdefault("max_output_tokens", 1000)
    return call_llm(client, cfg, role, messages or [{"role": "user", "content": "hi"}], sleep=sleeps.append, **kw)


# 1
def test_text_reply(cfg):
    out = run(cfg, Server(ok([message("hello")])))
    assert out["text"] == "hello"
    assert out["tool_calls"] == []
    assert out["status"] == "completed" and out["incomplete_reason"] is None
    assert out["usage"] == {"input_tokens": 1000, "cached_tokens": 0, "output_tokens": 200}
    assert out["cost_usd"] == pytest.approx(0.00014)
    assert out["model_id"] == "muse-spark-1.3-contributor"


# 2
def test_tool_call_reply(cfg):
    server = Server(ok([fcall("c1", "write_file", '{"path": "a.py"}')]))
    out = run(cfg, server, tools=[WRITE_TOOL])
    assert out["tool_calls"] == [{"call_id": "c1", "name": "write_file", "arguments": {"path": "a.py"}, "error": None}]
    assert out["text"] == ""
    assert out["raw_output"][0]["call_id"] == "c1"
    assert all(t["type"] == "function" for t in server.bodies[0]["tools"])


# 3
def test_mixed_reply_skips_reasoning(cfg):
    reasoning = {"type": "reasoning", "summary": [{"type": "summary_text", "text": "secret thought"}]}
    out = run(cfg, Server(ok([reasoning, message("ok"), fcall("c2", "write_file", '{"path": "b.py"}')])))
    assert out["text"] == "ok"
    assert [c["call_id"] for c in out["tool_calls"]] == ["c2"]
    assert "secret thought" not in out["text"]


# 4
def test_truncated_reply(cfg):
    reply = ok([message("partial")], usage={"input_tokens": 10, "output_tokens": 50}, status="incomplete",
               incomplete_details={"reason": "max_output_tokens"})
    out = run(cfg, Server(reply))
    assert out["status"] == "incomplete"
    assert out["incomplete_reason"] == "max_output_tokens"
    assert out["text"] == "partial"
    assert out["cost_usd"] == pytest.approx(0.000011)


# 5
def test_429_then_ok(cfg):
    server = Server((429, {"error": {"message": "slow down"}}), ok([message("hi")]))
    sleeps = []
    out = run(cfg, server, sleeps=sleeps)
    assert out["text"] == "hi"
    assert len(server.bodies) == 2
    assert sleeps == [2]


# 6
def test_401_is_fatal_and_hides_key(cfg):
    server = Server((401, {"error": {"message": f"bad key {KEY}"}}))
    sleeps = []
    with pytest.raises(LLMError) as err:
        run(cfg, server, sleeps=sleeps)
    assert err.value.retryable is False
    assert KEY not in str(err.value) and "***" in str(err.value)
    assert len(server.bodies) == 1 and sleeps == []


# 7
def test_timeout_every_try(cfg):
    server = Server(httpx.ReadTimeout("slow"))
    sleeps = []
    with pytest.raises(LLMError) as err:
        run(cfg, server, sleeps=sleeps)
    assert err.value.retryable is True
    assert "after 4 attempts" in str(err.value)
    assert len(server.bodies) == 4
    assert sleeps == [2, 4, 8]


# 8
def test_5xx_and_failed_body_are_retried(cfg):
    failed = ok([], status="failed", error={"message": "overloaded"})
    server = Server((503, {"error": {"message": "down"}}), failed, ok([message("back")]))
    sleeps = []
    out = run(cfg, server, sleeps=sleeps)
    assert out["text"] == "back"
    assert len(server.bodies) == 3
    assert sleeps == [2, 4]


# 9
def test_cost_with_cached_tokens(cfg):
    usage = {"input_tokens": 1_000_000, "cached_tokens": 400_000, "output_tokens": 100_000}
    assert cost_usd(cfg, "muse-wonder-1.0", usage) == pytest.approx(4.48)
    assert cost_usd(cfg, "muse-spark-1.3-contributor", usage) == pytest.approx(0.0808)
    reply = ok([message("x")], usage={"input_tokens": 1_000_000, "output_tokens": 100_000,
                                      "input_tokens_details": {"cached_tokens": 400_000}})
    out = run(cfg, Server(reply))
    assert out["usage"]["cached_tokens"] == 400_000
    assert out["cost_usd"] == pytest.approx(0.0808)


# 10
def test_web_search_refused_before_sending(cfg):
    server = Server(ok([message("never")]))
    with pytest.raises(ValueError):
        run(cfg, server, tools=[{"type": "web_search"}])
    assert server.bodies == []


# 11
def test_request_body_shape(cfg):
    server = Server(ok([message("x")]))
    msgs = [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}]
    run(cfg, server, messages=msgs, role="orchestrator", max_output_tokens=500)
    body = server.bodies[0]
    assert body["model"] == "muse-spark-1.3-contributor"
    assert body["instructions"] == "S"
    assert body["input"] == [{"role": "user", "content": "U"}]
    assert body["store"] is False
    assert body["max_output_tokens"] == 500
    assert "reasoning" not in body and "tools" not in body
    run(cfg, server, messages=msgs, role="orchestrator", max_output_tokens=500, reasoning_effort="high")
    assert server.bodies[1]["reasoning"] == {"effort": "high"}


# 12
def test_tool_round_trip_items_sent_unchanged(cfg):
    items = [{"role": "user", "content": "go"},
             fcall("c1", "write_file", '{"path": "a.py"}'),
             {"type": "function_call_output", "call_id": "c1", "output": "done"}]
    server = Server(ok([message("ok")]))
    run(cfg, server, messages=items, tools=[WRITE_TOOL])
    assert server.bodies[0]["input"] == items
    assert all(t["type"] == "function" for t in server.bodies[0]["tools"])


# 13
def test_bad_tool_json(cfg):
    out = run(cfg, Server(ok([fcall("c3", "write_file", '{"path": ')])))
    call = out["tool_calls"][0]
    assert call["arguments"] is None
    assert call["error"].startswith("arguments are not a JSON object")


# 14
def test_missing_key(cfg, monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY")
    with pytest.raises(LLMError) as err:
        make_client(cfg)
    assert err.value.retryable is False


# 20
def test_key_not_cut_in_half_by_length_limit(cfg):
    failed = ok([], status="failed", error={"message": "x" * 290 + KEY})
    with pytest.raises(LLMError) as err:
        run(cfg, Server(failed))
    assert "sk-test" not in str(err.value)


def _chain(exc):
    seen = []
    while exc is not None and exc not in seen:
        seen.append(exc)
        exc = exc.__cause__ or exc.__context__
    return seen


# 21
def test_no_key_in_exception_chain(cfg):
    with pytest.raises(LLMError) as err:
        run(cfg, Server((401, {"error": {"message": f"bad key {KEY}"}})))
    for exc in _chain(err.value):
        assert KEY not in str(exc) and KEY not in repr(exc)


class _Raising:
    """A stand-in client whose create() always raises `exc`; counts the calls."""

    def __init__(self, exc):
        self.calls = 0
        outer = self

        class _Raw:
            def create(self, **body):
                outer.calls += 1
                raise exc

        class _Responses:
            with_raw_response = _Raw()

        self.responses = _Responses()


# 22
def test_other_sdk_error_retried_and_cleaned(cfg):
    import openai
    client = _Raising(openai.APIError(f"weird {KEY}", request=httpx.Request("POST", "https://x"), body=None))
    sleeps = []
    with pytest.raises(LLMError) as err:
        call_llm(client, cfg, "agent", [{"role": "user", "content": "hi"}], max_output_tokens=10,
                 sleep=sleeps.append)
    assert client.calls == 4 and sleeps == [2, 4, 8]
    assert KEY not in str(err.value)
    for exc in _chain(err.value):
        assert KEY not in str(exc)


# 23
def test_generator_tools_not_used_up(cfg):
    server = Server(ok([message("x")]))
    run(cfg, server, tools=(t for t in [WRITE_TOOL]))
    assert len(server.bodies[0]["tools"]) == 1


# 24
@pytest.mark.parametrize("code", [400, 404, 422])
def test_other_fatal_codes(cfg, code):
    server = Server((code, {"error": {"message": "no"}}))
    with pytest.raises(LLMError) as err:
        run(cfg, server)
    assert err.value.retryable is False and len(server.bodies) == 1


# 25
def test_unexpected_status_retried(cfg):
    server = Server(ok([message("half")], status="in_progress"), ok([message("done")]))
    out = run(cfg, server)
    assert out["text"] == "done" and len(server.bodies) == 2
