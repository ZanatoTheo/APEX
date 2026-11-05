"""The test year in the run config, task.settings.
Fake model and the small price fixture (years 2021, 2022, 2024, 2025) only: no real API call."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from apex import config

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"
CSV, ASSETS = FIX / "prices_small.csv", FIX / "assets_small.json"


def start(tmp_path, settings=None, extra=()):
    cfg = {"operation": {"agents": 3}}
    if settings is not None:
        cfg["task"] = {"settings": settings}
    small = tmp_path / "cfg.json"
    small.write_text(json.dumps(cfg))
    return subprocess.run([sys.executable, "environment/start.py", "--csv", str(CSV), "--assets", str(ASSETS),
                           "--time-gap", "7", "--seed", "5", "--build-out", str(tmp_path / "data"), "--fake",
                           "--max-cycles", "1", "--skip-holdout", "--config", str(small),
                           "--out", str(tmp_path / "runs"), *extra],
                          cwd=ROOT, capture_output=True, text=True, timeout=260)


def no_run(tmp_path):
    runs = tmp_path / "runs"
    return not runs.exists() or not any(runs.iterdir())


# 1
def test_settings_default_and_type(tmp_path):
    assert config.load()["task"]["settings"] == {}
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"task": {"settings": {"year": 2022, "anything": [1]}}}))
    assert config.load(p)["task"]["settings"] == {"year": 2022, "anything": [1]}
    p.write_text(json.dumps({"task": {"settings": "2022"}}))
    with pytest.raises(config.ConfigError):
        config.load(p)


# 2
def test_year_2022_end_to_end(tmp_path):
    p = start(tmp_path, {"year": 2022, "holdout_year": None})
    assert p.returncode == 0, p.stderr[-2000:]
    f = tmp_path / "data" / "chunks_2022_gap7.json"
    d = json.loads(f.read_text())
    days = [x["date"] for s in d["steps"] for x in s["days"]]
    assert days and all(x.startswith("2022-") for x in days)
    assert any(x["date"].startswith("2021-") for x in d["history"])


# 3
def test_defaults():
    from environment import start as st
    assert st.years({}, None) == (2025, 2022)


# 4
def test_holdout_not_before_year(tmp_path):
    p = start(tmp_path, {"year": 2022})
    assert p.returncode == 2 and "holdout_year" in p.stderr
    assert no_run(tmp_path)


# 5
@pytest.mark.parametrize("year", ["2022", True, 2030])
def test_bad_year(tmp_path, year):
    p = start(tmp_path, {"year": year, "holdout_year": None})
    assert p.returncode == 2 and "error" in p.stderr
    assert no_run(tmp_path)


# 6
def test_flag_beats_settings():
    from environment import start as st
    assert st.years({"year": 2022, "holdout_year": 2021}, "none") == (2022, None)
    assert st.years({"year": 2022, "holdout_year": 2021}, None) == (2022, 2021)


# 7 (review): a bad flag names the flag, not the config
@pytest.mark.parametrize("flag", ["2026", "abc"])
def test_bad_flag_names_the_flag(flag):
    from environment import start as st
    with pytest.raises(ValueError, match="--holdout-year"):
        st.years({"year": 2025}, flag)
