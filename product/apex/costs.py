"""Worst-case token cost of a run, from its config alone (`run.py estimate`; logic and hand traces: ../LOGIC.md).

Kept apart from stats.py, which reads only the public record and never names the evaluator-only store: this module
needs the held-out reserve and task count. No model call, no key.
"""

PROMPT_TOKENS_EST = 4000   # input of one call apart from replayed history (prompt, task, newest tool output or trace)


def estimate(cfg: dict, n_heldout: int) -> dict:
    """Worst-case token use of a run with `cfg`: every call hits its cap. Mirrors evolution._run's structure.

    Reads only the config and the held-out task count; no model call, no key.
    """
    P, mu, K, g_max = cfg["population"]["P"], cfg["population"]["mu"], cfg["batch"]["K"], cfg["run"]["g_max"]
    token_budget = cfg["limits"]["token_budget"]
    subagent_call = cfg["models"]["subagent"]["max_tokens"] + PROMPT_TOKENS_EST
    # The budget is checked before each call, and each call re-sends the history (< token_budget), so the last call
    # can cost token_budget + subagent_call on top of the < token_budget already spent (LOGIC.md, phase 6, R9).
    run_cap = 2 * token_budget + subagent_call
    mutation_call = cfg["models"]["mutation"]["max_tokens"] + PROMPT_TOKENS_EST
    attempts, mutation_max = cfg["mutation"]["max_attempts"], cfg["models"]["mutation"]["max_tokens"]
    # attempt k replays the k − 1 rejected replies: PROMPT_TOKENS_EST + k · max_tokens (R10)
    make_child = attempts * PROMPT_TOKENS_EST + mutation_max * attempts * (attempts + 1) // 2
    seeding = (P - 1) * make_child
    eval_gen = P * K * run_cap
    children_gen = (P - 1) * 2 * make_child           # worst case: one survivor, every lineage redrawn once
    main_cap = cfg["budget"]["tokens_total"] - cfg["budget"]["holdout_reserve"]
    spent, largest, cap_needed, generations_fit = seeding, 0, 0, g_max
    for g in range(g_max):
        need = P * K * token_budget if g == 0 else largest * 3 // 2      # evolution._run's gate
        cap_needed = max(cap_needed, spent + need)
        if generations_fit == g_max and main_cap - spent < need:
            generations_fit = g
        cost = eval_gen + (children_gen if g < g_max - 1 else 0)
        spent += cost
        largest = max(largest, cost)
    main_cap_needed = max(cap_needed, spent)
    heldout_worst = mu * n_heldout * run_cap
    return {
        "prompt_tokens_est": PROMPT_TOKENS_EST, "subagent_call": subagent_call, "run_cap": run_cap,
        "mutation_call": mutation_call, "make_child": make_child, "seeding": seeding,
        "eval_per_generation": eval_gen, "children_per_generation": children_gen,
        "g_max": g_max, "main_worst": spent, "main_cap": main_cap, "main_cap_needed": main_cap_needed,
        "generations_fit": generations_fit, "heldout_runs": mu * n_heldout, "heldout_worst": heldout_worst,
        "holdout_reserve": cfg["budget"]["holdout_reserve"], "tokens_total": cfg["budget"]["tokens_total"],
        "tokens_total_needed": main_cap_needed + heldout_worst,
    }


def format_estimate(e: dict) -> str:
    fits = e["generations_fit"] == e["g_max"]
    held_ok = e["heldout_worst"] <= e["holdout_reserve"]
    lines = [
        "worst case: every call hits its cap; real runs cost less (compare with a probe's tokens per task run)",
        f"per call: subagent {e['subagent_call']:,} · mutation {e['mutation_call']:,}"
        f" (max_tokens + {e['prompt_tokens_est']:,} prompt tokens, estimated)",
        f"per task run: {e['run_cap']:,} · per child: {e['make_child']:,} · seeding: {e['seeding']:,}",
        f"per generation: {e['eval_per_generation']:,} task runs + {e['children_per_generation']:,} mutation"
        " (none in the last generation)",
        f"main phase: {e['main_worst']:,} for {e['g_max']} generations; the budget gate needs a cap of"
        f" {e['main_cap_needed']:,}; cap is {e['main_cap']:,} (tokens_total − holdout_reserve)",
        ("main phase: fits, all generations run" if fits else
         f"main phase: the gate may stop the run after {e['generations_fit']} of {e['g_max']} generations"),
        f"held-out: {e['heldout_runs']} task runs, {e['heldout_worst']:,}; reserve {e['holdout_reserve']:,}"
        + (" (fits)" if held_ok else " (short: held-out runs can only use what the main phase left)"),
        f"for no early stop: tokens_total ≥ {e['tokens_total_needed']:,} with holdout_reserve ≥"
        f" {e['heldout_worst']:,} (now {e['tokens_total']:,} and {e['holdout_reserve']:,})",
    ]
    return "\n".join(lines) + "\n"
