"""ToolSet turns model tool calls into outputs, never crashing on agent mistakes."""
import json

import pytest

from apex import config
from apex.fake_model import FakeModel
from apex.tools import core_toolset
from apex.tools.files import ToolError, Workspace
from apex.tools.registry import Tool, ToolSet

CORE = {"write_file", "edit_file", "delete_file", "read_file", "list_files", "run_script"}


@pytest.fixture
def cfg():
    return config.load()


def echo_set(cfg, handler=None):
    calls = []

    def default(args):
        calls.append(args)
        return args["msg"]

    schema = {"type": "object", "properties": {"msg": {"type": "string"}}, "required": ["msg"]}
    ts = ToolSet(cfg)
    ts.add(Tool("echo", "Echo msg.", schema, handler or default))
    return ts, calls


def call(name, arguments, error=None, call_id="c1"):
    return {"call_id": call_id, "name": name, "arguments": arguments, "error": error}


# 19
def test_specs_and_duplicates(cfg, tmp_path):
    ts = core_toolset(Workspace(tmp_path, cfg), cfg)
    specs = ts.specs()
    assert {s["name"] for s in specs} == CORE and len(specs) == 6
    assert all(s["type"] == "function" for s in specs)
    with pytest.raises(ValueError):
        ts.add(Tool("write_file", "again", {"type": "object", "properties": {}}, lambda a: ""))


# 20
def test_good_call(cfg):
    ts, _ = echo_set(cfg)
    assert ts.run(call("echo", {"msg": "hi"})) == {"type": "function_call_output", "call_id": "c1", "output": "hi"}


# 21
def test_bad_json_not_run(cfg):
    ts, calls = echo_set(cfg)
    out = ts.run(call("echo", None, error="arguments are not a JSON object: Expecting value"))
    assert out["output"].startswith("error:") and "not valid JSON" in out["output"]
    assert calls == []


# 22
def test_unknown_tool(cfg):
    ts, _ = echo_set(cfg)
    assert ts.run(call("nope", {}))["output"] == "error: no tool named nope"


# 23
def test_schema_check(cfg):
    ts, calls = echo_set(cfg)
    assert ts.run(call("echo", {}))["output"] == "error: argument msg is required"
    assert ts.run(call("echo", {"msg": 5}))["output"] == "error: argument msg must be a string"
    assert calls == []


# 24
def test_handler_errors(cfg):
    def bad(args):
        raise ToolError("bad")

    def boom(args):
        raise RuntimeError("boom")

    assert echo_set(cfg, bad)[0].run(call("echo", {"msg": "x"}))["output"] == "error: bad"
    assert echo_set(cfg, boom)[0].run(call("echo", {"msg": "x"}))["output"] == "error: RuntimeError: boom"


# 25
def test_long_output_cut():
    cfg = config.load(overrides={"tools": {"max_tool_output_chars": 10}})
    ts, _ = echo_set(cfg)
    assert ts.run(call("echo", {"msg": "y" * 25}))["output"] == "y" * 10 + "\n… [15 more chars cut]"


# 26
def test_end_to_end_with_fake_model(cfg, tmp_path):
    ws = Workspace(tmp_path, cfg)
    ts = core_toolset(ws, cfg)
    script = [{"tool_calls": [{"name": "write_file", "arguments": {"path": "s.py", "content": "print(2+2)"}}]},
              {"tool_calls": [{"name": "run_script", "arguments": {"path": "s.py"}}]}]
    model = FakeModel(cfg, {"agent": script})
    outputs = []
    for _ in range(2):
        reply = model("agent", [{"role": "user", "content": "go"}], tools=ts.specs(), max_output_tokens=1000)
        outputs += [ts.run(c) for c in reply["tool_calls"]]
    assert (tmp_path / "s.py").read_text() == "print(2+2)"
    assert "exit_code: 0" in outputs[1]["output"]
    assert "--- stdout ---\n4\n" in outputs[1]["output"]


# 32
@pytest.mark.parametrize("bad", [
    {"call_id": "c1", "name": "echo", "arguments": ["x"], "error": None},
    {"call_id": "c1", "name": "echo", "arguments": "x", "error": None},
    {"call_id": "c1", "name": "echo", "arguments": 5, "error": None},
    {"call_id": "c1", "name": ["echo"], "arguments": {}, "error": None},
    {"name": "echo", "arguments": {"msg": "x"}},
    None,
])
def test_run_never_raises(cfg, bad):
    ts, calls = echo_set(cfg)
    out = ts.run(bad)
    assert out["type"] == "function_call_output"
    if bad is None or bad.get("arguments") != {"msg": "x"}:
        assert out["output"].startswith("error:")


def test_unjsonable_handler_result(cfg):
    ts, _ = echo_set(cfg, lambda args: {1, 2})
    assert ts.run(call("echo", {"msg": "x"}))["output"].startswith("error:")
