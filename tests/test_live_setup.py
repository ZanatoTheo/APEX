"""max_cycles, configs/live.json, start.py --skip-holdout, tools/live_calls.py.
Fake models and fake HTTP only: no real API call."""
import json
import re
import signal
from pathlib import Path

import httpx
import pytest

import run
from apex import config, llm
from apex.estimate import cycle_cost
from apex.fake_run import demo_model
from apex.operation import Operation
from environment import start
from tests.fixtures.toy_connector import ToyConnector
from tools import live_calls

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"
LIVE = ROOT / "configs" / "live.json"
FINAL = "Current agents, best loop score first"      # a phrase only the final prompt holds
KEY = "sk-test-secret-live"


@pytest.fixture(autouse=True)
def hang_guard():
    def stuck(*_):
        raise AssertionError("test ran past 90 s")
    old = signal.signal(signal.SIGALRM, stuck)
    signal.alarm(90)
    yield
    signal.alarm(0)
    signal.signal(signal.SIGALRM, old)


def events(run_dir, kind=None):
    rows = [json.loads(line) for line in (Path(run_dir) / "log.jsonl").read_text().splitlines()]
    return [r for r in rows if kind is None or r["event"] == kind]


def run_toy(tmp_path, max_cycles, loops):
    cfg = config.load(overrides={"operation": {"agents": 3, "max_loops": loops, "max_cycles": max_cycles}})
    model = demo_model(cfg)
    op = Operation(cfg, ToyConnector(cfg), model, tmp_path / "run")
    return op, model, op.run()


# ---- 1: max_cycles on the toy (8 steps, 4 per cycle) ------------------------------------------------------------
def test_max_cycles_one(tmp_path):
    op, model, result = run_toy(tmp_path, 1, 2)
    assert result["reason"] == "max_cycles" and result["cycles"] == 1
    assert len(events(op.run_dir, "cycle_end")) == 1
    assert events(op.run_dir, "generation") == []
    assert events(op.run_dir, "stop")[-1]["reason"] == "max_cycles"
    assert any(FINAL in json.dumps(c["body"]["input"]) for c in model.calls if c["role"] == "orchestrator")
    assert json.loads((op.run_dir / "final.json").read_text())["cycles"] == 1


def test_max_cycles_stops_inside_loop_two(tmp_path):
    op, _, result = run_toy(tmp_path, 3, 2)
    assert result["reason"] == "max_cycles" and result["loops"] == 2 and result["cycles"] == 3
    assert len(events(op.run_dir, "cycle_end")) == 3
    assert len(events(op.run_dir, "generation")) == 2


def test_loop_end_comes_first(tmp_path):
    _, _, result = run_toy(tmp_path, 2, 1)
    assert result["reason"] == "max_loops" and result["cycles"] == 2


# ---- 2: the config ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("bad", [0, -1, 1.5, "2", True])
def test_max_cycles_refused(bad):
    with pytest.raises(config.ConfigError):
        config.load(overrides={"operation": {"max_cycles": bad}})


def test_max_cycles_accepted():
    assert config.load()["operation"]["max_cycles"] is None
    assert config.load(overrides={"operation": {"max_cycles": 4}})["operation"]["max_cycles"] == 4
    assert config.load(overrides={"operation": {"max_cycles": None}})["operation"]["max_cycles"] is None
    assert json.loads((ROOT / "configs" / "default.json").read_text())["operation"]["max_cycles"] is None


# ---- 3: the CLI and start.py -----------------------------------------------------------------------------------
def test_cli_rejects_zero_cycles(tmp_path, capsys):
    with pytest.raises(SystemExit) as e:
        run.main(["run", "--connector", "tests.fixtures.toy_connector", "--fake", "--max-cycles", "0",
                  "--out", str(tmp_path)])
    assert e.value.code == 2 and "max_cycles" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def start_stubbed(monkeypatch, tmp_path, *extra):
    seen = {}

    def fake_main(cmd):
        seen["cmd"] = cmd
        return 0
    monkeypatch.setattr(run, "main", fake_main)
    code = start.main(["--csv", str(FIX / "prices_small.csv"), "--assets", str(FIX / "assets_small.json"),
                       "--seed", "5", "--build-out", str(tmp_path / "data"), *extra])
    return code, seen["cmd"]


def worst_cycles(text):
    return int(re.search(r"worst case: (\d+) cycles", text).group(1))


def test_start_skip_holdout(monkeypatch, tmp_path, capsys):
    code, cmd = start_stubbed(monkeypatch, tmp_path)
    assert code == 0 and "--holdout" in cmd
    with_holdout = worst_cycles(capsys.readouterr().out)
    code, cmd = start_stubbed(monkeypatch, tmp_path, "--skip-holdout", "--max-cycles", "2")
    assert code == 0 and "--holdout" not in cmd
    assert cmd[cmd.index("--max-cycles") + 1] == "2"
    train = json.loads(Path(cmd[cmd.index("--data") + 1]).read_text())
    assert train["history"][0]["date"] >= "2023-01-01"            # history still starts after the held-out year
    skipped = worst_cycles(capsys.readouterr().out)
    assert skipped <= 2 and skipped < with_holdout


# ---- 4: configs/live.json ---------------------------------------------------------------------------------------
def test_live_config():
    cfg = config.load(LIVE)
    assert cfg["task"]["connector"] == "apex.env_connector"
    assert cfg["operation"]["max_cycles"] == 4
    assert cfg["models"]["retries"] == 6 and cfg["models"]["retry_backoff_s"] == 5
    assert cfg["models"]["request_timeout_s"] >= 600       # a 16k-token Mutation reply fits (non-streaming)
    assert cycle_cost(cfg, 28)["total"] <= cfg["budget"]["cycle_usd"]


# ---- 5: tools/live_calls.py ----------------------------------------------------------------------------------------
def message(text):
    return {"type": "message", "id": "msg_srv_1", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": text}]}


def fake_api(cut_status="incomplete", echo=True, bad_status=404):
    """A fake Responses API that answers each check by the request's shape; records every body."""
    bodies = []

    def handle(request):
        body = json.loads(request.content)
        bodies.append(body)
        if body["model"] == live_calls.BAD_MODEL:
            return httpx.Response(bad_status, json={"error": {"message": f"model not found (key {KEY})"}})

        def reply(output, status="completed"):
            data = {"model": body["model"], "status": status, "output": output,
                    "usage": {"input_tokens": 50, "output_tokens": 10}}
            if status == "incomplete":
                data["incomplete_details"] = {"reason": "max_output_tokens"}
            return httpx.Response(200, json=data)
        outputs = [i["output"] for i in body["input"] if i.get("type") == "function_call_output"]
        if outputs:
            return reply([message(f"The code is {outputs[0]}." if echo else "2 + 3 = 5")])
        if body.get("tools"):
            return reply([{"type": "function_call", "id": "fc_srv_1", "status": "completed", "call_id": "call_1",
                           "name": "lookup_code", "arguments": '{"name": "apex"}'}])
        if body["max_output_tokens"] <= 256:
            return reply([message("Once upon a time")], cut_status)
        if any('{"ok": true}' in str(i.get("content", "")) for i in body["input"]):
            return reply([message('{"ok": true}')])
        return reply([message("ready")])
    return handle, bodies


def client_for(handler, monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", KEY)
    return llm.make_client(config.load(LIVE), http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_live_calls_dry_run(monkeypatch, capsys):
    def no_client(*a, **k):
        raise AssertionError("--dry-run made a client")
    monkeypatch.setattr(llm, "make_client", no_client)
    assert live_calls.main(["--dry-run", "--config", str(LIVE)]) == 0
    out = capsys.readouterr().out
    assert re.findall(r"^(\d)\. ", out, re.M) == ["1", "2", "3", "4", "5"]


def test_live_calls_needs_a_key(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    assert live_calls.main(["--env-file", str(tmp_path / "missing.env")]) == 2
    assert "MODEL_API_KEY" in capsys.readouterr().err


def test_live_calls_all_pass(monkeypatch, capsys):
    handler, bodies = fake_api()
    code = live_calls.main(["--config", str(LIVE)], client=client_for(handler, monkeypatch))
    out = capsys.readouterr().out
    assert code == 0, out
    assert len(re.findall(r"^\d\. \S+\s+ok\s", out, re.M)) == 5
    assert "total: 5/5 ok" in out
    assert len(bodies) == 6                                        # the round trip is 2 requests
    second = next(b for b in bodies if any(i.get("type") == "function_call_output" for i in b["input"]))
    sent = next(i for i in second["input"] if i.get("type") == "function_call_output")
    assert sent["call_id"] == "call_1" and re.fullmatch(r"[A-Z0-9]{4}-[A-Z0-9]{4}", sent["output"])
    replayed = next(i for i in second["input"] if i.get("type") == "function_call")
    assert "id" not in replayed and "status" not in replayed       # server ids point at nothing with store=False
    assert "404" in out and KEY not in out


def test_live_calls_uncut_reply_fails(monkeypatch, capsys):
    handler, _ = fake_api(cut_status="completed")
    assert live_calls.main(["--config", str(LIVE)], client=client_for(handler, monkeypatch)) == 1
    out = capsys.readouterr().out
    assert re.search(r"^3\. \S+\s+FAIL", out, re.M) and "total: 4/5 ok" in out


def test_live_calls_round_trip_needs_the_output(monkeypatch, capsys):
    handler, _ = fake_api(echo=False)                              # a server that ignores the tool's output
    assert live_calls.main(["--config", str(LIVE)], client=client_for(handler, monkeypatch)) == 1
    assert re.search(r"^2\. \S+\s+FAIL", capsys.readouterr().out, re.M)


def test_live_calls_rejected_key_is_not_a_clean_bad_id(monkeypatch, capsys):
    handler, _ = fake_api(bad_status=401)
    assert live_calls.main(["--config", str(LIVE)], client=client_for(handler, monkeypatch)) == 1
    assert re.search(r"^5\. \S+\s+FAIL", capsys.readouterr().out, re.M)
