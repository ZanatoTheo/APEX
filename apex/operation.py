"""The operation: Op. Orch's code that drives the connector and the agents.

One loop = all of the connector's steps once, split into cycles. Per step: release → test every agent → each agent
works (one after another, or up to operation.parallel_agents at the same time) → summary.
Per cycle end: scores → selection → Eval, then either the final pick (the run's
last cycle) or Mutation → next generation → cleaner. After the last cycle of a loop it wraps to the first.
With a held-out connector, a copy of the picked agent then walks its steps once, with no evolution.
"""
import json
import math
import os
import shutil
import stat
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .agent import DATA_HEADER, Agent
from .budget import CapReached, CycleBudget
from .call_agent import call_agent
from .cleaner import Cleaner
from .connector import cycle_steps, target_score
from .evaluator import Evaluator
from .mutation import Mutation
from .orchestrator import Orchestrator
from .prompts import report_numbers
from .runlog import RunLog
from .selection import parent_penalty, select
from .summarizer import Summarizer


def split_cycles(n_steps: int, k: int) -> list[list[int]]:
    """Steps 0..n-1 in cycles of k. A remainder shorter than half a cycle joins the last cycle; else its own."""
    if n_steps < 1 or k < 1:
        raise ValueError(f"need n_steps >= 1 and k >= 1, got {n_steps}, {k}")
    full, rest = divmod(n_steps, k)
    lengths = [k] * full
    if not lengths:
        lengths = [n_steps]
    elif rest and 2 * rest < k:
        lengths[-1] += rest
    elif rest:
        lengths.append(rest)
    out, start = [], 0
    for length in lengths:
        out.append(list(range(start, start + length)))
        start += length
    return out


def loop_scores(history: list, n_steps: int) -> dict:
    """{agent id: its finite cycle scores summed over the run, scaled to one loop of n_steps}."""
    total, steps = {}, {}
    for entry in history:
        for agent_id, s in entry["scores"].items():
            if isinstance(s, bool) or not isinstance(s, (int, float)) or not math.isfinite(s):
                continue
            total[agent_id] = total.get(agent_id, 0.0) + s
            steps[agent_id] = steps.get(agent_id, 0) + entry["steps"]
    out = {a: total[a] / steps[a] * n_steps for a in total if steps[a]}
    return {a: s for a, s in out.items() if math.isfinite(s)}       # an overflowing sum never reaches a stop check


STOP_FILE = "STOP"                                    # run.py stop writes it in the run folder


class UserStop(Exception):
    """The STOP file appeared in the run folder."""


class TimeUp(Exception):
    """operation.max_minutes passed in the middle of a cycle."""


def _cycle_capped(budget_events: list) -> bool:
    """Per-agent caps (call_tokens, turns, subagent pool) end one agent's step; only cycle_usd stops the run."""
    return any(e.get("event") == "cap" and e.get("kind") == "cycle_usd" for e in budget_events)


class Operation:
    def __init__(self, cfg: dict, connector, model, run_dir, budget=None, progress=None, holdout=None,
                 clock=time.monotonic):
        self.cfg, self.connector, self.model = cfg, connector, model
        self.clock = clock                   # seconds; injectable for tests (max_minutes)
        self._t0 = None                      # clock() when training starts
        self.holdout = holdout               # a second connector with held-out data, or None
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "config.json").write_text(json.dumps(cfg, indent=1))
        self.budget = budget or CycleBudget(cfg)
        hidden = self.run_dir / "hidden"
        self.orch = Orchestrator(cfg, self.budget, model, self.run_dir)
        self.summarizer = Summarizer(cfg, self.budget, model)
        self.evaluator = Evaluator(cfg, self.budget, model, hidden)
        self.mutation = Mutation(cfg, self.budget, model, hidden)
        self.cleaner = Cleaner(cfg, self.budget, model, hidden)
        self.log = RunLog(self.run_dir / "log.jsonl")
        self.progress = progress or (lambda line: None)
        self.history = []                    # [{loop, cycle, steps, scores}], one per finished cycle
        self._advice = {}                    # {agent id: {score, weaknesses}} for its next step
        self.n_steps = self.loop = self.cycle = 0
        self.target, self.target_source = None, "orch"

    # ---- the loop: read this first ------------------------------------------------------------------------------
    def run(self, seeds_dir=None) -> dict:
        result = self._train(seeds_dir)                       # an error stop raises: no held-out check
        if self.holdout is not None:
            result["holdout"] = (self.holdout_check(result["selected"]) if result["selected"]
                                 else {"skipped": "no agent was selected"})
            try:                                              # a write failure never loses training's result
                (self.run_dir / "final.json").write_text(json.dumps(result, indent=1))
                self.log.drain(self.budget)
                self.log.event("holdout_end", **result["holdout"])
            except Exception as e:
                result["holdout"]["write_error"] = f"{type(e).__name__}: {e}"[:300]
                try:
                    (self.run_dir / "final.json").write_text(json.dumps(result, indent=1))
                except Exception:
                    pass
        return result

    def _train(self, seeds_dir) -> dict:
        self.n_steps = self.connector.n_steps()
        cycles = split_cycles(self.n_steps, cycle_steps(self.connector, self.cfg))
        max_loops = self.cfg["operation"]["max_loops"]
        max_cycles = self.cfg["operation"].get("max_cycles")
        max_minutes = self.cfg["operation"].get("max_minutes")
        self._t0 = mark = self.clock()             # mark: the last cycle end (or the start)
        self.log.event("run_start", n_steps=self.n_steps, cycles=[len(c) for c in cycles], max_loops=max_loops,
                       max_cycles=max_cycles, max_minutes=max_minutes, agents=self.cfg["operation"]["agents"])
        selection, notes = None, {}
        try:
            self.start(seeds_dir)
            for loop in range(1, max_loops + 1):
                self.loop = loop
                for i, steps in enumerate(cycles):
                    self.cycle += 1
                    self.begin_cycle()
                    for step in steps:
                        self.run_step(step)
                    self._check_time()                    # Eval is several model calls
                    selection, notes = self.score_cycle(steps)
                    reason = None
                    if i == len(cycles) - 1:                  # the loop's last cycle
                        reason = self.loop_end(last_loop=loop == max_loops)
                    if reason is None and self.cycle == max_cycles:
                        reason = "max_cycles"
                    if reason is None and max_minutes is not None:   # would the next generation + cycle fit?
                        now = self.clock()                 # now - mark: this cycle and the generation before it
                        if (now - self._t0) + (now - mark) > max_minutes * 60:
                            reason = "time_limit"
                        mark = now
                    if reason:
                        return self.finish(reason, selection, notes)
                    self.next_generation(selection, notes)
                    self._advice = self._advice_for(notes)
            raise AssertionError("unreachable: the last loop always ends the run")
        except CapReached as e:
            return self.finish(f"budget:{e.kind}", selection, notes, ask=False)
        except UserStop:                                  # run.py stop: like TimeUp, fallback pick
            return self.finish("stopped_by_user", selection, notes, ask=False)
        except TimeUp:                                    # mid-cycle: that cycle isn't scored, no model call
            return self.finish("time_limit", selection, notes, ask=False)
        except Exception as e:
            self.log.drain(self.budget)
            self.log.event("stop", reason=f"error: {type(e).__name__}: {e}"[:500], loops=self.loop,
                           cycles=self.cycle)
            raise

    # ---- the parts, in the order they run -----------------------------------------------------------------------
    def start(self, seeds_dir) -> None:
        agents = self.orch.start(self.connector, seeds_dir)
        target = target_score(self.connector)
        if target is not None:
            self.target, self.target_source = target, "connector"
        else:
            self.target = self.orch.stop_threshold
        self.log.event("gen0", ids=[a.id for a in agents], target=self.target, target_source=self.target_source)

    def begin_cycle(self) -> None:
        if self.cycle > 1:
            self.budget.new_cycle()
        self.connector.begin_cycle([a.id for a in self.orch.agents])

    def run_step(self, step: int) -> None:
        agents = list(self.orch.agents)
        self.connector.release(step)
        reports, errors = {}, {}
        for a in agents:                                      # test every agent's work on the released step
            try:
                reports[a.id] = self.connector.run_step(a.id, a.dir, step)
            except Exception as e:
                reports[a.id], errors[a.id] = {}, f"{type(e).__name__}: {e}"[:300]
        results = {}
        workers = self.cfg["operation"]["parallel_agents"]
        if workers <= 1:
            for a in agents:                                  # then each agent works, one after another
                self._check_time()
                results[a.id] = {"report": reports[a.id],
                                 "call": call_agent(a, reports[a.id], step, self.connector, self.budget, self.model,
                                                    advice=self._advice.pop(a.id, None))}
        else:             # or up to `workers` at the same time (budget counters aren't locked: a few calls can pass cycle_usd)
            self._check_time()
            advice = {a.id: self._advice.pop(a.id, None) for a in agents}
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {a.id: pool.submit(call_agent, a, reports[a.id], step, self.connector, self.budget,
                                             self.model, advice=advice[a.id]) for a in agents}
            errors_seen = []                                  # every agent finished: now raise the first error
            for a in agents:
                try:
                    results[a.id] = {"report": reports[a.id], "call": futures[a.id].result()}
                except BaseException as e:
                    errors_seen.append(e)
            if errors_seen:
                raise errors_seen[0]
        summary = self.summarizer.summarize(agents, step, results)
        self.orch.log({"event": "step_summary", "cycle": self.cycle, "step": step, "summary": summary})
        self.log.event("step", loop=self.loop, cycle=self.cycle, step=step, errors=errors, summary=summary,
                       agents={a: {"ended_by": r["call"]["ended_by"], "turns": r["call"]["turns"],
                                   "report": report_numbers(r["report"])} for a, r in results.items()})
        self._stop_on_cap()                                   # an agent or the summarizer ran out of dollars

    def score_cycle(self, steps: list) -> tuple[dict, dict]:
        agents = list(self.orch.agents)
        scores = {a.id: self.connector.cycle_score(a.id) for a in agents}
        adjusted, flags = parent_penalty(scores, {a.id: a.parents for a in agents}, len(steps), self.history,
                                         self.cfg)
        self.history.append({"loop": self.loop, "cycle": self.cycle, "steps": len(steps), "scores": scores})
        selection = select(adjusted, self.cfg)
        selection["worse_than_parents"] = flags
        notes = self.evaluator.judge(self.cycle, agents, scores, self.connector.brief(), axes=self.orch.axes)
        self.log.event("cycle_end", loop=self.loop, cycle=self.cycle, steps=len(steps), scores=scores,
                       worse_than_parents=flags, survivors=selection["survivors"], bases=selection["bases"],
                       eval_errors=sum(1 for n in notes.values() if "error" in n))
        self.progress(f"loop {self.loop} cycle {self.cycle} (steps {steps[0]}-{steps[-1]}): "
                      f"best {selection['ranking'][0]} {scores[selection['ranking'][0]]}, "
                      f"spent ${self.budget.spent_usd:.4f}")
        self._stop_on_cap()                                   # Eval ran out of dollars: no new generation
        return selection, notes

    def loop_end(self, last_loop: bool) -> str | None:
        """The stop reason after a loop's last cycle, or None to go on."""
        scores = loop_scores(self.history, self.n_steps)
        best = max(scores, key=scores.get) if scores else None
        value = scores.get(best)
        self.log.event("loop_end", loop=self.loop, loop_score=value, best=best, target=self.target)
        if value is not None and self.target is not None and value >= self.target:
            return "threshold"
        return "max_loops" if last_loop else None

    def next_generation(self, selection: dict, notes: dict) -> None:
        mutation = self.mutation.run(self.cycle, self.orch.agents, notes, selection, self.connector.brief(),
                                     self.orch.axes)
        before = {a.id for a in self.orch.agents}
        agents = self.orch.next_generation(self.cycle, self.connector, selection, notes, mutation)
        self.log.event("generation", cycle=self.cycle, generation=self.orch.generation, ids=[a.id for a in agents],
                       kept=[a.id for a in agents if a.id in before], new=[a.id for a in agents if a.id not in before],
                       mutation_error=mutation.get("error"))
        rules = self.connector.cleaning_rules()
        deletions = self.cleaner.clean_all(self.cycle, agents, rules)
        undone = self.orch.review_deletions(self.cycle, deletions, self.cleaner)
        for a in agents:
            self._fresh_data_file(a)
        self.log.event("cleaner", cycle=self.cycle, deletions=[d["id"] for d in deletions], undone=undone)
        self.log.drain(self.budget)

    def finish(self, reason: str, selection, notes: dict, ask: bool = True) -> dict:
        scores = loop_scores(self.history, self.n_steps)
        if ask and selection is not None:
            pick = self.orch.final_review(self.cycle, selection, notes, scores, self.target, self.target_source)
            if _cycle_capped(self.log.drain(self.budget)):   # the final pick itself ran out of dollars
                reason = "budget:cycle_usd"
        else:                                                 # a budget stop: no model call
            selected = self.orch.fallback_pick(scores, selection)
            pick = {"selected": selected, "report": "", "fallback": True,
                    "why": "fallback: best loop score" if selected else "fallback: no agent was scored"}
            self.orch.log({"event": "final", "cycle": self.cycle, **pick})
        result = {"reason": reason, **pick, "loop_score": scores.get(pick["selected"]), "target": self.target,
                  "target_source": self.target_source, "loops": self.loop, "cycles": self.cycle}
        (self.run_dir / "final.json").write_text(json.dumps(result, indent=1))
        self.log.drain(self.budget)
        self.log.event("stop", **result)
        return result

    # ---- the held-out check -------------------------------------------------------------------------------------
    def holdout_check(self, agent_id: str) -> dict:
        """A copy of the picked agent walks every held-out step once: per step the held-out connector tests it, then
        it works (call_agent). One cleaner call cleans the copy; no Summarizer, Eval, Mutation or Op. Orch call.
        Never raises: training's result stays. `passed` is set only after a full walk with no step error."""
        h = self.holdout
        out = {"agent": agent_id, "loop_score": None, "target": None, "target_source": "none", "passed": None,
               "cycles": 0, "steps_done": 0, "n_steps": None, "step_errors": 0, "skipped_files": [],
               "stopped": "done"}
        history, open_steps = [], 0                           # open_steps: steps of a cycle not yet scored
        try:
            self.log.event("holdout_start", agent=agent_id)
            out["n_steps"] = h.n_steps()
            cycles = split_cycles(out["n_steps"], cycle_steps(h, self.cfg))
            target = target_score(h)
            if target is not None:
                out["target"], out["target_source"] = target, "connector"
            agent, out["skipped_files"] = self._holdout_copy(agent_id)
            self.budget.new_cycle()
            deletions = self.cleaner.clean_all(self.cycle + 1, [agent], h.cleaning_rules())
            self._fresh_data_file(agent)
            self.log.event("holdout_cleaner", agent=agent_id, deletions=[d["id"] for d in deletions])
            for i, steps in enumerate(cycles):
                if i:
                    self.budget.new_cycle()
                h.begin_cycle([agent.id])
                out["cycles"] += 1
                for step in steps:
                    h.release(step)
                    error = None
                    try:
                        report = h.run_step(agent.id, agent.dir, step)
                    except Exception as e:
                        report, error = {}, f"{type(e).__name__}: {e}"[:300]
                        out["step_errors"] += 1
                    call = call_agent(agent, report, step, h, self.budget, self.model)
                    out["steps_done"] += 1
                    open_steps += 1
                    self.log.event("holdout_step", agent=agent.id, cycle=out["cycles"], step=step, error=error,
                                   ended_by=call["ended_by"], turns=call["turns"], report=report_numbers(report))
                    self._stop_on_cap()
                history.append({"steps": open_steps, "scores": {agent.id: h.cycle_score(agent.id)}})
                open_steps = 0
        except CapReached as e:
            out["stopped"] = f"budget:{e.kind}"
        except Exception as e:
            out["stopped"] = f"error: {type(e).__name__}: {e}"[:500]
        if open_steps:                                        # a cut cycle is scored the same way after any stop
            try:
                history.append({"steps": open_steps, "scores": {agent_id: h.cycle_score(agent_id)}})
            except Exception:
                pass
        if out["n_steps"]:
            out["loop_score"] = loop_scores(history, out["n_steps"]).get(agent_id)
        complete = out["stopped"] == "done" and out["steps_done"] == out["n_steps"] and not out["step_errors"]
        if complete and out["loop_score"] is not None and out["target"] is not None:
            out["passed"] = out["loop_score"] >= out["target"]
        return out

    def _holdout_copy(self, agent_id: str) -> tuple[Agent, list]:
        """The picked agent's folder copied to <run>/holdout/agents/<id>, with an empty log beside it. Links stay
        links; special files (a FIFO would block the copy) are left out; entries that can't be read (an agent may
        chmod them) are skipped and listed. The training folder is never touched, not even chmod-ed."""
        src = next((a for a in self.orch.agents if a.id == agent_id), None)
        if src is None:
            raise ValueError(f"no current agent {agent_id}")

        def special(folder, names):
            skip = []
            for name in names:
                mode = os.lstat(os.path.join(folder, name)).st_mode
                if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode) or stat.S_ISLNK(mode)):
                    skip.append(name)
            return skip

        root = self.run_dir / "holdout"
        folder, log_path = root / "agents" / agent_id, root / "logs" / f"{agent_id}.jsonl"
        skipped = []
        try:
            shutil.copytree(src.dir, folder, symlinks=True, ignore=special)
        except shutil.Error as e:                             # the rest is copied; these entries are not
            skipped = sorted({str(Path(row[0]).relative_to(src.dir)) for row in e.args[0]
                              if Path(row[0]).is_relative_to(src.dir) and Path(row[0]) != src.dir})
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("")
        return Agent(agent_id, folder, log_path, src.axioms, src.data_file, src.generation, list(src.parents)), skipped

    # ---- helpers ------------------------------------------------------------------------------------------------
    def _advice_for(self, notes: dict) -> dict:
        """Each agent still here whose last cycle score is below operation.advice_below: its own Eval weaknesses."""
        limit = self.cfg["operation"].get("advice_below")
        if limit is None or not self.history:
            return {}
        scores, out = self.history[-1]["scores"], {}
        for a in self.orch.agents:
            s, weak = scores.get(a.id), (notes.get(a.id) or {}).get("weaknesses")
            if isinstance(s, (int, float)) and s < limit and isinstance(weak, list) and weak:
                out[a.id] = {"score": s, "weaknesses": [str(w) for w in weak][:8]}
        return out

    def _check_time(self) -> None:
        """Raise UserStop if the STOP file exists; TimeUp once operation.max_minutes has passed."""
        if (self.run_dir / STOP_FILE).exists():
            raise UserStop("STOP file")
        limit = self.cfg["operation"].get("max_minutes")
        if limit is not None and self._t0 is not None and self.clock() - self._t0 >= limit * 60:
            raise TimeUp(f"{limit} min passed")

    def _stop_on_cap(self) -> None:
        """Write the budget's new events to the run log; stop the run if the cycle's dollars ran out. (Eval and the
        summarizer turn a cap into a note, and an agent into `cap:cycle_usd`, so the loop checks here.)"""
        if _cycle_capped(self.log.drain(self.budget)):
            raise CapReached("cycle_usd", "the cycle's dollars ran out")

    def _fresh_data_file(self, agent) -> None:
        """Every cycle starts with an empty data file (the cleaner deleted the old one)."""
        path = agent.dir / agent.data_file
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
        except FileExistsError:
            return                                            # Op. Orch undid its deletion: leave it
        with os.fdopen(fd, "w") as f:
            f.write(DATA_HEADER)
