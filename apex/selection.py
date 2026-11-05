"""Selection at a cycle's end, on the connector's cycle scores. Pure code, no model.

- ranking: by score, high first; ties go to the smaller agent id in natural order (g0-2 before g0-10); a score
  that isn't a finite number (bool, None, text, NaN, inf, too big for a float) ranks last.
- survivors: the top `operation.survivors` with a finite score (kept unchanged into the next generation).
- bases: agents with score >= avg + base_margin * |avg| (the "120% of the average", safe for a negative average).
  If nobody passes, the survivors are the bases (bases_fallback = True), so Mutation always has a parent.
- below: everyone not in bases, in rank order.
- parent_penalty: before ranking, an agent that did worse than its parents loses
  worse_child_penalty * max(|avg|, max - min), so it is kept less easily.
"""
import math
import re


def _score(s) -> float:
    if isinstance(s, bool) or not isinstance(s, (int, float)):
        return -math.inf
    try:
        f = float(s)
    except OverflowError:
        return -math.inf
    return f if math.isfinite(f) else -math.inf


def natural_key(agent_id: str) -> tuple:
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"(\d+)", str(agent_id)))


def select(scores: dict, cfg: dict) -> dict:
    op = cfg["operation"]
    clean = {a: _score(s) for a, s in scores.items()}
    ranking = sorted(clean, key=lambda a: (-clean[a], natural_key(a)))
    finite = [s for s in clean.values() if math.isfinite(s)]
    avg = sum(s / len(finite) for s in finite) if finite else 0.0      # divide first: no overflow to inf
    threshold = avg + op["base_margin"] * abs(avg)
    survivors = [a for a in ranking if math.isfinite(clean[a])][: op["survivors"]]
    bases = [a for a in ranking if math.isfinite(clean[a]) and clean[a] >= threshold]
    fallback = not bases
    if fallback:
        bases = list(survivors)
    return {"ranking": ranking, "survivors": survivors, "bases": bases,
            "below": [a for a in ranking if a not in bases], "avg": avg, "threshold": threshold,
            "bases_fallback": fallback, "scores": {a: scores[a] for a in ranking}}


def _per_step(agent_id: str, history: list):
    """Mean score per step over the agent's finished cycles, or None."""
    total = steps = 0.0
    for entry in history:
        s = _score(entry["scores"].get(agent_id))
        if math.isfinite(s):
            total += s
            steps += entry["steps"]
    return total / steps if steps else None


def parent_penalty(scores: dict, parents: dict, steps: int, history: list, cfg: dict):
    """(adjusted scores, flags). An agent with parents is worse when its score is below its best parent's in this
    cycle; when no parent ran this cycle, when its score per step is below its best parent's mean per step over
    the parent's life (`history`: [{steps, scores}] of earlier cycles). A worse agent loses the penalty."""
    clean = {a: _score(s) for a, s in scores.items()}
    finite = [s for s in clean.values() if math.isfinite(s)]
    adjusted, flags = dict(scores), {}
    if not finite:
        return adjusted, flags
    avg = sum(s / len(finite) for s in finite)
    spread = max(finite) - min(finite)
    if not math.isfinite(spread):                      # scores near ±1e308: half the spread still ranks the same
        spread = max(finite) / 2 - min(finite) / 2
    penalty = cfg["operation"]["worse_child_penalty"] * max(abs(avg), spread)
    for agent_id, own in clean.items():
        mine = [p for p in parents.get(agent_id) or [] if p != agent_id]
        if not mine or not math.isfinite(own):
            continue
        alive = [clean[p] for p in mine if p in clean and math.isfinite(clean[p])]
        if alive:
            ref, value, basis = max(alive), own, "same_cycle"
        else:
            means = [m for m in (_per_step(p, history) for p in mine) if m is not None]
            if not means or steps < 1:
                continue
            ref, value, basis = max(means), own / steps, "per_step"
        if value < ref:
            adjusted[agent_id] = own - penalty
            flags[agent_id] = {"score": own, "ref": ref, "basis": basis, "penalty": penalty}
    return adjusted, flags
