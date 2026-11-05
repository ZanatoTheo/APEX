"""run_script under bwrap: own folder only, no network, no env, timeout, output cap."""
import shutil
import signal
import subprocess
import time
import uuid
from pathlib import Path

import pytest

from apex import config
from apex.tools import sandbox
from apex.tools.files import ToolError
from apex.tools.sandbox import SandboxUnavailable, run_script

PRODUCT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "ws"
    r.mkdir()
    return r


def run(root, code, overrides=None, **kw):
    (root / "s.py").write_text(code)
    return run_script(root, config.load(overrides=overrides), "s.py", **kw)


# 9
def test_runs_and_writes_back(root):
    out = run(root, 'import os\nprint(os.getcwd())\nopen("out.txt", "w").write("hi")\n')
    assert out["exit_code"] == 0 and out["timed_out"] is False
    assert out["stdout"] == "/work\n"
    assert (root / "out.txt").read_text() == "hi"


# 10
def test_no_network(root):
    code = ('import socket\ntry:\n    socket.create_connection(("1.1.1.1", 80), timeout=2)\n    print("reachable")\n'
            'except OSError:\n    print("blocked")\n')
    assert run(root, code)["stdout"] == "blocked\n"


# 11
def test_host_files_hidden(root, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("future data")
    plan = PRODUCT_ROOT / "README.md"
    assert secret.exists() and plan.exists()
    out = run(root, f'import os\nprint(os.path.exists({str(secret)!r}), os.path.exists({str(plan)!r}))\n')
    assert out["stdout"] == "False False\n"


# 12
def test_no_api_key(root, monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "sk-should-not-leak")
    out = run(root, "import os\nprint(sorted(os.environ))\n")
    assert "MODEL_API_KEY" not in out["stdout"] and "sk-should-not-leak" not in out["stdout"]


# 13
def test_timeout_kills_everything(root):
    marker = f"apex-t13-{uuid.uuid4().hex}"
    start = time.monotonic()
    out = run(root, "while True:\n    pass\n", {"tools": {"script_timeout_s": 2}}, args=(marker,))
    assert out["timed_out"] is True and out["exit_code"] is None
    assert time.monotonic() - start < 6
    time.sleep(0.2)
    assert subprocess.run(["pgrep", "-f", marker], capture_output=True).returncode == 1


# 14
def test_output_limit(root):
    out = run(root, 'print("x" * 100_000)\n', {"tools": {"script_output_chars": 1000}})
    assert out["stdout"] == "x" * 1000 + "\n… [99001 more bytes cut]"


# 15
def test_numpy_pandas(root):
    code = "import numpy as np, pandas as pd\nprint(int(np.arange(10).sum()), len(pd.DataFrame({'a': [1, 2]})))\n"
    out = run(root, code)
    assert out["stdout"] == "45 2\n", out["stderr"]


# 16
def test_read_only_extra_file(root, tmp_path):
    host = tmp_path / "h.json"
    host.write_text('{"x": 1}')
    code = ('import json\nprint(json.load(open("/data/h.json"))["x"])\ntry:\n    open("/data/h.json", "w")\n'
            'except OSError:\n    print("ro")\n')
    assert run(root, code, ro_files={"/data/h.json": host})["stdout"] == "1\nro\n"


# 17
def test_bad_script_path(root, monkeypatch):
    def no_popen(*a, **kw):
        raise AssertionError("Popen must not be called")

    monkeypatch.setattr(subprocess, "Popen", no_popen)
    (root / "notes.md").write_text("x")
    cfg = config.load()
    for bad in ("../x.py", "notes.md"):
        with pytest.raises(ToolError):
            run_script(root, cfg, bad)


# 18
def test_no_bwrap(root, monkeypatch):
    (root / "s.py").write_text("print(1)\n")
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: None)
    with pytest.raises(SandboxUnavailable, match="bubblewrap"):
        run_script(root, config.load(), "s.py")


# 28
def test_fifo_refused_by_host_tools(root):
    from apex.tools.files import Workspace
    run(root, 'import os\nos.mkfifo("pipe")\n')
    ws = Workspace(root, config.load())
    start = time.monotonic()
    for action in (lambda: ws.write("pipe", "x"), lambda: ws.read("pipe"), lambda: ws.edit("pipe", "a", "b")):
        with pytest.raises(ToolError, match="regular file"):
            action()
    ws.delete("pipe")
    assert not (root / "pipe").exists() and time.monotonic() - start < 2


# 29
def test_output_flood_is_bounded(root):
    import resource
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    start = time.monotonic()
    out = run(root, 'import sys\nwhile True:\n    sys.stdout.write("x" * 1_000_000)\n',
              {"tools": {"script_timeout_s": 3}})
    assert time.monotonic() - start < 8
    assert len(out["stdout"]) < 9_000 and "more" in out["stdout"]
    grown_mb = (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before) / 1024
    assert grown_mb < 300


# 30
def test_script_cannot_forge_log(root):
    (root / "log.jsonl").write_text("original\n")
    code = ('import os\nfor act in (lambda: open("log.jsonl", "w").write("forged"), '
            'lambda: os.link("log.jsonl", "alias.txt"), lambda: os.remove("log.jsonl")):\n'
            '    try:\n        act()\n        print("done")\n    except OSError:\n        print("refused")\n')
    assert run(root, code)["stdout"] == "refused\nrefused\nrefused\n"
    assert (root / "log.jsonl").read_text() == "original\n" and not (root / "alias.txt").exists()


# 35
def test_dash_named_script(root):
    (root / "-x.py").write_text('print("ok")\n')
    assert run_script(root, config.load(), "-x.py")["stdout"] == "ok\n"


# 36
def test_size_limits(root):
    (root / "big.bin").write_bytes(b"0" * 2_000_000)
    (root / "s.py").write_text("print(1)\n")
    with pytest.raises(ToolError, match="folder"):
        run_script(root, config.load(overrides={"tools": {"max_folder_mb": 1}}), "s.py")
    (root / "big.bin").unlink()
    run(root, 'f = open("w.bin", "wb")\nfor _ in range(3):\n    f.write(b"0" * 1_000_000)\n',
        {"tools": {"script_file_mb": 1}})
    assert (root / "w.bin").stat().st_size <= 1_048_576


# ---- Session, an interactive sandboxed run over pipes -----------------
def session_entry(tmp_path, code):
    host = tmp_path / "entry.py"
    host.write_text(code)
    return {"/opt/t/entry.py": host}


def test_session_echo(root, tmp_path):
    ro = session_entry(tmp_path, 'import sys, json\nfor line in sys.stdin:\n'
                                 '    print(json.dumps({"echo": json.loads(line)}), flush=True)\n')
    s = sandbox.Session(root, config.load(), "/opt/t/entry.py", ro)
    assert [s.ask({"n": i}) for i in range(3)] == [{"echo": {"n": i}} for i in range(3)]
    out = s.close()
    assert out["exit_code"] == 0 and out["timed_out"] is False


def test_session_deadline(root, tmp_path):
    ro = session_entry(tmp_path, 'import time\ntime.sleep(10)\n')
    s = sandbox.Session(root, config.load(overrides={"tools": {"script_timeout_s": 2}}), "/opt/t/entry.py", ro)
    t0 = time.monotonic()
    assert s.ask({"x": 1}) is None and "deadline" in s.error
    assert s.ask({"x": 2}) is None                                       # dead after the first None
    assert s.close()["timed_out"] is True and time.monotonic() - t0 < 6


def test_session_stderr_capped_and_entry_checked(root, tmp_path):
    ro = session_entry(tmp_path, 'import sys\nsys.stderr.write("e" * 100000)\nprint("{\\"ok\\": 1}", flush=True)\n'
                                 'sys.stdin.readline()\n')
    s = sandbox.Session(root, config.load(), "/opt/t/entry.py", ro)
    assert s.ask({}) == {"ok": 1}
    assert len(s.close()["stderr"]) <= config.load()["tools"]["script_output_chars"] + 200
    with pytest.raises(ValueError):
        sandbox.Session(root, config.load(), "/work/entry.py", ro)
    with pytest.raises(ValueError):
        sandbox.Session(root, config.load(), "/opt/t/other.py", ro)


def test_session_write_respects_the_deadline(root, tmp_path):
    ro = session_entry(tmp_path, 'import sys, time\nsys.stdout.write("x" * 300000)\nsys.stdout.flush()\n'
                                 'time.sleep(30)\n')
    s = sandbox.Session(root, config.load(overrides={"tools": {"script_timeout_s": 3}}), "/opt/t/entry.py", ro)

    def stuck(*_):
        s.proc.kill()
        raise AssertionError("ask() blocked past its deadline")
    old = signal.signal(signal.SIGALRM, stuck)
    signal.alarm(15)                                                    # a hang fails the test, it doesn't hang it
    try:
        t0 = time.monotonic()
        assert s.ask({"pad": "y" * 2_000_000}) is None                 # the entry never reads stdin
        assert time.monotonic() - t0 < 8 and s.close()["timed_out"] is True
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def test_session_refuses_an_oversized_folder(root, tmp_path):
    ro = session_entry(tmp_path, 'print("{}")\n')
    (root / "big.bin").write_bytes(b"0" * (2 * 1024 * 1024))
    with pytest.raises(ToolError):
        sandbox.Session(root, config.load(overrides={"tools": {"max_folder_mb": 1}}), "/opt/t/entry.py", ro)
