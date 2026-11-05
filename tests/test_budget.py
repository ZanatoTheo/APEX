"""Caps per call_agent, the shared subagent pool, and the $ per cycle."""
import pytest

from apex import config
from apex.budget import CallBudget, CapReached, CycleBudget
from apex.fake_model import FakeModel

GO = [{"role": "user", "content": "go"}]
BIG_REPLY = {"text": "x" * 16_000}                    # 4,000 output tokens


def setup(overrides=None, step=BIG_REPLY):
    cfg = config.load(overrides=overrides)
    model = FakeModel(cfg, {}, defaults={r: step for r in ("agent", "subagent", "orchestrator")})
    cycle = CycleBudget(cfg)
    return cfg, model, cycle


# 11
def test_turn_cap():
    cfg, model, cycle = setup({"limits": {"call_turns": 3}}, {"text": "ok"})
    budget = CallBudget(cfg, cycle, "a1")
    for _ in range(3):
        budget.call(model, "agent", GO)
    with pytest.raises(CapReached) as err:
        budget.call(model, "agent", GO)
    assert err.value.kind == "call_turns"
    assert cycle.events[-1] == {"event": "cap", "kind": "call_turns", "agent_id": "a1", "scope": "agent",
                                "used": 3, "cap": 3}
    assert len(model.calls) == 3


# 12
def test_token_cap_shrinks_then_stops():
    cfg, model, cycle = setup({"limits": {"call_tokens": 10_000}})
    budget = CallBudget(cfg, cycle, "a1")
    for _ in range(3):
        budget.call(model, "agent", GO)
    assert [c["body"]["max_output_tokens"] for c in model.calls] == [4000, 4000, 1973]
    assert budget.used["agent"] == 10_000
    with pytest.raises(CapReached) as err:
        budget.call(model, "agent", GO)
    assert err.value.kind == "call_tokens"
    assert budget.used["agent"] <= 10_000


# 13
def test_three_subagents_share_one_cap():
    cfg, model, cycle = setup({"limits": {"subagent_tokens": 20_000}})
    budget = CallBudget(cfg, cycle, "a1")
    names = ["s1", "s2", "s3"]
    for i in range(5):
        budget.call(model, "subagent", [{"role": "user", "content": names[i % 3]}], scope="subagent")
    assert budget.used["subagent"] == 20_000
    for name in ("s3", "s1", "s2"):
        with pytest.raises(CapReached) as err:
            budget.call(model, "subagent", [{"role": "user", "content": name}], scope="subagent")
        assert err.value.kind == "subagent_tokens"
    assert budget.used["agent"] == 0
    budget.call(model, "agent", GO)
    assert budget.used["agent"] > 0


# 14
def test_never_past_the_cap():
    cfg = config.load(overrides={"limits": {"subagent_tokens": 20_000}})
    step = lambda messages, tools, rng: {"text": "x" * rng.randint(0, 30_000)}
    model = FakeModel(cfg, {}, seed=3, defaults={"subagent": step})
    budget = CallBudget(cfg, CycleBudget(cfg), "a1")
    for _ in range(50):
        try:
            budget.call(model, "subagent", GO, scope="subagent")
        except CapReached:
            break
        assert budget.used["subagent"] <= 20_000
    assert budget.used["subagent"] <= 20_000


# 15
def test_cycle_stops_at_5_usd():
    cfg, model, cycle = setup({"budget": {"cycle_usd": 5.0}})   # the numbers below are for a $5 cap
    big = [{"role": "user", "content": "y" * 400_000}]
    for _ in range(10):
        cycle.call(model, "orchestrator", big, max_output_tokens=4_000)
    assert cycle.spent_usd == pytest.approx(4.80032)
    with pytest.raises(CapReached) as err:
        cycle.call(model, "orchestrator", big, max_output_tokens=4_000)
    assert err.value.kind == "cycle_usd"
    assert cycle.spent_usd <= 5.0
    cycle.new_cycle()
    assert cycle.spent_usd == 0 and cycle.cycle == 2
    assert {"event": "cycle_end", "cycle": 1}.items() <= cycle.events[-1].items()
    assert cycle.events[-1]["spent_usd"] == pytest.approx(4.80032)
    cycle.call(model, "orchestrator", big, max_output_tokens=4_000)


# 16
def test_charging_matches_replies():
    cfg, model, cycle = setup(step={"text": "abc" * 100})
    budget = CallBudget(cfg, cycle, "a1")
    replies = [budget.call(model, "agent", GO),
               budget.call(model, "subagent", GO, scope="subagent"),
               cycle.call(model, "orchestrator", GO)]
    assert abs(cycle.spent_usd - sum(r["cost_usd"] for r in replies)) < 1e-12


# 18
@pytest.mark.parametrize("bad", [0, -5])
def test_cycle_call_refuses_bad_output_limit(bad):
    cfg, model, cycle = setup()
    with pytest.raises(ValueError):
        cycle.call(model, "orchestrator", GO, max_output_tokens=bad)
    assert model.calls == [] and cycle.spent_usd == 0


# 22
def test_failed_call_logged_and_counted():
    from apex.llm import LLMError
    cfg = config.load()
    cycle = CycleBudget(cfg)
    budget = CallBudget(cfg, cycle, "a1")

    def broken(role, messages, **kw):
        raise LLMError("server down")

    with pytest.raises(LLMError):
        budget.call(broken, "agent", GO)
    assert budget.turns == 1 and budget.used["agent"] == 0 and cycle.spent_usd == 0
    assert cycle.events[-1]["event"] == "call_failed" and cycle.events[-1]["agent_id"] == "a1"
    assert "server down" in cycle.events[-1]["error"]


# 23
def test_estimate_too_low_is_logged():
    step = {"text": "x", "usage": {"input_tokens": 99_999, "output_tokens": 1}}
    cfg, model, cycle = setup(step=step)
    CallBudget(cfg, cycle, "a1").call(model, "agent", GO)
    assert cycle.events[-1] == {"event": "estimate_low", "role": "agent", "agent_id": "a1", "est": 9,
                                "actual": 99_999}
