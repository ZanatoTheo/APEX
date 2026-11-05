"""Run configuration: JSON files merged over DEFAULTS, then checked.

Secrets never go here: apex/llm.py reads the API key from $MODEL_API_KEY.
"""
import copy
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ROLES = ("orchestrator", "agent", "subagent", "evaluator", "mutation", "summarizer", "cleaner")
EFFORTS = (None, "minimal", "low", "medium", "high", "max")

_SPARK_C = "muse-spark-1.3-contributor"

DEFAULTS = {
    "models": {
        "base_url": "https://api.meta.ai/v1",
        "request_timeout_s": 120,
        "retries": 3,                 # extra tries after the first
        "retry_backoff_s": 2.0,       # waits 2, 4, 8 s
        "roles": {role: {"model_id": _SPARK_C, "reasoning_effort": None}   # every role on contributor (user,
                  for role in ROLES},                                           # 2026-11-04)
    },
    "pricing": {                      # USD per 1M tokens (models.md)
        "muse-wonder-1.0": {"input": 4.00, "cached_input": 0.20, "output": 20.00},
        "muse-spark-1.3": {"input": 1.25, "cached_input": 0.15, "output": 4.25},
        "muse-spark-1.2": {"input": 1.25, "cached_input": 0.15, "output": 4.25},
        "muse-spark-1.3-contributor": {"input": 0.10, "cached_input": 0.002, "output": 0.20},
        "muse-spark-1.2-contributor": {"input": 0.10, "cached_input": 0.002, "output": 0.20},
    },
    "limits": {                       # per call_agent (apex/budget.py CallBudget)
        "call_tokens": 18000,         # the agent's own input + output tokens in one step
        "call_turns": 25,             # the agent's own model calls in one step
        "subagent_tokens": 8000,      # one pool shared by all its subagents in that step
        "max_output_tokens": 4000,    # per model call
        "min_output_tokens": 256,     # a call that can't get this many output tokens isn't sent
        "max_subagents": 4,           # tasks in one spawn_subagents call
    },
    "budget": {"cycle_usd": 2.5},     # all roles together, per cycle (CycleBudget)
    "task": {"connector": "",         # module with make_connector(cfg, data); run.py requires it
             "settings": {}},         # free keys for the task's own scripts; the core never reads them
    "operation": {                    # Op. Orch's operation (apex/orchestrator.py)
        "agents": 10,
        "parallel_agents": 1,         # agents of one step working at the same time (1: one after another)
        "steps_per_cycle": 4,
        "survivors": 2,               # top agents kept unchanged each cycle (Op. Orch may add one more)
        "base_margin": 0.2,           # bases: score >= avg + base_margin * |avg|
        "worse_child_penalty": 0.2,   # an agent below its parents ranks with score - this * max(|avg|, spread)
        "max_loops": 3,               # hard stop: full passes over the connector's steps
        "max_cycles": None,           # null, or stop after this many cycles in all (whichever of the two comes first)
        "advice_below": None,         # null, or: a survivor scoring below this sees its own Eval weaknesses
        "max_minutes": None,          # null, or a time limit for the run in minutes (time_limit stop)
        "axes": [                     # every agent's axioms give one rule per axis
            "signals: what the agent watches",
            "decision rule: how it turns signals into actions",
            "sizing: how much it commits to each action",
            "adaptation: when and how it changes its rules",
            "safety: how it limits losses and errors",
        ],
        "orch_output_tokens": 8000,       # 28 steps per cycle fit the $2.50 cap (2026-11-04)
        "summary_output_tokens": 1500,
        "eval_output_tokens": 8000,
        "eval_files_chars": 60000,    # one agent's files shown to Eval
        "mutation_output_tokens": 16000,
        "mutation_files_chars": 120000,   # all agents' files shown to Mutation, split evenly
        "orch_notes_chars": 40000,    # Eval notes shown to Op. Orch at the next generation, in all
    },
    "cleaner": {                      # cycle-end data cleaning (apex/cleaner.py)
        "files_chars": 60000,         # an agent's text files shown to the cleaner model, in all
        "output_tokens": 4000,
        "dense_share": 0.3,           # a file whose pattern matches cover this share of its text is deleted whole
        "max_matches_per_file": 100,  # ... or that has more matches than this
    },
    "tools": {                        # agent tools (apex/tools/)
        "max_file_chars": 200000,     # largest file write_file / edit_file may produce
        "max_read_chars": 50000,      # read_file returns at most this much
        "max_list_entries": 500,      # list_files lines
        "max_tool_output_chars": 20000,   # any tool output sent back to the model
        "script_timeout_s": 60,       # run_script wall time
        "script_memory_mb": 4096,     # run_script address space (RLIMIT_AS)
        "script_file_mb": 100,        # largest file a script may write, stdout and stderr included (RLIMIT_FSIZE)
        "script_tmp_mb": 256,         # the sandbox's in-memory /tmp
        "max_folder_mb": 500,         # run_script refuses to start when the agent's folder is bigger
        "script_output_chars": 8000,  # run_script stdout and stderr, each (both must fit one tool output)
    },
}

_OPEN = {"pricing", "task.settings"}                                # any key may be added under these paths
_NULLABLE = {"reasoning_effort"}                     # null or a string
_NULLABLE_INT = {"max_cycles", "max_minutes"}        # null or an int (validate checks >= 1)
_NULLABLE_NUM = {"advice_below"}                     # null or a finite number
_BASE_URL = re.compile(r"(https://[^/\s]+|http://(127\.0\.0\.1|localhost)(:\d+)?)(/\S*)?")   # used with fullmatch


class ConfigError(ValueError):
    pass


def _same_type(default, value) -> bool:
    if isinstance(default, bool) or isinstance(value, bool):
        return type(default) is type(value)
    if isinstance(default, float):
        return isinstance(value, (int, float))       # JSON writes 4 for 4.0
    return type(value) is type(default)


def _merge(base: dict, override: dict, path: str) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        where = f"{path}{key}"
        if key not in base:
            if path.rstrip(".") in _OPEN:
                out[key] = copy.deepcopy(value)
                continue
            raise ConfigError(f"unknown config key {where}")
        default = base[key]
        if isinstance(default, dict):
            if not isinstance(value, dict):
                raise ConfigError(f"{where} must be an object")
            out[key] = _merge(default, value, f"{where}.")
        elif key in _NULLABLE:
            if value is not None and not isinstance(value, str):
                raise ConfigError(f"{where} must be null or a string")
            out[key] = value
        elif key in _NULLABLE_NUM:
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                      or not math.isfinite(value)):
                raise ConfigError(f"{where} must be null or a finite number")
            out[key] = value
        elif key in _NULLABLE_INT:
            if value is not None and type(value) is not int:
                raise ConfigError(f"{where} must be null or an int")
            out[key] = value
        else:
            if not _same_type(default, value):
                raise ConfigError(f"{where} must be {type(default).__name__}")
            out[key] = copy.deepcopy(value)
    return out


def validate(cfg: dict) -> None:
    m = cfg["models"]
    if not _BASE_URL.fullmatch(m["base_url"]):
        raise ConfigError("models.base_url must be https://…, or http://127.0.0.1 / http://localhost for a local stub")
    if m["request_timeout_s"] <= 0:
        raise ConfigError("models.request_timeout_s must be positive")
    if m["retries"] < 0 or m["retry_backoff_s"] < 0:
        raise ConfigError("models.retries and models.retry_backoff_s must be >= 0")
    if set(m["roles"]) != set(ROLES):
        raise ConfigError(f"models.roles must be exactly {', '.join(ROLES)}")
    for role, spec in m["roles"].items():
        if not isinstance(spec.get("model_id"), str) or not spec["model_id"]:
            raise ConfigError(f"models.roles.{role}.model_id must be a non-empty string")
        if spec["reasoning_effort"] not in EFFORTS:
            raise ConfigError(f"models.roles.{role}.reasoning_effort must be one of {EFFORTS}")
        row = cfg["pricing"].get(spec["model_id"])
        if row is None:
            raise ConfigError(f"no pricing row for model {spec['model_id']} (role {role})")
    for model_id, row in cfg["pricing"].items():
        if not isinstance(row, dict) or set(row) != {"input", "cached_input", "output"}:
            raise ConfigError(f"pricing.{model_id} must have exactly input, cached_input, output")
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0
                   for v in row.values()):
            raise ConfigError(f"pricing.{model_id} rates must be finite numbers >= 0")
        if row["cached_input"] > row["input"]:
            raise ConfigError(f"pricing.{model_id}.cached_input must be <= input (else the worst case is too low)")
    lim = cfg["limits"]
    for name, value in lim.items():
        if value <= 0:
            raise ConfigError(f"limits.{name} must be positive")
    if not lim["min_output_tokens"] <= lim["max_output_tokens"] <= lim["call_tokens"]:
        raise ConfigError("limits must satisfy min_output_tokens <= max_output_tokens <= call_tokens")
    if lim["max_output_tokens"] > lim["subagent_tokens"]:
        raise ConfigError("limits.max_output_tokens must be <= limits.subagent_tokens")
    if not math.isfinite(cfg["budget"]["cycle_usd"]) or cfg["budget"]["cycle_usd"] <= 0:
        raise ConfigError("budget.cycle_usd must be a finite number > 0")
    for name, value in cfg["tools"].items():
        if value <= 0:
            raise ConfigError(f"tools.{name} must be positive")
    op = cfg["operation"]
    for name, value in op.items():
        if type(value) is int and value <= 0:
            raise ConfigError(f"operation.{name} must be positive")
    if op["survivors"] >= op["agents"]:
        raise ConfigError("operation.survivors must be less than operation.agents")
    if not math.isfinite(op["base_margin"]) or op["base_margin"] < 0:
        raise ConfigError("operation.base_margin must be a finite number >= 0")
    if isinstance(op["worse_child_penalty"], bool) or not isinstance(op["worse_child_penalty"], (int, float)) \
            or not math.isfinite(op["worse_child_penalty"]) or op["worse_child_penalty"] < 0:
        raise ConfigError("operation.worse_child_penalty must be a finite number >= 0")
    cl = cfg["cleaner"]
    for name, value in cl.items():
        if type(value) is int and value <= 0:
            raise ConfigError(f"cleaner.{name} must be positive")
    if not math.isfinite(cl["dense_share"]) or not 0 < cl["dense_share"] <= 1:
        raise ConfigError("cleaner.dense_share must be in (0, 1]")
    axes = op["axes"]
    if not 1 <= len(axes) <= 12 or not all(isinstance(a, str) and a.strip() for a in axes) \
            or len(set(axes)) != len(axes):
        raise ConfigError("operation.axes must be 1 to 12 unique non-empty strings")


def load(path: Path | str | None = None, overrides: dict | None = None) -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    if path is not None:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise ConfigError(f"cannot read config {path}: {e}") from e
        if not isinstance(data, dict):
            raise ConfigError(f"config {path} must be a JSON object")
        cfg = _merge(cfg, data, "")
    if overrides:
        cfg = _merge(cfg, overrides, "")
    validate(cfg)
    return cfg
