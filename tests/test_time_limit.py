"""operation.max_minutes: a run ends between agent steps, never inside one. Toy connector, demo model, fake clock.
No real API call."""
import json
from pathlib import Path

import pytest

from apex import config
from apex.fake_run import demo_model
from apex.operation import Operation
from tests.fixtures.toy_connector import ToyConnector


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class TimedToy(ToyConnector):
    """Each run_step call (one agent's report on one step) moves the clock by minutes(n) fake minutes."""

    def __init__(self, cfg, clock, minutes):
        super().__init__(cfg)
        self.clock, self.minutes, self.n = clock, minutes, 0

    def run_step(self, agent_id, agent_dir, step):
        self.clock.t += 60 * self.minutes(self.n)
        self.n += 1
        return super().run_step(agent_id, agent_dir, step)


def run_timed(tmp_path, max_minutes, minutes=lambda n: 1, max_cycles=3, loops=2, name="run"):
    cfg = config.load(overrides={"operation": {"agents": 3, "max_loops": loops, "max_cycles": max_cycles,
                                               "max_minutes": max_minutes}})
    clock = Clock()
    model = demo_model(cfg)
    op = Operation(cfg, TimedToy(cfg, clock, minutes), model, tmp_path / name, clock=clock)
    return op, model, op.run()


def events(run_dir, kind):
    rows = [json.loads(line) for line in (Path(run_dir) / "log.jsonl").read_text().splitlines()]
    return [r for r in rows if r["event"] == kind]


def agent_calls(model):
    return sum(1 for c in model.calls if c["role"] == "agent")


# 1
def test_no_limit_runs_as_before(tmp_path):
    op, _, result = run_timed(tmp_path, None, max_cycles=1)
    assert result["reason"] == "max_cycles" and result["cycles"] == 1
    assert events(op.run_dir, "run_start")[0]["max_minutes"] is None


# 2
def test_cycle_end_projection_stops_with_final_pick(tmp_path):
    op, _, result = run_timed(tmp_path, 20)
    assert result["reason"] == "time_limit" and result["cycles"] == 1
    assert result["fallback"] is False
    assert events(op.run_dir, "generation") == []
    assert events(op.run_dir, "run_start")[0]["max_minutes"] == 20
    assert json.loads((op.run_dir / "final.json").read_text())["reason"] == "time_limit"


# 3
def test_mid_cycle_stop_uses_fallback(tmp_path):
    _, base_model, _ = run_timed(tmp_path, None, max_cycles=1, name="base")
    op, model, result = run_timed(tmp_path, 30, minutes=lambda n: 1 if n < 12 else 10)
    assert result["reason"] == "time_limit" and result["cycles"] == 2
    assert result["fallback"] is True and result["selected"]
    assert len(events(op.run_dir, "step")) == 4
    assert len(events(op.run_dir, "generation")) == 1
    assert agent_calls(model) == agent_calls(base_model)
    assert events(op.run_dir, "stop")[-1]["reason"] == "time_limit"


# 4
def test_time_up_before_any_cycle(tmp_path):
    op, _, result = run_timed(tmp_path, 1)
    assert result["reason"] == "time_limit" and result["cycles"] == 1
    assert result["selected"] is None and result["why"] == "fallback: no agent was scored"
    assert events(op.run_dir, "step") == []
    assert (op.run_dir / "final.json").exists()


# 5
def test_max_minutes_accepted():
    assert config.load(overrides={"operation": {"max_minutes": 80}})["operation"]["max_minutes"] == 80
    assert config.load()["operation"]["max_minutes"] is None


@pytest.mark.parametrize("bad", [0, -5, 1.5, "80", True])
def test_max_minutes_refused(bad):
    with pytest.raises(config.ConfigError):
        config.load(overrides={"operation": {"max_minutes": bad}})


class TimedModel:
    """The demo model, but each `role` call moves the clock by `minutes` fake minutes (a slow generation)."""

    def __init__(self, inner, clock, role, minutes):
        self.inner, self.clock, self.role, self.minutes = inner, clock, role, minutes
        self.calls = inner.calls

    def __call__(self, role, messages, **kw):
        if role == self.role:
            self.clock.t += 60 * self.minutes
        return self.inner(role, messages, **kw)


# 6 (review): the cycle-end check counts the generation that comes before the next cycle
def test_projection_counts_the_generation(tmp_path):
    cfg = config.load(overrides={"operation": {"agents": 3, "max_loops": 2, "max_cycles": 3, "max_minutes": 50}})
    clock = Clock()
    model = TimedModel(demo_model(cfg), clock, "mutation", 10)
    op = Operation(cfg, TimedToy(cfg, clock, lambda n: 1), model, tmp_path / "run", clock=clock)
    result = op.run()
    gen_minutes = 10 * sum(1 for c in model.calls if c["role"] == "mutation")
    assert gen_minutes >= 10
    # cycle 1 ends at 12 (12 + 12 <= 50); the generation; cycle 2 ends at 24 + gen. From cycle 1's end to cycle 2's
    # end is 12 + gen, so the next cycle would end past 50: stop at cycle 2's end, with the normal final pick.
    assert result["reason"] == "time_limit" and result["cycles"] == 2
    assert result["fallback"] is False
    assert len(events(op.run_dir, "cycle_end")) == 2
