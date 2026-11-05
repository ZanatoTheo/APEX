"""The step message holds the budget, the priority and the files, so no turn goes to re-reading them.
Fake model and toy connector only: no real API call."""
import json

from apex import config, prompts
from apex.agent import Agent
from apex.budget import CycleBudget
from apex.call_agent import call_agent
from apex.fake_model import FakeModel
from tests.fixtures.toy_connector import ToyConnector

FILES = {"notes.md": "N", "answer.py": "A"}
LISTING = ["answer.py", "notes.md"]
BUDGET = {"tokens": 40000, "turns": 25}


def msg(files=FILES, starters=("answer.py",)):
    return prompts.step_message(0, 10, {}, files=files, listing=LISTING, budget=BUDGET, starters=set(starters))


# 1
def test_budget_in_message():
    m = msg()
    assert "40000 tokens" in m and "25 turns" in m


# 2
def test_priority_files_and_listing():
    m = msg()
    assert "Your score comes only from answer.py" in m
    assert "--- answer.py (still the starter: replace it) ---\nA" in m
    assert "--- notes.md ---\nN" in m
    assert "Files in your folder: answer.py, notes.md" in m


# 3
def test_long_file_cut():
    m = msg(files={"notes.md": "N", "answer.py": "x" * 20000})
    assert "x" * 6000 + "\n… [14000 more chars cut]" in m
    assert "x" * 6001 not in m


# 4
def test_missing_file():
    assert "--- notes.md ---\n(missing)" in msg(files={"notes.md": None, "answer.py": "A"})


def first_request(tmp_path, answer=None):
    cfg = config.load(overrides={"limits": {"call_tokens": 40000}})
    conn = ToyConnector(cfg)
    agent = Agent.create(tmp_path / "agents", tmp_path / "logs", "a1", "AXIOMS", conn.starter_files(),
                         conn.cleaning_rules()["data_file"])
    (agent.dir / "notes.md").write_text("PLAN-XYZ")
    if answer is not None:
        (agent.dir / "answer.py").write_text(answer)
    conn.release(0)
    fake = FakeModel(cfg, {"agent": [{"text": "ok"}]})
    call_agent(agent, {}, 0, conn, CycleBudget(cfg), fake)
    return json.dumps(fake.calls[0]["body"])


# 5
def test_call_agent_first_message(tmp_path):
    body = first_request(tmp_path)
    assert "PLAN-XYZ" in body and "ANSWER = 0" in body
    assert "still the starter" in body and "40000 tokens" in body


# 6
def test_changed_main_file_not_marked(tmp_path):
    body = first_request(tmp_path, answer="ANSWER = 1\n")
    assert "ANSWER = 1" in body and "still the starter" not in body


# 7
def test_no_files_old_message():
    m = prompts.step_message(0, 10, {})
    assert m.startswith("Step 1 of 10 is released.") and m.rstrip().endswith("then call finish.")
    assert "---" not in m and "Files in your folder" not in m
