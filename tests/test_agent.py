"""call_agent: one agent, one step, with the fake model and the toy connector."""
import json

import pytest

from apex import config
from apex.agent import Agent
from apex.budget import CycleBudget
from apex.call_agent import call_agent, replay_items
from apex.fake_model import FakeModel
from apex.llm import LLMError
from tests.fixtures.toy_connector import SECRET, ToyConnector

AXIOMS = "Follow the recent direction of the numbers."


def tc(name, **arguments):
    return {"name": name, "arguments": arguments}


def make(tmp_path, cfg, conn=None):
    conn = conn or ToyConnector(cfg)
    agent = Agent.create(tmp_path / "agents", tmp_path / "logs", "a1", AXIOMS, conn.starter_files(),
                         conn.cleaning_rules()["data_file"])
    return agent, conn


def run(tmp_path, cfg, scripts, step=0, report=None, defaults=None, conn=None):
    agent, conn = make(tmp_path, cfg, conn)
    conn.release(step)
    fake = FakeModel(cfg, scripts, defaults=defaults)
    out = call_agent(agent, report or {}, step, conn, CycleBudget(cfg), fake)
    return out, agent, conn, fake


def log_events(agent):
    return [json.loads(line) for line in agent.log_path.read_text().splitlines()]


@pytest.fixture
def cfg():
    return config.load()


# 1
def test_create(cfg, tmp_path):
    agent, _ = make(tmp_path, cfg)
    assert (agent.dir / "axioms.md").read_text() == AXIOMS
    assert (agent.dir / "notes.md").exists()
    assert (agent.dir / "answer.py").read_text() == "ANSWER = 0\n"
    assert (agent.dir / "data.md").exists()
    assert agent.log_path == tmp_path / "logs" / "a1.jsonl" and agent.log_path.exists()
    assert agent.dir not in agent.log_path.parents
    for bad_id in ("A B", "", "../x", "a" * 41):
        with pytest.raises(ValueError):
            Agent.create(tmp_path / "agents", tmp_path / "logs", bad_id, AXIOMS, {})
    for bad_files in ({"axioms.md": "x"}, {"../x": "x"}, {"/etc/x": "x"}, {"log.jsonl": "x"}):
        with pytest.raises(ValueError):
            Agent.create(tmp_path / "agents", tmp_path / "logs", "b1", AXIOMS, bad_files)
    with pytest.raises(ValueError):
        Agent.create(tmp_path / "agents", tmp_path / "logs", "a1", AXIOMS, {})


# 2
def test_edit_then_finish(cfg, tmp_path):
    out, agent, conn, _ = run(tmp_path, cfg, {"agent": [
        {"tool_calls": [tc("write_file", path="answer.py", content="ANSWER = 5\n")]},
        {"tool_calls": [tc("finish", summary="set 5")]}]})
    assert out["ended_by"] == "finish" and out["turns"] == 2
    assert out["files_changed"] == ["answer.py"] and out["summary"] == "set 5"
    assert out["tokens"] > 0 and out["cost"] > 0
    conn.begin_cycle(["a1"])
    assert conn.run_step("a1", agent.dir, 0)["score"] == -2


# 3
def test_final_reply(cfg, tmp_path):
    out, *_ = run(tmp_path, cfg, {"agent": [{"text": "nothing to change"}]})
    assert out["ended_by"] == "reply" and out["turns"] == 1 and out["files_changed"] == []
    assert out["summary"] == "nothing to change"


# 4
def test_turn_cap(cfg, tmp_path):
    cfg = config.load(overrides={"limits": {"call_turns": 3}})
    out, _, _, fake = run(tmp_path, cfg, {}, defaults={"agent": {"tool_calls": [tc("list_files")]}})
    assert out["ended_by"] == "cap:call_turns" and len(fake.calls) == 3


def test_token_cap(cfg, tmp_path):
    cfg["limits"]["call_tokens"] = 60_000                       # the numbers below are for a 60k cap
    step = {"tool_calls": [tc("list_files")], "usage": {"input_tokens": 30000, "output_tokens": 100}}
    out, _, _, fake = run(tmp_path, cfg, {}, defaults={"agent": step})
    assert out["ended_by"] == "cap:call_tokens" and len(fake.calls) == 2 and out["tokens"] == 60200


# 5
def test_finish_with_other_calls(cfg, tmp_path):
    out, agent, *_ = run(tmp_path, cfg, {"agent": [
        {"tool_calls": [tc("write_file", path="notes.md", content="n"), tc("finish")]}]})
    assert out["ended_by"] == "finish" and out["turns"] == 1
    assert (agent.dir / "notes.md").read_text() == "n"


# 6
def test_subagents_share_one_pool(tmp_path):
    cfg = config.load(overrides={"limits": {"subagent_tokens": 3000, "max_output_tokens": 1000,
                                            "min_output_tokens": 256}})
    sub = {"tool_calls": [tc("list_files")], "usage": {"input_tokens": 800, "output_tokens": 100}}
    out, agent, _, fake = run(tmp_path, cfg, {"agent": [
        {"tool_calls": [tc("spawn_subagents", tasks=["t1", "t2"])]},
        {"tool_calls": [tc("finish")]}]}, defaults={"subagent": sub})
    assert out["ended_by"] == "finish"
    sub_calls = [c for c in fake.calls if c["role"] == "subagent"]
    assert len(sub_calls) >= 2
    for c in sub_calls:
        names = {t["name"] for t in c["body"]["tools"]}
        assert "spawn_subagents" not in names and "finish" not in names and "write_file" in names
    spawn_out = next(e for e in log_events(agent) if e["event"] == "tools")["outputs"][0]["output"]
    results = json.loads(spawn_out)
    assert [r["task"] for r in results] == ["t1", "t2"]
    assert all(r["ended_by"] == "cap:subagent_tokens" for r in results)
    assert sum(e["event"] == "subagent" for e in log_events(agent)) == len(sub_calls)
    assert len(sub_calls) * 900 <= 3000


def test_spawn_refuses_bad_tasks(cfg, tmp_path):
    out, agent, *_ = run(tmp_path, cfg, {"agent": [
        {"tool_calls": [tc("spawn_subagents", tasks=[])]},
        {"tool_calls": [tc("spawn_subagents", tasks=["x"] * 9)]},
        {"tool_calls": [tc("finish")]}]})
    outs = [e["outputs"][0]["output"] for e in log_events(agent) if e["event"] == "tools"][:2]
    assert all(o.startswith("error:") for o in outs)


# 7
def test_report_numbers_only(cfg, tmp_path):
    report = {"score": -3.5, "eval": "EVAL-TEXT weak logic", "nested": {"x": 1, "why": "EVAL-TEXT"}}
    _, _, _, fake = run(tmp_path, cfg, {"agent": [{"text": "ok"}]}, report=report)
    body = json.dumps(fake.calls[0]["body"])
    assert "-3.5" in body and '\\"x\\": 1' in body
    assert "EVAL-TEXT" not in body


# 8
def secret_script():
    return {"agent": [{"tool_calls": [tc("read_values")]},
                      {"tool_calls": [tc("read_file", path="answer.py")]},
                      {"tool_calls": [tc("spawn_subagents", tasks=["look"])]},
                      {"tool_calls": [tc("finish")]}],
            "subagent": [{"tool_calls": [tc("read_values")]}, {"text": "done"}]}


def test_secret_never_sent_before_release(cfg, tmp_path):
    out, agent, _, fake = run(tmp_path, cfg, secret_script(), step=2)
    assert out["ended_by"] == "finish"
    assert SECRET not in json.dumps([c["body"] for c in fake.calls])
    first_tools = next(e for e in log_events(agent) if e["event"] == "tools")
    assert [r["value"] for r in json.loads(first_tools["outputs"][0]["output"])] == [3, 5, 4]


def test_secret_control_after_release(cfg, tmp_path):
    _, _, _, fake = run(tmp_path, cfg, secret_script(), step=7)
    assert SECRET in json.dumps([c["body"] for c in fake.calls])


# 9
def test_log(cfg, tmp_path):
    _, agent, *_ = run(tmp_path, cfg, {"agent": [
        {"tool_calls": [tc("write_file", path="answer.py", content="ANSWER = 5\n")]},
        {"tool_calls": [tc("finish")]}]})
    events = log_events(agent)
    assert [e["event"] for e in events] == ["start", "reply", "tools", "reply", "tools", "end"]
    assert events[-1]["ended_by"] == "finish" and events[0]["step"] == 0


# 10
def test_replay_items():
    raw = [{"type": "reasoning", "id": "rs_1", "summary": []},
           {"type": "message", "id": "msg_1", "status": "completed", "role": "assistant",
            "content": [{"type": "output_text", "text": "hi", "annotations": []}]},
           {"type": "function_call", "id": "fc_1", "status": "completed", "call_id": "c1", "name": "f",
            "arguments": "{}"}]
    assert replay_items(raw) == [
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "hi"}]},
        {"type": "function_call", "call_id": "c1", "name": "f", "arguments": "{}"}]


# 11
def test_cycle_dollars_stop(tmp_path):
    cfg = config.load(overrides={"budget": {"cycle_usd": 1e-9}})
    out, _, _, fake = run(tmp_path, cfg, {"agent": [{"text": "x"}]})
    assert out["ended_by"] == "cap:cycle_usd" and out["turns"] == 0 and fake.calls == []


def test_model_error_ends_the_step(cfg, tmp_path):
    agent, conn = make(tmp_path, cfg)
    conn.release(0)

    def down(*a, **k):
        raise LLMError("down")

    out = call_agent(agent, {}, 0, conn, CycleBudget(cfg), down)
    assert out["ended_by"] == "error"
    assert "down" in log_events(agent)[-1]["error"]


# 12
def test_axioms_read_only(cfg, tmp_path):
    _, agent, *_ = run(tmp_path, cfg, {"agent": [
        {"tool_calls": [tc("write_file", path="axioms.md", content="x")]},
        {"tool_calls": [tc("finish")]}]})
    out = next(e for e in log_events(agent) if e["event"] == "tools")["outputs"][0]["output"]
    assert out.startswith("error:") and (agent.dir / "axioms.md").read_text() == AXIOMS


# ---- review fixes ----------------------------------------------------------------------------------------------
class BadTools(ToyConnector):
    def __init__(self, cfg, how):
        super().__init__(cfg)
        self.how = how

    def tools(self, agent_id, agent_dir, step):
        if self.how == "raise":
            raise RuntimeError("tools broke")
        from apex.tools.registry import Tool
        return [Tool("finish", "clash", {"type": "object", "properties": {}}, lambda a: "")]


# 13
@pytest.mark.parametrize("how", ["raise", "clash"])
def test_connector_failure_ends_step_not_run(cfg, tmp_path, how):
    out, agent, _, fake = run(tmp_path, cfg, {}, conn=BadTools(cfg, how))
    assert out["ended_by"] == "error" and out["turns"] == 0 and fake.calls == []
    assert out["error"] and log_events(agent)[-1]["event"] == "end"


# 14
def test_any_model_exception_ends_step(cfg, tmp_path):
    agent, conn = make(tmp_path, cfg)
    conn.release(0)

    def broken(*a, **k):
        raise KeyError("odd")

    assert call_agent(agent, {}, 0, conn, CycleBudget(cfg), broken)["ended_by"] == "error"


def test_any_model_exception_ends_subagent(cfg, tmp_path):
    agent, conn = make(tmp_path, cfg)
    conn.release(0)
    fake = FakeModel(cfg, {"agent": [{"tool_calls": [tc("spawn_subagents", tasks=["t"])]},
                                     {"tool_calls": [tc("finish")]}]})

    def model(role, *a, **k):
        if role == "subagent":
            raise KeyError("odd")
        return fake(role, *a, **k)

    out = call_agent(agent, {}, 0, conn, CycleBudget(cfg), model)
    spawn_out = next(e for e in log_events(agent) if e["event"] == "tools")["outputs"][0]["output"]
    assert out["ended_by"] == "finish" and json.loads(spawn_out)[0]["ended_by"] == "error"


# 15
def test_snapshot_odd_entries(tmp_path):
    from apex.call_agent import snapshot
    (tmp_path / "locked.txt").write_text("x")
    (tmp_path / "locked.txt").chmod(0)
    (tmp_path / "empty").mkdir()
    (tmp_path / "real").mkdir()
    (tmp_path / "dirlink").symlink_to(tmp_path / "real")
    try:
        snap = snapshot(tmp_path)
    finally:
        (tmp_path / "locked.txt").chmod(0o644)
    assert "locked.txt" in snap and "empty/" in snap and "dirlink" in snap


# 16
def test_report_keys_are_names_only(cfg, tmp_path):
    from apex.prompts import report_numbers
    assert report_numbers({"TOY-SECRET-9f3a1c": 1, "note about rule": 2, "score": 3, "cycle_score": 4}) == \
        {"score": 3, "cycle_score": 4}


# 17
def test_data_file_checked_and_log_not_wiped(cfg, tmp_path):
    for bad in ("axioms.md", "../../escape.md", "/abs.md", "log.jsonl"):
        with pytest.raises(ValueError):
            Agent.create(tmp_path / "agents", tmp_path / "logs", "d1", AXIOMS, {}, bad)
    (tmp_path / "logs").mkdir(exist_ok=True)
    (tmp_path / "logs" / "q1.jsonl").write_text("old\n")
    with pytest.raises(ValueError):
        Agent.create(tmp_path / "agents", tmp_path / "logs", "q1", AXIOMS, {})
    assert (tmp_path / "logs" / "q1.jsonl").read_text() == "old\n"
    assert not (tmp_path / "agents" / "q1").exists()


def test_replay_odd_content():
    assert replay_items([{"type": "message", "content": 5}, {"type": "message", "content": "hi"}]) == []


# ---- a connector's script files are visible to run_script, read-only ---------------------------------
def test_agent_script_sees_connector_files(cfg, tmp_path):
    from tests.test_connector import FilesToy
    host = tmp_path / "hello.txt"
    host.write_text("hello from the connector")
    conn = FilesToy(cfg, {"/data/hello.txt": host})
    code = 'open("seen.txt", "w").write(open("/data/hello.txt").read())\n'
    scripts = {"agent": [{"tool_calls": [tc("write_file", path="probe.py", content=code)]},
                         {"tool_calls": [tc("run_script", path="probe.py")]},
                         {"tool_calls": [tc("finish")]}]}
    out, agent, _, _ = run(tmp_path, cfg, scripts, conn=conn)
    assert out["ended_by"] == "finish"
    assert (agent.dir / "seen.txt").read_text() == "hello from the connector"


def test_bad_script_files_end_the_step(cfg, tmp_path):
    from tests.test_connector import FilesToy
    conn = FilesToy(cfg, {"/work/x": tmp_path})
    out, _, _, _ = run(tmp_path, cfg, {"agent": [{"tool_calls": [tc("finish")]}]}, conn=conn)
    assert out["ended_by"] == "error" and "script_files" in out["error"]
