"""Creative gen 0 and Mutation, interpretation.md, the replay helper.
Fake model, toy connector and fake data only: no real API call."""
import json
from pathlib import Path

import pytest

from apex import config, prompts
from apex.agent import INTERPRETATION, INTERPRETATION_HEADER, Agent
from apex.budget import CycleBudget
from apex.call_agent import call_agent
from apex.env_connector import Connector, replay
from apex.fake_model import FakeModel
from tests.fixtures.toy_connector import ToyConnector

ROOT = Path(__file__).resolve().parent.parent
F7 = ROOT / "tests" / "fixtures" / "chunks_small_7.json"


# 1
def test_creative_rule_in_gen0_and_mutation():
    gen0 = prompts.gen0_message("BRIEF", ["a: x"], 2, [], 3, 10, 4)
    for text in (gen0, prompts.mutation_system()):
        assert prompts.CREATIVE_RULE in text
    assert "far from" in prompts.CREATIVE_RULE and "mechanism" in prompts.CREATIVE_RULE
    assert "threshold" in prompts.CREATIVE_RULE


# 2
def test_create_writes_interpretation(tmp_path):
    agent = Agent.create(tmp_path / "agents", tmp_path / "logs", "a1", "AX", {"answer.py": "ANSWER = 0\n"})
    assert (agent.dir / INTERPRETATION).read_text() == INTERPRETATION_HEADER


def first_request(tmp_path, interpretation=None):
    cfg = config.load()
    conn = ToyConnector(cfg)
    agent = Agent.create(tmp_path / "agents", tmp_path / "logs", "a1", "AX", conn.starter_files(),
                         conn.cleaning_rules()["data_file"])
    if interpretation is not None:
        (agent.dir / INTERPRETATION).write_text(interpretation)
    conn.release(0)
    fake = FakeModel(cfg, {"agent": [{"text": "ok"}]})
    call_agent(agent, {}, 0, conn, CycleBudget(cfg), fake)
    return json.dumps(fake.calls[0]["body"])


# 3
def test_step_message_marks_empty_interpretation(tmp_path):
    assert "--- interpretation.md (still empty: write it first) ---" in first_request(tmp_path / "a")
    body = first_request(tmp_path / "b", interpretation="signals: X-RULE")
    assert "X-RULE" in body and "still empty" not in body


# ---- the replay helper on fake data ------------------------------------------------------------------------
def data_dir(tmp_path, n=30):
    d = tmp_path / "data"
    d.mkdir()
    rows, ctx = ["date,asset,open,high,low,close,volume"], ["date,series,value"]
    for i in range(n):
        day = f"2024-01-{i + 1:02d}" if i < 31 else None
        a = 100 * 1.01 ** i
        rows += [f"{day},A,{a},{a},{a},{a * 1.0},1", f"{day},B,50,50,50,50,1"]
        ctx.append(f"{day},Rate,1")
    (d / "prices.csv").write_text("\n".join(rows) + "\n")
    (d / "context.csv").write_text("\n".join(ctx) + "\n")
    return d


def strategy(tmp_path, body):
    s = tmp_path / "strategy.py"
    s.write_text(body)
    return s


# 4
def test_replay_all_in_rising_asset(tmp_path):
    out = replay.replay(data_dir(tmp_path), strategy(tmp_path, "def weights(history):\n    return {'A': 1.0}\n"), 10)
    assert out["days"] == 10 and out["errors"] == 0
    assert out["strategy_return"] > out["equal_weight_return"] and out["excess"] > 0


# 5
def test_replay_errors_go_to_cash(tmp_path):
    out = replay.replay(data_dir(tmp_path), strategy(tmp_path, "def weights(history):\n    raise ValueError('bad')\n"),
                        10)
    assert out["errors"] == 10 and abs(out["strategy_return"]) < 1e-9
    assert "ValueError" in out["first_error"]


# 6
def test_replay_never_shows_today(tmp_path):
    body = ("def weights(history):\n"
            "    assert len(history.close) > 0 and history.close.index.max() < history.today\n"
            "    assert history.context.index.max() < history.today\n"
            "    return {'B': 0.5}\n")
    out = replay.replay(data_dir(tmp_path), strategy(tmp_path, body), 20)
    assert out["errors"] == 0 and out["days"] == 20


# 7
def test_connector_offers_replay():
    conn = Connector(config.load(), F7)
    conn.release(0)
    files = conn.script_files("a1", 0)
    assert Path(files["/data/replay.py"]).resolve() == Path(replay.__file__).resolve()
    assert "/data/replay.py" in conn.brief()
