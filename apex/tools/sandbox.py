"""run_script: run an agent's Python file under bwrap (bubblewrap).

Inside the sandbox the script sees only:
- its own folder, writable, at /work (its protected files read-only);
- /usr and the venv, read-only;
- any extra read-only files the caller passes (`ro_files`);
- a small in-memory /tmp.

It has no network, an empty environment (so no API key), and limits on memory, on each file it writes (stdout
and stderr included), and on time. The rest of the host does not exist for it, including the full data file,
other agents' folders and Eval's notes. Its output goes to capped temp files, of which only the head is read back.

Session runs a read-only entry script (outside /work) under the same sandbox, talking JSON lines over
stdin/stdout with one deadline: a connector can hand a script its inputs one at a time.
"""
import json
import os
import resource
import select
import time
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .files import ToolError, Workspace, folder_bytes, read_head


class SandboxUnavailable(Exception):
    """bwrap is missing: scripts refuse to run rather than run half-sandboxed."""


_ENV = {"PATH": "/usr/bin:/bin", "HOME": "/work", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
        "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1"}
_MB = 1024 * 1024


def _command(bwrap: str, ws: Workspace, entry: str, args, ro_files: dict, tmp_mb: int) -> list[str]:
    venv = Path(sys.prefix)
    root = ws.root.resolve()
    cmd = [bwrap, "--unshare-all", "--die-with-parent", "--new-session", "--clearenv"]
    for key, value in _ENV.items():
        cmd += ["--setenv", key, value]
    cmd += ["--ro-bind", "/usr", "/usr", "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
            "--symlink", "usr/bin", "/bin"]
    if not str(venv).startswith("/usr/"):
        cmd += ["--ro-bind", str(venv), str(venv)]
    cmd += ["--proc", "/proc", "--dev", "/dev", "--size", str(tmp_mb * _MB), "--tmpfs", "/tmp",
            "--bind", str(root), "/work"]
    for name in sorted(ws.protected):                 # read-only inside too: no rewrite, no hard link, no delete
        host = root / name
        if host.is_file() and not host.is_symlink():
            cmd += ["--ro-bind", str(host), f"/work/{name}"]
    for inside, host in ro_files.items():
        cmd += ["--ro-bind", str(host), inside]
    cmd += ["--chdir", "/work", str(venv / "bin" / "python"), "-s", entry, *[str(a) for a in args]]
    return cmd


def run_script(root, cfg: dict, path: str, args=(), ro_files: dict | None = None) -> dict:
    """Run `path` (a .py file in the agent's folder). Returns {exit_code, stdout, stderr, timed_out}."""
    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise SandboxUnavailable("bwrap (bubblewrap) is required to run agent scripts: install the 'bubblewrap' "
                                 "package")
    lim = cfg["tools"]
    ws = Workspace(root, cfg)
    p = ws._resolve(path)
    if p.suffix != ".py":
        raise ToolError(f"{path} is not a .py file")
    ws._existing_regular(p, path, changing=False)
    used = folder_bytes(ws.root.resolve())
    if used > lim["max_folder_mb"] * _MB:
        raise ToolError(f"your folder holds {used // _MB} MB; the limit is {lim['max_folder_mb']} MB. "
                        "Delete files before running scripts.")
    ro_files = dict(ro_files or {})
    for inside, host in ro_files.items():
        if not inside.startswith("/") or inside.startswith("/work") or not Path(host).is_file():
            raise ValueError(f"ro_files needs an absolute sandbox path outside /work and an existing host file: "
                             f"{inside} → {host}")

    memory, file_size = lim["script_memory_mb"] * _MB, lim["script_file_mb"] * _MB

    def limits():
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        resource.setrlimit(resource.RLIMIT_FSIZE, (file_size, file_size))   # caps stdout/stderr files too

    cmd = _command(bwrap, ws, f"./{ws._rel(p)}", args, ro_files, lim["script_tmp_mb"])
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=err, preexec_fn=limits)
        timed_out = False
        try:
            proc.wait(timeout=lim["script_timeout_s"])
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()                  # bwrap dies; --die-with-parent takes the script with it
            proc.wait()
        heads = []
        for f in (out, err):
            f.seek(0)
            heads.append(read_head(f.fileno(), lim["script_output_chars"]))
    return {"exit_code": None if timed_out else proc.returncode, "stdout": heads[0], "stderr": heads[1],
            "timed_out": timed_out}


_LINE_MAX = 1024 * 1024


class Session:
    """A sandboxed script that answers JSON lines: ask(obj) sends one line and reads one back. One deadline
    (tools.script_timeout_s) covers the whole session. After the first failed ask, the session is dead."""

    def __init__(self, root, cfg: dict, entry: str, ro_files: dict, args=()):
        bwrap = shutil.which("bwrap")
        if not bwrap:
            raise SandboxUnavailable("bwrap (bubblewrap) is required to run agent scripts")
        ro_files = {k: str(v) for k, v in dict(ro_files).items()}
        if entry not in ro_files or not entry.startswith("/") or entry == "/work" or entry.startswith("/work/"):
            raise ValueError(f"the entry {entry} must be one of ro_files, outside /work")
        for inside, host in ro_files.items():
            if not inside.startswith("/") or inside.startswith("/work") or not Path(host).is_file():
                raise ValueError(f"ro_files needs an absolute sandbox path outside /work and an existing host file: "
                                 f"{inside} → {host}")
        lim = cfg["tools"]
        ws = Workspace(root, cfg)
        used = folder_bytes(ws.root.resolve())
        if used > lim["max_folder_mb"] * _MB:
            raise ToolError(f"the folder holds {used // _MB} MB; the limit is {lim['max_folder_mb']} MB")
        self.cfg, self.error, self.timed_out = cfg, None, False
        self.deadline = time.monotonic() + lim["script_timeout_s"]
        memory, file_size = lim["script_memory_mb"] * _MB, lim["script_file_mb"] * _MB

        def limits():
            resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
            resource.setrlimit(resource.RLIMIT_FSIZE, (file_size, file_size))

        self._err = tempfile.TemporaryFile()
        self._buf = b""
        self.proc = subprocess.Popen(_command(bwrap, ws, entry, args, ro_files, lim["script_tmp_mb"]),
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._err,
                                     preexec_fn=limits)

    def _fail(self, reason: str):
        self.error = self.error or reason
        return None

    def _send(self, data: bytes) -> bool:
        """Write data to the script's stdin without blocking past the deadline (a script that never reads its
        stdin while its own stdout is full would otherwise block both sides for good)."""
        fd = self.proc.stdin.fileno()
        os.set_blocking(fd, False)
        view = memoryview(data)
        while view:
            left = self.deadline - time.monotonic()
            if left <= 0:
                self.timed_out = True
                self._fail("deadline: the script took longer than tools.script_timeout_s")
                return False
            _, ready, _ = select.select([], [fd], [], left)
            if not ready:
                continue
            try:
                view = view[os.write(fd, view):]
            except BlockingIOError:
                continue
            except (BrokenPipeError, OSError):
                self._fail("the script ended")
                return False
        return True

    def ask(self, obj):
        """Send obj as one JSON line; return the next line parsed, or None (see .error) when the script ended, the
        deadline passed, the line was too long or not JSON."""
        if self.error:
            return None
        if not self._send((json.dumps(obj) + "\n").encode()):
            return None
        out = self.proc.stdout.fileno()
        while b"\n" not in self._buf:
            left = self.deadline - time.monotonic()
            if left <= 0:
                self.timed_out = True
                return self._fail("deadline: the script took longer than tools.script_timeout_s")
            ready, _, _ = select.select([out], [], [], left)
            if not ready:
                continue
            chunk = os.read(out, 65536)
            if not chunk:
                return self._fail("the script ended")
            self._buf += chunk
            if len(self._buf) > _LINE_MAX and b"\n" not in self._buf:
                return self._fail("a reply line was longer than 1 MB")
        line, self._buf = self._buf.split(b"\n", 1)
        try:
            return json.loads(line)
        except ValueError:
            return self._fail(f"not a JSON line: {line[:200]!r}")

    def close(self) -> dict:
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=0 if self.timed_out else 2)
        except subprocess.TimeoutExpired:
            pass
        if self.proc.poll() is None:
            self.proc.kill()                 # bwrap dies; --die-with-parent takes the script with it
            self.proc.wait()
        self.proc.stdout.close()
        self._err.seek(0)
        stderr = read_head(self._err.fileno(), self.cfg["tools"]["script_output_chars"])
        self._err.close()
        return {"exit_code": None if self.timed_out else self.proc.returncode, "stderr": stderr,
                "timed_out": self.timed_out, "error": self.error}
