"""A survivor below operation.advice_below sees its own Eval weaknesses as a suggestion, once, in the first step of
the next cycle. Toy connector and demo model only: no real API call."""
import json

import pytest

from apex import config, prompts
from apex.fake_run import demo_model
from apex.operation import Operation
from tests.fixtures.toy_connector import ToyConnector

FLAW = "W-FLAW"
EVAL = {"strengths": ["ran"], "weaknesses": [FLAW], "axiom_flaws": [], "axiom_fixes": []}


# 1
def test_step_message_with_advice():
    m = prompts.step_message(0, 10, {}, advice={"score": -0.02, "weaknesses": ["W1", "W2"]})
    assert "A suggestion from a reviewer" in m and "-0.02" in m and "W1" in m and "W2" in m
    assert "suggestion from a reviewer" not in prompts.step_message(0, 10, {})


class FlawEval:
    """The demo model, but Eval always reports FLAW as a weakness."""

    def __init__(self, inner):
        self.inner, self.calls = inner, inner.calls

    def __call__(self, role, messages, **kw):
        reply = self.inner(role, messages, **kw)
        if role == "evaluator":
            reply = {**reply, "text": json.dumps(EVAL)}
        return reply


def agent_requests(model, agent_id, step_no):
    out = []
    for c in model.calls:
        body = json.dumps(c["body"])
        if c["role"] == "agent" and f"You are agent {agent_id}" in body and f"Step {step_no} of 8" in body:
            out.append(body)
    return out


def run_toy(tmp_path, advice_below):
    ops = {"agents": 3, "max_loops": 1, "max_cycles": 2}
    if advice_below != "default":
        ops["advice_below"] = advice_below
    cfg = config.load(overrides={"operation": ops})
    model = FlawEval(demo_model(cfg))
    op = Operation(cfg, ToyConnector(cfg), model, tmp_path / "run")
    op.run()
    gen = [json.loads(x) for x in (op.run_dir / "log.jsonl").read_text().splitlines()
           if json.loads(x)["event"] == "generation"][0]
    return model, gen["kept"], gen["new"]


# 2
def test_survivors_below_get_own_advice(tmp_path):
    model, kept, new = run_toy(tmp_path, 1e9)
    assert kept and new
    for a in kept:
        first = agent_requests(model, a, 5)
        assert first and FLAW in first[0] and "A suggestion from a reviewer" in first[0]
        assert all(FLAW not in b for b in agent_requests(model, a, 6))
    for a in new:
        assert all(FLAW not in b for b in agent_requests(model, a, 5))


# 3
def test_no_advice_when_scores_above(tmp_path):
    model, _, _ = run_toy(tmp_path, -1e9)
    assert not any(FLAW in json.dumps(c["body"]) for c in model.calls if c["role"] == "agent")


# 4
def test_advice_off_by_default(tmp_path):
    model, _, _ = run_toy(tmp_path, "default")
    assert not any(FLAW in json.dumps(c["body"]) for c in model.calls if c["role"] == "agent")


# 5
def test_advice_below_config():
    assert config.load(overrides={"operation": {"advice_below": 0.0}})["operation"]["advice_below"] == 0.0
    assert config.load()["operation"]["advice_below"] is None
    for bad in ("x", True):
        with pytest.raises(config.ConfigError):
            config.load(overrides={"operation": {"advice_below": bad}})
