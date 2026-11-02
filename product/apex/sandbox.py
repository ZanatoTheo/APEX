"""Sandbox and tools (design §14, CODE_STRUCTURE §5.6), prototype form (JC-33).

Task code runs in a subprocess inside a per-run copy of the task, with a timeout, prlimit caps, a scrubbed
environment and, when the kernel allows it, `unshare -rn` for no network. This is NOT a security boundary.
"""
import difflib
import fnmatch
import functools
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from . import canonical

RUNNER = Path(__file__).resolve().parent / "testrunner.py"
# CODE_STRUCTURE §5.6 denied paths (any depth), stricter than design §14 on purpose.
DENIED_NAMES = {"conftest.py", "pytest.ini", "setup.cfg", "tox.ini", "pyproject.toml",
                "sitecustomize.py", "usercustomize.py"}
FORBIDDEN_DIFF_LINES = ("rename from", "rename to", "copy from", "copy to", "old mode", "new mode",
                        "new file mode", "deleted file mode", "similarity index", "dissimilarity index",
                        "GIT binary patch", "Binary files")
READ_CAP = 64 * 1024
TEST_OUTPUT_CAP = 16 * 1024


@dataclass(frozen=True)
class Limits:
    timeout_s: int = 30
    memory_mb: int = 1024
    file_size_mb: int = 16


@dataclass
class TestRun:
    passed: int
    total: int
    output: str
    timed_out: bool = False
    killed: bool = False

    @property
    def pass_ppm(self) -> int:
        return self.passed * 1_000_000 // self.total if self.total else 0


@dataclass
class ToolResult:
    status: str   # the outcome label the agent graph branches on
    output: str
    data: dict = field(default_factory=dict)


# -- patch policy ------------------------------------------------------------------------------------------

def is_denied(path: str) -> bool:
    p = PurePosixPath(path)
    return p.parts[:1] == ("tests",) or p.name in DENIED_NAMES or p.suffix == ".pth"


def _header_path(raw: str, problems: list) -> str | None:
    """Path as `git apply -p1` will see it, or None (with a problem recorded) if it is not acceptable."""
    if raw.startswith('"'):
        problems.append(f"quoted path {raw!r} is not allowed")
        return None
    if not raw.startswith(("a/", "b/")):
        problems.append(f"path {raw!r} must start with a/ or b/ (git apply strips one leading component)")
        return None
    path = raw[2:]
    pure = PurePosixPath(path)
    if not path or pure.is_absolute() or ".." in pure.parts or "\\" in path:
        problems.append(f"unsafe path {raw!r}")
        return None
    return path


def patch_problems(diff: str, editable_paths) -> tuple[list[str], list[str]]:
    """Return (paths touched, policy problems) for a unified diff. Only plain edits of existing text files pass."""
    paths, problems = [], []
    if not isinstance(diff, str) or not diff.strip():
        return [], ["empty patch"]
    for line in diff.splitlines():
        line = line.rstrip("\r")
        forbidden = next((f for f in FORBIDDEN_DIFF_LINES if line.startswith(f)), None)
        if forbidden:
            problems.append(f"forbidden hunk type ({forbidden}): only plain text edits are allowed")
        raws = []
        if line.startswith(("--- ", "+++ ")):
            raws = [line[4:].split("\t")[0].strip()]
        elif line.startswith("diff --git "):
            raws = line[len("diff --git "):].split(" ")
        for raw in raws:
            if raw == "/dev/null":
                problems.append("creating or deleting files is not allowed")
                continue
            path = _header_path(raw, problems)
            if path is not None and path not in paths:
                paths.append(path)
    if not paths and not problems:
        problems.append("no file headers (expected '--- a/<path>' and '+++ b/<path>')")
    for path in paths:
        if is_denied(path):
            problems.append(f"{path}: denied path (tests and test configuration cannot be edited)")
        elif not any(fnmatch.fnmatchcase(path, pat) for pat in editable_paths):
            problems.append(f"{path}: outside editable_paths {list(editable_paths)}")
    return paths, list(dict.fromkeys(problems))


# -- process runner ----------------------------------------------------------------------------------------

@functools.cache
def _network_prefix() -> tuple:
    try:
        ok = subprocess.run(["unshare", "-rn", "true"], capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        ok = False
    return ("unshare", "-rn") if ok else ()


def network_isolated() -> bool:
    return bool(_network_prefix())


def limits_enforced() -> bool:
    return shutil.which("prlimit") is not None


def _limit_prefix(limits: Limits) -> tuple:
    if not limits_enforced():
        return ()
    return ("prlimit", f"--as={limits.memory_mb * 1024 * 1024}", f"--cpu={limits.timeout_s + 1}",
            f"--fsize={limits.file_size_mb * 1024 * 1024}", "--core=0", "--")


def _env(work_dir: Path) -> dict:
    path = os.pathsep.join(dict.fromkeys([str(Path(sys.executable).parent), "/usr/local/bin", "/usr/bin", "/bin"]))
    return {"PATH": path, "HOME": str(work_dir), "LANG": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0", "TMPDIR": str(work_dir)}


def _truncate(text: str, cap: int) -> str:
    if len(text) <= cap:
        return text
    half = cap // 2
    return text[:half] + f"\n…[{len(text) - cap} characters truncated]…\n" + text[-half:]


_RAN = re.compile(r"^Ran (\d+) tests? in ", re.M)
_FAILED = re.compile(r"^FAILED \(([^)]*)\)", re.M)


def parse_unittest(output: str) -> tuple[int, int]:
    """(passed, total) from unittest's text summary; (0, 0) when no summary was printed. Display only."""
    ran = _RAN.findall(output)
    if not ran:
        return 0, 0
    total = int(ran[-1])
    bad = 0
    failed = _FAILED.findall(output)
    if failed:
        for part in failed[-1].split(","):
            key, _, value = part.strip().partition("=")
            if key in ("failures", "errors", "unexpected successes") and value.isdigit():
                bad += int(value)
    return max(total - bad, 0), total


def _parse_result(text: str, nonce: str, returncode: int | None) -> tuple[int, int]:
    """Trust only the runner's nonce line, and only if the exit code agrees with it."""
    found = None
    for m in re.finditer(r"^APEX-RESULT (\S+) (\{.*\})$", text, re.M):
        if m.group(1) == nonce:
            try:
                data = json.loads(m.group(2))
                found = (int(data["passed"]), int(data["total"]))
            except (ValueError, KeyError, TypeError):
                found = None
    if found is None:
        return 0, 0
    passed, total = found
    all_pass = total > 0 and passed == total
    if all_pass != (returncode == 0):
        return 0, max(total, 1)   # the exit code contradicts the reported result: count nothing as passed
    return passed, total


def _kill_group(pid: int):
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def run_test_command(work_dir: Path, tests_dir: str, limits: Limits) -> TestRun:
    nonce = secrets.token_hex(16)
    cmd = [*_network_prefix(), *_limit_prefix(limits), sys.executable, str(RUNNER), tests_dir]
    env = {**_env(work_dir), "APEX_RESULT_NONCE": nonce}
    try:
        proc = subprocess.Popen(cmd, cwd=work_dir, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, start_new_session=True)
    except OSError as e:
        return TestRun(0, 1, f"could not start the test runner: {e}")
    timed_out = False
    try:
        out, _ = proc.communicate(timeout=limits.timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_group(proc.pid)
        try:
            out, _ = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:   # a setsid'd grandchild still holds the pipe
            proc.kill()
            out = b""
    finally:
        _kill_group(proc.pid)               # no background children outlive the run
    text = out.decode("utf-8", errors="replace")
    passed, total = (0, 1) if timed_out else _parse_result(text, nonce, proc.returncode)
    total = max(total, 1)   # no trustworthy result counts as a failed run, never as "no tests" (pass-rate denominator)
    text = re.sub(r"^APEX-RESULT .*$", "", text, flags=re.M).rstrip()   # the nonce never reaches a prompt
    killed = proc.returncode is not None and proc.returncode < 0 and not timed_out
    if timed_out:
        text += f"\n[timed out after {limits.timeout_s}s]"
    return TestRun(passed, total, _truncate(text, TEST_OUTPUT_CAP), timed_out, killed)


def _git_env(work_dir: Path) -> dict:
    # Stop git from discovering an enclosing repository, so patch paths are relative to the workspace.
    return {**_env(work_dir), "GIT_CEILING_DIRECTORIES": str(work_dir.parent)}


# -- workspace ---------------------------------------------------------------------------------------------

class Workspace:
    """A writable copy of one task: repo files at the top, the given tests (read-only) under tests/."""

    def __init__(self, repo_dir: Path, tests_dir: Path, editable_paths, work_root: Path,
                 limits: Limits = Limits()):
        Path(work_root).mkdir(parents=True, exist_ok=True)
        self.dir = Path(tempfile.mkdtemp(prefix="ws-", dir=work_root)).resolve()
        self.editable_paths = tuple(editable_paths)
        self.limits = limits
        self.violations: list[str] = []
        try:
            shutil.copytree(repo_dir, self.dir, dirs_exist_ok=True)
            shutil.copytree(tests_dir, self.dir / "tests")
            self._original = self._snapshot()
            self._set_tests_writable(False)
            self.original_tests_hash = self.tests_hash()
        except BaseException:
            self.close()
            raise

    @classmethod
    def for_task(cls, task, work_root: Path, limits: Limits = Limits(), tests_dir: Path | None = None):
        return cls(task.repo_dir, tests_dir or task.tests_dir, task.editable_paths, work_root, limits)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if self.dir.exists():
            self._set_tests_writable(True)
            shutil.rmtree(self.dir, ignore_errors=True)

    def _set_tests_writable(self, writable: bool):
        tests = self.dir / "tests"
        if not tests.exists():
            return
        for p in [tests, *tests.rglob("*")]:
            try:
                if p.is_dir():
                    p.chmod(0o755 if writable else 0o555)
                elif p.is_file():
                    p.chmod(0o644 if writable else 0o444)
            except OSError:
                pass

    def _snapshot(self) -> dict[str, bytes]:
        return {p.relative_to(self.dir).as_posix(): p.read_bytes() for p in sorted(self.dir.rglob("*"))
                if p.is_file() and not p.relative_to(self.dir).as_posix().startswith("tests/")
                and "__pycache__" not in p.parts}

    def tests_hash(self) -> str:
        tests = self.dir / "tests"
        return canonical.hash_obj({p.relative_to(tests).as_posix(): canonical.sha256_hex(p.read_bytes())
                                   for p in sorted(tests.rglob("*")) if p.is_file() and "__pycache__" not in p.parts})

    def tests_intact(self) -> bool:
        return self.tests_hash() == self.original_tests_hash

    # -- tools -------------------------------------------------------------------------------------------
    def exec(self, tool: str, args: dict) -> ToolResult:
        args = args if isinstance(args, dict) else {}
        if tool == "read_file":
            return self.read_file(args.get("path"))
        if tool == "run_tests":
            return self.run_tests()
        if tool == "write_patch":
            return self.write_patch(args.get("diff"))
        return ToolResult("error", f"unknown tool {tool!r}")

    def read_file(self, path) -> ToolResult:
        if not isinstance(path, str) or not path:
            return ToolResult("error", "read_file needs a string 'path'")
        target = (self.dir / path).resolve()
        if not target.is_relative_to(self.dir):
            return ToolResult("error", f"{path}: outside the workspace")
        if not target.is_file():
            return ToolResult("error", f"{path}: no such file")
        text = target.read_bytes()[:READ_CAP].decode("utf-8", errors="replace")
        if target.stat().st_size > READ_CAP:
            text += f"\n…[truncated at {READ_CAP} bytes]"
        return ToolResult("ok", text, {"path": path})

    def run_tests(self) -> ToolResult:
        run = run_test_command(self.dir, "tests", self.limits)
        if run.timed_out:
            self.violations.append("timeout")
        elif run.killed:
            self.violations.append("killed by resource limit")
        if not self.tests_intact():
            self.violations.append("tests modified")
            run.passed = 0
        status = "timeout" if run.timed_out else ("pass" if run.total and run.passed == run.total else "fail")
        return ToolResult(status, run.output, {"passed": run.passed, "total": run.total})

    def write_patch(self, diff) -> ToolResult:
        paths, problems = patch_problems(diff, self.editable_paths)
        if problems:
            return ToolResult("rejected", "patch rejected: " + "; ".join(problems))
        if not diff.endswith("\n"):
            diff += "\n"
        for args in (["git", "apply", "--check", "-p1", "-"], ["git", "apply", "-p1", "--whitespace=nowarn", "-"]):
            r = subprocess.run(args, cwd=self.dir, env=_git_env(self.dir), input=diff.encode("utf-8"),
                               capture_output=True, timeout=30)
            if r.returncode != 0:
                return ToolResult("rejected", "patch does not apply: " + r.stderr.decode("utf-8", "replace").strip())
        return ToolResult("applied", f"patched {', '.join(paths)}", {"paths": paths})

    def diff(self) -> str:
        """The final patch: workspace vs the original snapshot (tests excluded)."""
        now = self._snapshot()
        out = []
        for rel in sorted(set(self._original) | set(now)):
            a, b = self._original.get(rel), now.get(rel)
            if a == b:
                continue
            a_lines = (a or b"").decode("utf-8", "replace").splitlines(keepends=True)
            b_lines = (b or b"").decode("utf-8", "replace").splitlines(keepends=True)
            out += difflib.unified_diff(a_lines, b_lines, fromfile=f"a/{rel}" if a is not None else "/dev/null",
                                        tofile=f"b/{rel}" if b is not None else "/dev/null")
        return "".join(out)
