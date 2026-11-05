"""Connector interface, loader and the toy task."""
import json
import types

import pytest

from apex import config
from apex.connector import REQUIRED_METHODS, ConnectorError, check_connector, load_connector
from tests.fixtures.toy_connector import SECRET, ToyConnector


@pytest.fixture
def cfg():
    return config.load()


def values_tool(conn, tmp_path, step):
    (tool,) = conn.tools("a", tmp_path, step)
    assert tool.name == "read_values"
    return tool.handler({})


# 1
def test_checker(cfg):
    toy = ToyConnector(cfg)
    check_connector(toy)
    partial = types.SimpleNamespace(**{m: getattr(toy, m) for m in REQUIRED_METHODS if m != "cycle_score"})
    with pytest.raises(ConnectorError, match="cycle_score"):
        check_connector(partial)
    not_callable = types.SimpleNamespace(**{m: getattr(toy, m) for m in REQUIRED_METHODS})
    not_callable.brief = "text"
    with pytest.raises(ConnectorError, match="brief"):
        check_connector(not_callable)


# 2
def test_loader(cfg):
    assert isinstance(load_connector("tests.fixtures.toy_connector", cfg), ToyConnector)
    with pytest.raises(ConnectorError, match="make_connector"):
        load_connector("json", cfg)
    with pytest.raises(ConnectorError):
        load_connector("no.such.module", cfg)
    with pytest.raises(ConnectorError):
        load_connector("", cfg)


# 3
def test_release_gates(cfg, tmp_path):
    conn = ToyConnector(cfg)
    assert SECRET not in conn.brief()
    conn.release(2)
    assert [r["value"] for r in json.loads(values_tool(conn, tmp_path, 2))] == [3, 5, 4]
    assert SECRET not in values_tool(conn, tmp_path, 2)
    conn.release(7)
    assert SECRET in values_tool(conn, tmp_path, 7)
    conn.release(0)                                     # wrap-around moves the clock back
    assert SECRET not in values_tool(conn, tmp_path, 0)
    with pytest.raises(ConnectorError):
        conn.release(8)


# 4
def test_scoring(cfg, tmp_path):
    conn = ToyConnector(cfg)
    (tmp_path / "answer.py").write_text("ANSWER = 6\n")
    conn.begin_cycle(["a"])
    for step in (0, 1):
        conn.release(step)
        conn.run_step("a", tmp_path, step)
    assert conn.cycle_score("a") == -4
    (tmp_path / "answer.py").write_text("nothing")
    conn.release(2)
    assert conn.run_step("a", tmp_path, 2) == {"step": 2, "answer": None, "score": -10.0}
    assert conn.cycle_score("a") == -14
    conn.begin_cycle(["a"])
    assert conn.cycle_score("a") == 0


# 5
def test_unreleased_step_refused(cfg, tmp_path):
    conn = ToyConnector(cfg)
    conn.release(1)
    with pytest.raises(ConnectorError):
        conn.run_step("a", tmp_path, 2)


# 1b (review): a tool built at one step never shows later steps, even after a later release
def test_stale_tool_handler_stays_gated(cfg, tmp_path):
    conn = ToyConnector(cfg)
    conn.release(2)
    (tool,) = conn.tools("a", tmp_path, 2)
    conn.release(7)
    out = tool.handler({})
    assert SECRET not in out and len(json.loads(out)) == 3


# 2b (review): any error while importing or making a connector becomes ConnectorError
def test_loader_wraps_any_error(cfg, tmp_path, monkeypatch):
    (tmp_path / "broken_conn.py").write_text("def oops(:\n")
    (tmp_path / "raising_conn.py").write_text("def make_connector(cfg, data=None):\n    raise RuntimeError('no data')\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    with pytest.raises(ConnectorError, match="broken_conn"):
        load_connector("broken_conn", cfg)
    with pytest.raises(ConnectorError, match="no data"):
        load_connector("raising_conn", cfg)


# 4b (review): a huge or non-finite answer counts as no answer
def test_non_finite_answer(cfg, tmp_path):
    conn = ToyConnector(cfg)
    conn.begin_cycle(["a"])
    conn.release(0)
    (tmp_path / "answer.py").write_text("ANSWER = " + "9" * 400 + "\n")
    assert conn.run_step("a", tmp_path, 0)["score"] == -10.0


# ---- the optional script_files() ------------------------------------------------------------------------------
class FilesToy(ToyConnector):
    def __init__(self, cfg, files):
        super().__init__(cfg)
        self.files = files

    def script_files(self, agent_id, step):
        return self.files


def test_script_files_helper(tmp_path):
    from apex.connector import script_files
    cfg = config.load()
    good = tmp_path / "hello.txt"
    good.write_text("hi")
    assert script_files(ToyConnector(cfg), "a", 0) == {}
    assert script_files(FilesToy(cfg, {"/data/hello.txt": good}), "a", 0) == {"/data/hello.txt": str(good)}
    for bad in ({"/work/x": good}, {"/data/x": tmp_path / "missing"}, {"data/x": good}, "x", {"/data/d": tmp_path}):
        with pytest.raises(ConnectorError):
            script_files(FilesToy(cfg, bad), "a", 0)
