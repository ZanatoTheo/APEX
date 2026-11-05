"""Worst-case dollars for one cycle, from the config's caps and pricing.

Tokens are chars / 4, plus a fixed allowance per prompt for its fixed text. Calls that ask_json may retry count
twice. Agent and subagent tokens (input and output share one cap) are priced at the higher of the two rates.
The real spend is still held to budget.cycle_usd by CycleBudget; this is for choosing caps before a run.
"""


def _rates(cfg: dict, role: str) -> dict:
    return cfg["pricing"][cfg["models"]["roles"][role]["model_id"]]


def _usd(cfg: dict, role: str, tokens_in: float, tokens_out: float) -> float:
    r = _rates(cfg, role)
    return (tokens_in * r["input"] + tokens_out * r["output"]) / 1_000_000


def cycle_cost(cfg: dict, steps: int) -> dict:
    op, lim, cl = cfg["operation"], cfg["limits"], cfg["cleaner"]
    n = op["agents"]
    top = lambda role: max(_rates(cfg, role).values()) / 1_000_000
    roles = {
        "agent": steps * n * lim["call_tokens"] * top("agent"),
        "subagent": steps * n * lim["subagent_tokens"] * top("subagent"),
        "summarizer": steps * _usd(cfg, "summarizer", (n * 1000 + 2000) / 4, op["summary_output_tokens"]),
        "evaluator": n * 2 * _usd(cfg, "evaluator", (op["eval_files_chars"] + 6000) / 4, op["eval_output_tokens"]),
        "mutation": 2 * _usd(cfg, "mutation", (op["mutation_files_chars"] + n * 6000) / 4,
                             op["mutation_output_tokens"]),
        "orchestrator": 2 * 2 * _usd(cfg, "orchestrator", (op["orch_notes_chars"] + 10000) / 4,
                                     op["orch_output_tokens"]),
        "cleaner": n * 2 * _usd(cfg, "cleaner", (cl["files_chars"] + 3000) / 4, cl["output_tokens"]),
    }
    return {"steps": steps, "roles": roles, "total": sum(roles.values()), "cap": cfg["budget"]["cycle_usd"]}
