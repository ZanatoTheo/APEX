"""FakeModel plays back scripts with the call_llm contract."""
import httpx
import pytest

from apex import config
from apex.fake_model import FakeModel, FakeModelError
from apex.llm import LiveModel, cost_usd, make_client
from tests.test_llm import KEY, WRITE_TOOL, Server, message, ok

GO = [{"role": "user", "content": "go"}]


@pytest.fixture
def cfg():
    return config.load()


# 1
def test_text_step(cfg):
    out = FakeModel(cfg, {"agent": [{"text": "hello"}]})("agent", GO, max_output_tokens=1000)
    assert out["text"] == "hello" and out["tool_calls"] == []
    assert out["status"] == "completed" and out["incomplete_reason"] is None
    assert out["usage"] == {"input_tokens": 9, "cached_tokens": 0, "output_tokens": 1}
    assert out["cost_usd"] == pytest.approx(cost_usd(cfg, "muse-spark-1.3-contributor", out["usage"]))
    assert out["cost_usd"] == pytest.approx(1.1e-6)
    assert out["model_id"] == "muse-spark-1.3-contributor"


# 2
def test_tool_call_step(cfg):
    step = {"tool_calls": [{"name": "write_file", "arguments": {"path": "a.py"}}]}
    out = FakeModel(cfg, {"agent": [step]})("agent", GO, tools=[WRITE_TOOL], max_output_tokens=1000)
    call = out["tool_calls"][0]
    assert call["call_id"].startswith("fc_") and len(call["call_id"]) == 11
    assert call["name"] == "write_file" and call["arguments"] == {"path": "a.py"} and call["error"] is None
    assert out["raw_output"] == [{"type": "function_call", "call_id": call["call_id"], "name": "write_file",
                                  "arguments": '{"path": "a.py"}'}]


# 3
def test_same_seed_same_replies(cfg):
    step = {"text": "t", "tool_calls": [{"name": "write_file", "arguments": {"path": "a.py"}}]}

    def replies(seed):
        model = FakeModel(cfg, {}, seed=seed, defaults={"agent": step})
        return [model("agent", GO, tools=[WRITE_TOOL], max_output_tokens=1000) for _ in range(3)]

    assert replies(7) == replies(7)
    ids = lambda rs: [r["tool_calls"][0]["call_id"] for r in rs]
    assert ids(replies(7)) != ids(replies(8))


# 4
def test_function_step(cfg):
    step = lambda messages, tools, rng: {"text": messages[-1]["content"].upper()}
    assert FakeModel(cfg, {"agent": [step]})("agent", GO, max_output_tokens=1000)["text"] == "GO"


# 5
def test_unoffered_tool(cfg):
    step = {"tool_calls": [{"name": "delete_file", "arguments": {"path": "a.py"}}]}
    with pytest.raises(FakeModelError, match="delete_file"):
        FakeModel(cfg, {"agent": [step]})("agent", GO, tools=[WRITE_TOOL], max_output_tokens=1000)


# 6
def test_empty_queue(cfg):
    with pytest.raises(FakeModelError, match="evaluator"):
        FakeModel(cfg, {"evaluator": []})("evaluator", GO, max_output_tokens=1000)
    model = FakeModel(cfg, {"evaluator": []}, defaults={"evaluator": {"text": "d"}})
    assert [model("evaluator", GO, max_output_tokens=1000)["text"] for _ in range(3)] == ["d", "d", "d"]


# 7
def test_same_tool_guard_as_call_llm(cfg):
    model = FakeModel(cfg, {}, defaults={"agent": {"text": "x"}})
    with pytest.raises(ValueError):
        model("agent", GO, tools=[{"type": "web_search"}], max_output_tokens=1000)
    assert model.calls == []


# 8
def test_truncation(cfg):
    out = FakeModel(cfg, {"agent": [{"text": "z" * 40_000}]})("agent", GO, max_output_tokens=100)
    assert out["status"] == "incomplete" and out["incomplete_reason"] == "max_output_tokens"
    assert out["usage"]["output_tokens"] == 100


# 9
def test_calls_recorded(cfg):
    model = FakeModel(cfg, {}, defaults={"agent": {"text": "a"}, "orchestrator": {"text": "o"}})
    model("agent", GO, max_output_tokens=1000)
    model("orchestrator", [{"role": "system", "content": "S"}] + GO, max_output_tokens=1000)
    assert [c["role"] for c in model.calls] == ["agent", "orchestrator"]
    assert model.calls[1]["body"]["instructions"] == "S"
    assert model.calls[1]["body"]["model"] == "muse-spark-1.3-contributor"


# 10
def test_same_shape_as_real(cfg, monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", KEY)
    client = make_client(cfg, http_client=httpx.Client(transport=httpx.MockTransport(Server(ok([message("r")])))))
    live = LiveModel(cfg, client)("agent", GO, max_output_tokens=1000)
    fake = FakeModel(cfg, {"agent": [{"text": "f"}]})("agent", GO, max_output_tokens=1000)
    keys = {"text", "tool_calls", "status", "incomplete_reason", "raw_output", "usage", "cost_usd", "model_id"}
    assert set(live) == set(fake) == keys
    assert set(live["usage"]) == set(fake["usage"])


# 20
def test_reply_arguments_not_shared_with_script(cfg):
    step = {"tool_calls": [{"name": "write_file", "arguments": {"path": "a.py"}}]}
    model = FakeModel(cfg, {}, defaults={"agent": step})
    first = model("agent", GO, tools=[WRITE_TOOL], max_output_tokens=1000)
    first["tool_calls"][0]["arguments"]["path"] = "changed.py"
    second = model("agent", GO, tools=[WRITE_TOOL], max_output_tokens=1000)
    assert second["tool_calls"][0]["arguments"] == {"path": "a.py"}


# 21
def test_recorded_call_is_what_was_sent(cfg):
    messages = [{"role": "user", "content": "original"}]
    model = FakeModel(cfg, {}, defaults={"agent": {"text": "x"}})
    model("agent", messages, max_output_tokens=1000)
    messages[0]["content"] = "edited later"
    assert model.calls[0]["body"]["input"][0]["content"] == "original"


# 24
def test_truncated_tool_call_is_cut(cfg):
    step = {"tool_calls": [{"name": "write_file", "arguments": {"path": "a.py", "content": "y" * 4000}}]}
    out = FakeModel(cfg, {"agent": [step]})("agent", GO, tools=[WRITE_TOOL], max_output_tokens=100)
    assert out["status"] == "incomplete" and out["incomplete_reason"] == "max_output_tokens"
    call = out["tool_calls"][-1]
    assert call["arguments"] is None and call["error"].startswith("arguments are not a JSON object")
    import json
    with pytest.raises(ValueError):
        json.loads(out["raw_output"][-1]["arguments"])
