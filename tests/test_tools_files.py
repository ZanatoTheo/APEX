"""Workspace file tools stay inside the agent's folder."""
import os

import pytest

from apex import config
from apex.tools.files import ToolError, Workspace


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    return Workspace(root, config.load())


# 1
def test_round_trip(ws):
    ws.write("a/b.py", "x=1")
    assert ws.read("a/b.py") == "x=1"
    assert (ws.root / "a").is_dir()


# 2
def test_edit(ws):
    ws.write("f.py", "x=1")
    ws.edit("f.py", "x=1", "x=2")
    assert ws.read("f.py") == "x=2"
    with pytest.raises(ToolError, match="not found"):
        ws.edit("f.py", "y", "z")
    ws.write("g.txt", "a a")
    with pytest.raises(ToolError, match="2 times"):
        ws.edit("g.txt", "a", "b")


# 3
def test_delete(ws):
    ws.write("f.py", "1")
    ws.delete("f.py")
    assert not (ws.root / "f.py").exists()
    with pytest.raises(ToolError):
        ws.delete("f.py")
    ws.write("d/f", "1")
    with pytest.raises(ToolError, match="folder"):
        ws.delete("d")


# 4
def test_list(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    ws = Workspace(root, config.load())
    for name in ("b.py", "a.txt", "c/d.md"):
        ws.write(name, "xy")
    assert ws.list() == "a.txt (2 bytes)\nb.py (2 bytes)\nc/d.md (2 bytes)"
    small = Workspace(root, config.load(overrides={"tools": {"max_list_entries": 2}}))
    assert small.list() == "a.txt (2 bytes)\nb.py (2 bytes)\n… 1 more"


# 5
@pytest.mark.parametrize("bad", ["../x", "/etc/passwd", "a/../../x", ""])
def test_no_escape(ws, tmp_path, bad):
    with pytest.raises(ToolError):
        ws.write(bad, "x")
    assert sorted(os.listdir(tmp_path)) == ["ws"]


# 6
def test_symlink_out(ws, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "s.txt").write_text("secret")
    (ws.root / "link").symlink_to(outside)
    with pytest.raises(ToolError):
        ws.read("link/s.txt")
    with pytest.raises(ToolError):
        ws.write("link/new.txt", "x")
    assert not (outside / "new.txt").exists()


# 7
def test_protected(ws):
    (ws.root / "log.jsonl").write_text('{"a": 1}\n')
    assert ws.read("log.jsonl") == '{"a": 1}\n'
    for action in (lambda: ws.write("log.jsonl", "x"), lambda: ws.edit("log.jsonl", "a", "b"),
                   lambda: ws.delete("log.jsonl")):
        with pytest.raises(ToolError, match="read-only"):
            action()


# 8
def test_limits(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    ws = Workspace(root, config.load(overrides={"tools": {"max_file_chars": 10, "max_read_chars": 5}}))
    with pytest.raises(ToolError):
        ws.write("f.txt", "x" * 11)
    (root / "big.txt").write_text("x" * 12)
    assert ws.read("big.txt") == "xxxxx\n… [7 more chars cut]"


# 31
def test_host_refuses_hard_linked_files(ws):
    ws.write("a.txt", "one")
    os.link(ws.root / "a.txt", ws.root / "b.txt")
    with pytest.raises(ToolError, match="hard links"):
        ws.write("b.txt", "two")
    assert (ws.root / "a.txt").read_text() == "one"


# 33
def test_big_file(ws, monkeypatch):
    (ws.root / "big.txt").write_bytes(b"x" * 10_000_000)
    out = ws.read("big.txt")
    assert out.startswith("x" * 50_000) and out.endswith("more bytes cut]")
    with pytest.raises(ToolError, match="too large"):
        ws.edit("big.txt", "x", "y")
    from pathlib import Path as P
    monkeypatch.setattr(P, "read_text", lambda *a, **k: (_ for _ in ()).throw(AssertionError("read")))
    assert "big.txt (10000000 bytes)" in ws.list()


# 34
def test_delete_symlink_not_target(ws, tmp_path):
    ws.write("real.txt", "keep")
    (ws.root / "inlink").symlink_to(ws.root / "real.txt")
    ws.delete("inlink")
    assert not os.path.lexists(ws.root / "inlink") and (ws.root / "real.txt").read_text() == "keep"
    outside = tmp_path / "outside.txt"
    outside.write_text("keep too")
    (ws.root / "outlink").symlink_to(outside)
    ws.delete("outlink")
    assert not os.path.lexists(ws.root / "outlink") and outside.read_text() == "keep too"
