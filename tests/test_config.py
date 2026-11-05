"""Config loading and the .env parser."""
import os
from pathlib import Path

import pytest

from apex import config, envfile

ROOT = Path(__file__).resolve().parent.parent


# 15
def test_defaults_and_default_json_load():
    for cfg in (config.load(), config.load(ROOT / "configs" / "default.json")):   # every role on contributor
        assert {r["model_id"] for r in cfg["models"]["roles"].values()} == {"muse-spark-1.3-contributor"}


# 16
def test_unknown_key_refused():
    with pytest.raises(config.ConfigError, match=r"models\.retry"):
        config.load(overrides={"models": {"retry": 1}})


# 17
def test_role_without_pricing_refused():
    with pytest.raises(config.ConfigError, match="x-1"):
        config.load(overrides={"models": {"roles": {"agent": {"model_id": "x-1"}}}})


# 18
def test_base_url_checked():
    with pytest.raises(config.ConfigError, match="base_url"):
        config.load(overrides={"models": {"base_url": "http://example.com"}})
    assert config.load(overrides={"models": {"base_url": "http://127.0.0.1:8000/v1"}})


# 19
def test_envfile(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_bytes(b'export A="x y"\r\nB=v #c\nC=v#c\n# comment\nD=\n')
    assert envfile.read(path) == {"A": "x y", "B": "v", "C": "v#c", "D": ""}
    env = {"B": "shell"}                      # a private copy, so A and C don't leak into other tests
    monkeypatch.setattr(os, "environ", env)
    assert sorted(envfile.load(path)) == ["A", "C"]
    assert env["B"] == "shell" and env["A"] == "x y"


# 26
def test_fractional_backoff_accepted():
    assert config.load(overrides={"models": {"retry_backoff_s": 0.5}})["models"]["retry_backoff_s"] == 0.5


# P2-17
def test_limits_and_budget():
    cfg = config.load()
    assert cfg["limits"]["call_tokens"] == 18_000 and cfg["budget"]["cycle_usd"] == 2.5   # the defaults
    with pytest.raises(config.ConfigError):
        config.load(overrides={"limits": {"min_output_tokens": 5000}})
    with pytest.raises(config.ConfigError):
        config.load(overrides={"budget": {"cycle_usd": 0.0}})


# P2-19
@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_non_finite_numbers_refused(bad):
    with pytest.raises(config.ConfigError):
        config.load(overrides={"budget": {"cycle_usd": bad}})
    with pytest.raises(config.ConfigError):
        config.load(overrides={"pricing": {"muse-wonder-1.0": {"input": 4.0, "cached_input": 0.2, "output": bad}}})


def test_cached_rate_above_input_refused():
    with pytest.raises(config.ConfigError, match="cached_input"):
        config.load(overrides={"pricing": {"muse-wonder-1.0": {"input": 1.0, "cached_input": 2.0, "output": 20.0}}})


# P3-27
def test_tools_section():
    assert config.load()["tools"]["script_timeout_s"] == 60
    with pytest.raises(config.ConfigError):
        config.load(overrides={"tools": {"script_timeout_s": 0}})


# P6-10: operation section checks
@pytest.mark.parametrize("bad", [
    {"survivors": 10}, {"agents": 0}, {"base_margin": -0.1}, {"base_margin": float("nan")},
    {"axes": []}, {"axes": ["a", "a"]}, {"axes": [""]}, {"axes": "a"},
])
def test_operation_checks(bad):
    with pytest.raises(config.ConfigError):
        config.load(overrides={"operation": bad})


# P9-12: cleaner section checks
@pytest.mark.parametrize("bad", [{"dense_share": 0}, {"dense_share": 1.5}, {"dense_share": float("nan")},
                                 {"files_chars": 0}])
def test_cleaner_checks(bad):
    with pytest.raises(config.ConfigError):
        config.load(overrides={"cleaner": bad})


def test_cleaner_defaults_load():
    assert config.load()["cleaner"] == {"files_chars": 60000, "output_tokens": 4000, "dense_share": 0.3,
                                        "max_matches_per_file": 100}
