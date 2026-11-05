"""The connector: the only door between the core and a task.

The core knows nothing about the task. Op. Orch drives a connector through the methods below and nothing else; to
change the task, only apex/env_connector/ and environment/ change. A connector module exposes
`make_connector(cfg, data=None)`.

| method | returns | meaning |
|---|---|---|
| brief() | str | what the task is; never holds step data |
| n_steps() | int | steps in one loop (0-based) |
| release(step) | None | make `step` current: data of steps <= step visible, later steps not (a lower step moves back) |
| begin_cycle(agent_ids) | None | reset the per-agent state a cycle starts from |
| run_step(agent_id, agent_dir, step) | dict | test the agent's work on the released step; small JSON-able values |
| cycle_score(agent_id) | float | the agent's score for the cycle so far |
| tools(agent_id, agent_dir, step) | list[Tool] | extra function tools, gated by the released step |
| cleaning_rules() | dict | {data_file, what_counts_as_data, patterns, file_globs?}: file_globs = files that are data as a whole |
| starter_files() | dict | {relative path: content} a new agent starts with |

Optional methods (read through the helpers below, never called directly):

| method | returns | meaning |
|---|---|---|
| steps_per_cycle() | int >= 1 | steps in one cycle for this task's data; else config operation.steps_per_cycle |
| target_score() | finite float | the loop score that counts as good enough, from a reference outside the agents |
| script_files(agent_id, step) | dict | {"/data/<name>": host file}: released files run_script mounts read-only |
"""
import importlib
import math
from pathlib import Path

REQUIRED_METHODS = ("brief", "n_steps", "release", "begin_cycle", "run_step", "cycle_score", "tools",
                    "cleaning_rules", "starter_files")


class ConnectorError(Exception):
    """A connector is broken or misused (e.g. a step that isn't released)."""


def check_connector(obj) -> None:
    missing = [name for name in REQUIRED_METHODS if not callable(getattr(obj, name, None))]
    if missing:
        raise ConnectorError(f"connector is missing: {', '.join(missing)}")


def load_connector(module_path: str, cfg: dict, data=None):
    if not isinstance(module_path, str) or not module_path.strip():
        raise ConnectorError("no connector module given (config task.connector)")
    try:                                 # any failure here ends in one clear ConnectorError for run.py
        module = importlib.import_module(module_path)
    except Exception as e:
        raise ConnectorError(f"cannot import connector module {module_path}: {type(e).__name__}: {e}") from None
    make = getattr(module, "make_connector", None)
    if not callable(make):
        raise ConnectorError(f"{module_path} has no make_connector(cfg, data)")
    try:
        conn = make(cfg, data)
    except ConnectorError:
        raise
    except Exception as e:
        raise ConnectorError(f"{module_path}.make_connector failed: {type(e).__name__}: {e}") from None
    check_connector(conn)
    return conn


def _optional(connector, name: str):
    """(True, value) if the connector has the optional method `name`, else (False, None). Errors → ConnectorError."""
    method = getattr(connector, name, None)
    if not callable(method):
        return False, None
    try:
        return True, method()
    except Exception as e:
        raise ConnectorError(f"connector {name}() failed: {type(e).__name__}: {e}") from None


def cycle_steps(connector, cfg: dict) -> int:
    """Steps per cycle: the connector's optional steps_per_cycle(), else operation.steps_per_cycle."""
    has, value = _optional(connector, "steps_per_cycle")
    if not has:
        return cfg["operation"]["steps_per_cycle"]
    if type(value) is not int or value < 1:
        raise ConnectorError(f"steps_per_cycle() must be an int >= 1, got {value!r}")
    return value


def target_score(connector):
    """The connector's optional target_score() as a float, or None."""
    has, value = _optional(connector, "target_score")
    if not has:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConnectorError(f"target_score() must be a finite number, got {value!r}")
    try:
        value = float(value)
    except OverflowError:
        value = math.inf
    if not math.isfinite(value):
        raise ConnectorError(f"target_score() must be a finite number, got {value!r}")
    return value


def script_files(connector, agent_id: str, step: int) -> dict:
    """The connector's optional script_files(agent_id, step), checked: {"/data/<name>": existing host file}, else {}.
    run_script mounts them read-only for the agent and its subagents."""
    method = getattr(connector, "script_files", None)
    if not callable(method):
        return {}
    try:
        files = method(agent_id, step)
    except Exception as e:
        raise ConnectorError(f"connector script_files() failed: {type(e).__name__}: {e}") from None
    if not isinstance(files, dict):
        raise ConnectorError(f"script_files() must return a dict, got {type(files).__name__}")
    out = {}
    for inside, host in files.items():
        name = inside[len("/data/"):] if isinstance(inside, str) and inside.startswith("/data/") else ""
        if not name or ".." in name.split("/") or "" in name.split("/"):
            raise ConnectorError(f"script_files() paths must be /data/<name>, got {inside!r}")
        try:
            ok = Path(host).is_file() and not Path(host).is_symlink()
        except (TypeError, OSError):
            ok = False
        if not ok:
            raise ConnectorError(f"script_files() needs an existing regular host file for {inside}: {host!r}")
        out[inside] = str(host)
    return out
