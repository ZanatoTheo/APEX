"""Run configuration (CODE_STRUCTURE §6.1, prototype defaults per JC-37).

Configs are JSON (JC-35). Rates and weights are integer ppm so the parsed config can be hashed with JCS.
Secrets never go here: an LLM service reads its API keys from environment variables.
"""
import copy
import json
import re
from pathlib import Path

from . import canonical

PROTO_ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = {
    "run": {"seed": 1234, "g_max": 8},
    "population": {"P": 4, "mu": 2},
    "batch": {"K": 3},
    "ucb1": {"c_ppm": 1_414_214},                                  # √2
    "l1_weights_ppm": {"pass_rate": 700_000, "tokens": 200_000, "latency": 100_000},
    "limits": {"token_budget": 20000, "timeout_s": 120, "test_timeout_s": 20, "memory_mb": 1024},
    "budget": {"tokens_total": 2_000_000, "holdout_reserve": 200_000, "max_concurrent": 4},
    "mutation": {"scopes": ["graph_config", "prompt_axiom"], "max_attempts": 3, "max_patch_ops": 5,
                 "max_axioms": 8, "max_axiom_chars": 300},
    "models": {
        "provider": "fake",                                       # fake | llm (loads apex/llm_service.py)
        "retries": 3,
        "retry_backoff_s": 1,
        "base_url": "https://api.meta.ai/v1",                     # Responses API endpoint (llm_service.py)
        "request_timeout_s": 120,
        "subagent": {"model_id": "fake-subagent-1", "max_tokens": 2000},
        "mutation": {"model_id": "fake-mutation-1", "max_tokens": 2000},
    },
    "paths": {"corpus": "corpus", "holdout": "holdout", "oracle": "oracle", "seed_agent": "seeds/baseline.json",
              "runs": "runs"},
    "gates": {"version": 1},
}


class ConfigError(ValueError):
    pass


_BASE_URL = re.compile(r"(https://[^/\s]+|http://(127\.0\.0\.1|localhost)(:\d+)?)(/\S*)?")   # used with fullmatch


def _merge(base: dict, override: dict, path: str) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if key not in base:
            raise ConfigError(f"unknown config key {path}{key}")
        if isinstance(base[key], dict):
            if not isinstance(value, dict):
                raise ConfigError(f"{path}{key} must be an object")
            out[key] = _merge(base[key], value, f"{path}{key}.")
        else:
            if type(value) is not type(base[key]):
                raise ConfigError(f"{path}{key} must be {type(base[key]).__name__}")
            out[key] = copy.deepcopy(value)
    return out


def validate(cfg: dict) -> None:
    pos = [("population", "P"), ("population", "mu"), ("batch", "K"), ("run", "g_max"),
           ("limits", "token_budget"), ("limits", "timeout_s"), ("limits", "test_timeout_s"),
           ("mutation", "max_attempts"), ("mutation", "max_patch_ops"), ("budget", "tokens_total")]
    for section, key in pos:
        if cfg[section][key] <= 0:
            raise ConfigError(f"{section}.{key} must be positive")
    if not 1 <= cfg["population"]["mu"] <= cfg["population"]["P"]:
        raise ConfigError("population.mu must be between 1 and P")
    if sum(cfg["l1_weights_ppm"].values()) != 1_000_000:
        raise ConfigError("l1_weights_ppm must sum to 1000000")
    if not 0 <= cfg["budget"]["holdout_reserve"] < cfg["budget"]["tokens_total"]:
        raise ConfigError("budget.holdout_reserve must be below budget.tokens_total")
    if not set(cfg["mutation"]["scopes"]) <= {"graph_config", "prompt_axiom"} or not cfg["mutation"]["scopes"]:
        raise ConfigError("mutation.scopes must be a non-empty subset of graph_config, prompt_axiom")
    if cfg["models"]["provider"] not in ("fake", "llm"):
        raise ConfigError("models.provider must be 'fake' or 'llm'")
    if not _BASE_URL.fullmatch(cfg["models"]["base_url"]):
        raise ConfigError("models.base_url must be https://…, or http://127.0.0.1 / http://localhost for a local stub")
    if cfg["models"]["request_timeout_s"] <= 0:
        raise ConfigError("models.request_timeout_s must be positive")
    canonical.dumps(cfg)   # hashable: no floats


def load(path: Path | None = None, overrides: dict | None = None) -> dict:
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


def resolve_path(cfg: dict, name: str) -> Path:
    p = Path(cfg["paths"][name])
    return p if p.is_absolute() else PROTO_ROOT / p


def config_hash(cfg: dict) -> str:
    return canonical.hash_obj(cfg)
