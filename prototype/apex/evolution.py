"""Evolution loop (design §10; CODE_STRUCTURE §5.2, §5.5): patches, UCB1, mutation, seeding, the generation loop.

Selection and mutation see only PublicResult objects and blobs/; hidden results reach the ledger as hashes.
"""
import copy
import itertools
import json
import math
import random
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config as config_mod
from . import corpus, evaluation, prompts
from .agent import Agent, GraphError, validate_axioms, validate_graph
from .ledger import ROOT, Ledger
from .models import Budget, ModelClient, ModelError, load_service


class PatchError(ValueError):
    pass


# -- mutation units ----------------------------------------------------------------------------------------

def _pointer(path) -> list[str]:
    if not isinstance(path, str) or not path.startswith("/"):
        raise PatchError(f"path {path!r} must be a JSON pointer starting with /")
    return [t.replace("~1", "/").replace("~0", "~") for t in path[1:].split("/")]


def _index(token: str, size: int) -> int:
    if not token.isdigit() or (token != "0" and token.startswith("0")) or int(token) >= size:
        raise PatchError(f"list index {token!r} out of range")
    return int(token)


def _walk(doc, tokens):
    for tok in tokens:
        if isinstance(doc, list):
            doc = doc[_index(tok, len(doc))]
        elif isinstance(doc, dict) and tok in doc:
            doc = doc[tok]
        else:
            raise PatchError(f"path segment {tok!r} does not exist")
    return doc


def apply_json_patch(doc, ops: list) -> dict:
    """RFC 6902 subset: add, remove, replace (JC-35). Returns a new document."""
    doc = copy.deepcopy(doc)
    for op in ops:
        if not isinstance(op, dict):
            raise PatchError("each operation must be an object")
        kind = op.get("op")
        if kind not in ("add", "remove", "replace"):
            raise PatchError(f"unsupported op {kind!r}: use add, remove or replace")
        if kind != "remove" and "value" not in op:
            raise PatchError(f"{kind} needs a value")
        tokens = _pointer(op.get("path"))
        if tokens == [""] or not tokens:
            raise PatchError("cannot replace the whole document")
        parent, last = _walk(doc, tokens[:-1]), tokens[-1]
        if isinstance(parent, list):
            if kind == "add":
                parent.insert(len(parent) if last == "-" else _index(last, len(parent) + 1), copy.deepcopy(op["value"]))
            elif kind == "remove":
                parent.pop(_index(last, len(parent)))
            else:
                parent[_index(last, len(parent))] = copy.deepcopy(op["value"])
        elif isinstance(parent, dict):
            if kind != "add" and last not in parent:
                raise PatchError(f"key {last!r} does not exist")
            if kind == "remove":
                del parent[last]
            else:
                parent[last] = copy.deepcopy(op["value"])
        else:
            raise PatchError(f"cannot {kind} inside a scalar")
    return doc


def apply_axiom_edit(axioms: list, ops: list) -> list:
    """axiom_edit (design §16): {op: add|replace|remove, index, text}. Returns a new list."""
    out = list(axioms)
    for op in ops:
        if not isinstance(op, dict):
            raise PatchError("each operation must be an object")
        kind, index, text = op.get("op"), op.get("index"), op.get("text")
        if not isinstance(index, int) or isinstance(index, bool):
            raise PatchError("index must be an integer")
        if kind == "add":
            if not 0 <= index <= len(out) or not isinstance(text, str):
                raise PatchError(f"add needs 0 <= index <= {len(out)} and a text")
            out.insert(index, text)
        elif kind in ("replace", "remove"):
            if not 0 <= index < len(out):
                raise PatchError(f"{kind} index {index} out of range 0..{len(out) - 1}")
            if kind == "replace":
                if not isinstance(text, str):
                    raise PatchError("replace needs a text")
                out[index] = text
            else:
                out.pop(index)
        else:
            raise PatchError(f"unsupported axiom op {kind!r}")
    return out


# -- UCB1 over lineages ------------------------------------------------------------------------------------

class UCB1:
    """Arm = lineage; a visit = a child produced; reward = the child's L1 (0 if it fails L0), credited when the
    child is evaluated in the next generation (JC-30). Picks within one call count as pending visits."""

    def __init__(self, c_ppm: int):
        self.c = c_ppm / 1_000_000
        self.visits: dict[str, int] = {}
        self.reward_ppm: dict[str, int] = {}

    def credit(self, lineage: str, reward_ppm: int):
        self.visits[lineage] = self.visits.get(lineage, 0) + 1
        self.reward_ppm[lineage] = self.reward_ppm.get(lineage, 0) + reward_ppm

    def score(self, lineage: str, pending: dict) -> float:
        n = self.visits.get(lineage, 0) + pending.get(lineage, 0)
        if n == 0:
            return math.inf
        total = sum(self.visits.values()) + sum(pending.values())
        mean = self.reward_ppm.get(lineage, 0) / 1_000_000 / self.visits[lineage] if self.visits.get(lineage) else 0.0
        return mean + self.c * math.sqrt(math.log(total) / n)

    def pick(self, k: int, lineages: list[str], exclude=()) -> list[str]:
        order = sorted(set(lineages) - set(exclude)) or sorted(set(lineages))   # exclude unless it empties the arms
        pending: dict[str, int] = {}
        picks = []
        for _ in range(k):
            best = max(order, key=lambda lin: (self.score(lin, pending), -order.index(lin)))   # ties: lowest id
            picks.append(best)
            pending[best] = pending.get(best, 0) + 1
        return picks


# -- mutation ----------------------------------------------------------------------------------------------

def pick_trace(result: evaluation.PublicResult) -> evaluation.TaskPublic:
    """JC-31: the worst public run (lowest pass rate, then most tokens); if all passed, the most expensive."""
    if all(t.total and t.passed == t.total for t in result.tasks):
        return max(result.tasks, key=lambda t: t.run.tokens)
    return min(result.tasks, key=lambda t: (t.pass_ppm, -t.run.tokens))


def trace_excerpt(tp: evaluation.TaskPublic, blobs, last_steps: int = 6) -> str:
    """Built from blobs/ only, never blobs-holdout/ (CODE_STRUCTURE §5.5)."""
    lines = [f"Task {tp.task_id}: public tests passed {tp.passed}/{tp.total}; run outcome {tp.run.outcome}; "
             f"tokens {tp.run.tokens}."]
    for t in tp.run.transitions[-(last_steps + 2):]:
        rec = blobs.get(t["result_hash"])
        if t["action"].startswith("llm:"):
            lines.append(f"[{t['action']}] model replied: {rec['response']['text'][:400]}")
        elif t["action"].startswith("tool:"):
            lines.append(f"[{t['action']}] → {rec['status']}: {rec['output'][:400]}")
        elif t["action"] == "eval:public":
            lines.append(f"[public test run] L0 failures: {rec['l0_failures'] or 'none'}\n{rec['test_output'][:3000]}")
    return "\n".join(lines)


def make_child(parent: Agent, parent_result, child_id: str, generation: int, lineage_id: str, client, cfg: dict,
               rng_scopes: random.Random, blobs, cite: tuple[str, str]):
    """One child = one in-place edit of one unit (design §10). Returns (child, proposal record) or None."""
    mcfg = cfg["mutation"]
    if parent_result is not None:
        tp = pick_trace(parent_result)
        excerpt, cite = trace_excerpt(tp, blobs), (tp.block_hash, tp.run.transitions[-1]["result_hash"])
    else:
        excerpt = "No runs yet: this is generation-0 seeding. Propose one plausible improvement."
    scope = rng_scopes.choice(mcfg["scopes"])
    unit = parent.graph if scope == "graph_config" else parent.axioms
    errors, attempts, calls, payload, new_unit = [], [], [], None, None
    for _ in range(mcfg["max_attempts"]):
        payload = None   # the record must describe the last attempt, not an earlier one
        messages = prompts.mutation_messages(scope, unit, excerpt, mcfg, attempts)
        try:
            completion = client.complete("mutation", messages)
        except ModelError as e:
            errors.append(f"model call failed: {e}")
            break
        calls.append(completion.record_hash)
        try:
            payload = prompts.parse_mutation(completion.text, scope)
            if len(payload["content"]) > mcfg["max_patch_ops"]:
                raise PatchError(f"{len(payload['content'])} operations exceed max_patch_ops={mcfg['max_patch_ops']}")
            if scope == "graph_config":
                new_unit = apply_json_patch(unit, payload["content"])
                validate_graph(new_unit, len(parent.axioms))
            else:
                new_unit = apply_axiom_edit(unit, payload["content"])
                validate_axioms(new_unit, mcfg["max_axioms"], mcfg["max_axiom_chars"])
                validate_graph(parent.graph, len(new_unit))       # axiom_refs must still resolve
            if new_unit == unit:
                raise PatchError("the edit changes nothing")
            break
        except (prompts.ParseError, PatchError, GraphError) as e:
            errors.append(str(e))
            attempts.append((completion.text, str(e)))
            new_unit = None
    record = {"proposal_id": f"p-{child_id}", "parent_agent_id": parent.agent_id, "child_agent_id": child_id,
              "causal_attribution_id": f"c-{child_id}", "mutation_scope": scope,
              "patch_payload": {"format": payload["format"] if payload else None,
                                "content": json.dumps(payload["content"]) if payload else None},
              "generator_model": cfg["models"]["mutation"]["model_id"], "rationale": payload["rationale"] if payload else "",
              "model_calls": calls, "validation_errors": errors, "accepted": new_unit is not None,
              "attribution": {"attribution_id": f"c-{child_id}", "block_hash": cite[0],
                              "step_identifier": "eval:public" if parent_result is not None else "seeding",
                              "empirical_evidence_link": cite[1]}}
    if new_unit is None:
        return None, record
    graph, axioms = (new_unit, parent.axioms) if scope == "graph_config" else (parent.graph, new_unit)
    child = Agent(child_id, lineage_id, parent.agent_id if parent_result is not None else None, generation,
                  copy.deepcopy(graph), list(axioms))
    return child, record


# -- the run -----------------------------------------------------------------------------------------------

def _evaluate_population(pop, batch, client, ledger, holdout_dir, cfg, work_root):
    jobs = [(a, t) for a in pop for t in batch]
    with ThreadPoolExecutor(max_workers=cfg["budget"]["max_concurrent"]) as pool:
        outs = list(pool.map(lambda j: evaluation.evaluate_task(j[0], j[1], client, ledger.blobs, ledger.holdout_blobs,
                                                                holdout_dir, cfg, work_root), jobs))
    per_agent = {a.agent_id: [] for a in pop}
    hidden = {a.agent_id: [] for a in pop}
    for (a, _), (tp, hidden_hash) in zip(jobs, outs):
        per_agent[a.agent_id].append(tp)
        hidden[a.agent_id].append(hidden_hash)
    return per_agent, hidden


def run(cfg: dict, run_dir: Path, log=print) -> dict:
    run_dir = Path(run_dir)
    ledger = Ledger(run_dir)
    try:
        return _run(cfg, run_dir, ledger, log)
    finally:
        ledger.close()
        shutil.rmtree(run_dir / "work", ignore_errors=True)


def _run(cfg: dict, run_dir: Path, ledger: Ledger, log) -> dict:
    work_root = run_dir / "work"
    seed, P, mu, K = cfg["run"]["seed"], cfg["population"]["P"], cfg["population"]["mu"], cfg["batch"]["K"]
    rng_batches, rng_scopes = random.Random(f"{seed}:batches"), random.Random(f"{seed}:scopes")
    budget = Budget(cfg["budget"]["tokens_total"], cfg["budget"]["holdout_reserve"])
    service = load_service(cfg)
    client = ModelClient(service, cfg, ledger.blobs, budget)
    public = corpus.load_public(config_mod.resolve_path(cfg, "corpus"))
    holdout_dir = config_mod.resolve_path(cfg, "holdout")
    seed_agent = json.loads(config_mod.resolve_path(cfg, "seed_agent").read_text(encoding="utf-8"))
    validate_axioms(seed_agent["axioms"], cfg["mutation"]["max_axioms"], cfg["mutation"]["max_axiom_chars"])
    validate_graph(seed_agent["graph"], len(seed_agent["axioms"]))
    put = ledger.blobs.put
    seed_hash = put(seed_agent)
    genesis = ledger.genesis([
        {"action": "config", "result_hash": put({"config": cfg})},
        {"action": "gate_definition", "result_hash": put(evaluation.GATES)},
        {"action": "public_manifest", "result_hash": put(corpus.manifest(public))},
        {"action": "holdout_manifest", "result_hash": put({"sha256": evaluation.holdout_manifest_hash(holdout_dir)})},
        {"action": "rng_seed", "result_hash": put({"seed": seed})},
        {"action": "seed_agent", "result_hash": seed_hash},
    ])
    counter = itertools.count()

    def new_id(g: int) -> str:
        return f"g{g}-a{next(counter):03d}"

    # Generation 0: the baseline plus P − 1 single mutations of it, each the root of its own lineage.
    base = Agent(new_id(0), "L00", None, 0, seed_agent["graph"], seed_agent["axioms"])
    pop, proposals = [base], []
    for i in range(1, P):
        child_id = new_id(0)
        child, record = make_child(base, None, child_id, 0, f"L{i:02d}", client, cfg, rng_scopes, ledger.blobs,
                                   (genesis["block_hash"], seed_hash))
        proposals.append(record)
        pop.append(child or Agent(child_id, f"L{i:02d}", None, 0, copy.deepcopy(base.graph), list(base.axioms)))
    for a in pop:
        a.branch_id = ledger.fork(genesis["block_hash"], a.agent_id)

    ucb = UCB1(cfg["ucb1"]["c_ppm"])
    prev_survivors, children_prev, generations = [], [], []
    largest_cost, stop = 0, "g_max reached"
    for g in range(cfg["run"]["g_max"]):
        need = P * K * cfg["limits"]["token_budget"] if g == 0 else largest_cost * 3 // 2
        if budget.available < need:
            stop = f"budget: {budget.available} tokens left, next generation may need {need}"
            break
        spent_before = budget.spent
        batch = corpus.sample(public, K, rng_batches)
        batch_hash = put({"generation": g, "tasks": [t.id for t in batch]})
        for a in pop:
            a.status = "evaluating"
        try:
            per_agent, hidden = _evaluate_population(pop, batch, client, ledger, holdout_dir, cfg, work_root)
        except Exception as e:   # atomic generations: any failure aborts the whole generation, recorded as such
            ledger.append("generation_event", ROOT, [
                {"action": "batch", "result_hash": batch_hash},
                {"action": "aborted", "result_hash": put({"generation": g, "reason": str(e)})}])
            ledger.publish_heads(g)
            stop = f"generation {g} aborted: {type(e).__name__}: {e}"
            break
        results = {}
        for a in pop:                                   # single writer: only this thread appends
            for tp in per_agent[a.agent_id]:
                tp.block_hash = ledger.append("agent_run", a.branch_id, tp.run.transitions)["block_hash"]
            results[a.agent_id] = evaluation.aggregate(a.agent_id, per_agent[a.agent_id], cfg)
        for child in children_prev:
            r = results[child.agent_id]
            ucb.credit(child.lineage_id, r.l1 if r.l0_passed else 0)

        ranked = sorted((a for a in pop if results[a.agent_id].l0_passed),
                        key=lambda a: (-results[a.agent_id].l1, results[a.agent_id].tokens,
                                       results[a.agent_id].tip_block_hash))
        rollback = not ranked
        if rollback and g == 0:
            for a in pop:
                a.status = "disqualified"
            stop = "all generation-0 seeds failed L0"
            survivors = []
        elif rollback:                                  # design §10: back to the previous survivors, new batch next
            survivors = prev_survivors
            for a in pop:
                a.status = "survived" if a in survivors else "disqualified"
        else:
            survivors = ranked[:mu]
            for a in pop:
                a.status = ("survived" if a in survivors else
                            "pruned" if results[a.agent_id].l0_passed else "disqualified")

        children, gen_proposals = [], list(proposals) if g == 0 else []
        last_generation = g == cfg["run"]["g_max"] - 1      # children made now would never be evaluated
        if survivors and stop == "g_max reached" and not last_generation:
            best_of = {}
            for a in survivors:                         # survivors are in rank order
                best_of.setdefault(a.lineage_id, a)
            for lineage in ucb.pick(P - len(survivors), list(best_of)):
                for attempt_lineage in (lineage, None):   # one redraw of another parent by UCB1 (C-78)
                    lin = attempt_lineage or ucb.pick(1, list(best_of), exclude=[lineage])[0]
                    parent = best_of[lin]
                    child_id = new_id(g + 1)
                    child, record = make_child(parent, results[parent.agent_id], child_id, g + 1, lin, client,
                                               cfg, rng_scopes, ledger.blobs, ("", ""))
                    gen_proposals.append(record)
                    if child is not None:
                        child.branch_id = ledger.fork(ledger.tip(parent.branch_id), child.agent_id)
                        children.append(child)
                        break

        fitness = {a.agent_id: evaluation.fitness_record(results[a.agent_id], g, batch_hash) for a in pop}
        transitions = [{"action": "batch", "result_hash": batch_hash}]
        transitions += [{"action": "fitness", "result_hash": put(fitness[a.agent_id])} for a in pop]
        transitions += [{"action": "hidden_fitness",
                         "result_hash": evaluation.write_hidden_fitness(fitness[a.agent_id], hidden[a.agent_id],
                                                                        ledger.holdout_blobs)} for a in pop]
        transitions += [{"action": "hidden_ref", "result_hash": h} for a in pop for h in hidden[a.agent_id]]
        transitions.append({"action": "selection", "result_hash": put({
            "generation": g, "rollback": rollback, "ranked": [a.agent_id for a in ranked],
            "survivors": [a.agent_id for a in survivors],
            "statuses": {a.agent_id: a.status for a in pop},
            "ucb1": {"visits": ucb.visits, "reward_ppm": ucb.reward_ppm}})})
        transitions += [{"action": "mutation_proposal", "result_hash": put(r)} for r in gen_proposals]
        transitions += [{"action": "agent", "result_hash": put(a.record())} for a in pop + children]
        ledger.append("generation_event", ROOT, transitions)
        heads = ledger.publish_heads(g)

        generations.append({
            "generation": g, "batch": [t.id for t in batch], "rollback": rollback,
            "results": {a.agent_id: {"lineage": a.lineage_id, "l0": results[a.agent_id].l0_passed,
                                     "l1_ppm": results[a.agent_id].l1, "pass_ppm": results[a.agent_id].pass_ppm,
                                     "tokens": results[a.agent_id].tokens, "status": a.status,
                                     "axioms": a.axioms, "has_verify": any(n.get("tool") == "run_tests"
                                                                           for n in a.graph["nodes"])}
                        for a in pop},
            "survivors": [a.agent_id for a in survivors],
            "children": [{"agent_id": r["child_agent_id"], "parent": r["parent_agent_id"], "scope": r["mutation_scope"],
                          "accepted": r["accepted"], "rationale": r["rationale"], "errors": len(r["validation_errors"])}
                         for r in gen_proposals],
            "tokens_spent": budget.spent, "heads": heads["tips"]})
        best = results[ranked[0].agent_id] if ranked else None
        log(f"gen {g}: batch {[t.id for t in batch]} best L1 {best.l1 / 1e6 if best else 0:.3f} "
            f"survivors {[a.agent_id for a in survivors]}{' (rollback)' if rollback else ''}")
        largest_cost = max(largest_cost, budget.spent - spent_before)
        if stop != "g_max reached":
            break
        prev_survivors, children_prev = survivors, children
        pop = survivors + children

    final = prev_survivors
    budget.holdout_phase = True
    heldout_client = ModelClient(service, cfg, ledger.holdout_blobs, budget)
    try:
        refs = evaluation.evaluate_heldout(final, holdout_dir, heldout_client, ledger.holdout_blobs, cfg, work_root)
    except evaluation.InfraError as e:
        refs, stop = [], stop + f"; held-out evaluation failed: {e}"
    ledger.append("generation_event", ROOT,
                  [{"action": "final_survivors", "result_hash": put([a.record() for a in final])}]
                  + [{"action": "heldout_run", "result_hash": r} for r in refs])
    ledger.publish_heads("final")
    summary = {"run_dir": str(run_dir), "seed": seed, "stop_reason": stop, "seed_agent": seed_agent,
               "generations": generations,
               "final_survivors": [a.record() for a in final], "heldout_refs": refs, "tokens_spent": budget.spent,
               "budget": {"tokens_total": budget.tokens_total, "holdout_reserve": budget.holdout_reserve}}
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary
