"""Op. Orch: deploys and supervises the agents and drives the connector.

Stance: see what the best agent is, not build the best agent. Its prompts hold only the connector's brief and
released information.
"""
import json
import math
import os
import re
import shutil
from pathlib import Path

from . import prompts
from .agent import Agent, _safe_rel
from .budget import CapReached
from .connector import cycle_steps
from .jsonreply import ask_json
from .selection import natural_key


class OrchestratorError(Exception):
    pass


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _axis_key(key) -> str:
    return key.split(":")[0].strip().lower() if isinstance(key, str) else ""


def axis_text(axioms: dict, axis: str):
    """The rule for `axis`. Keys match on the axis name before ':', ignoring case and spaces."""
    wanted = _axis_key(axis)
    for key, value in axioms.items():
        if _axis_key(key) == wanted and isinstance(value, str) and value.strip():
            return value
    return None


def render_draft(axes: list, draft: dict) -> str:
    return prompts.render_axioms(draft["name"], draft["approach"], {a: axis_text(draft["axioms"], a) for a in axes})


def rules_from_text(axes: list, text: str):
    """The joined rules of a rendered axioms.md ('## <axis>' sections), or None if an axis has no section."""
    sections, cur = {}, None
    for line in text.splitlines():
        if line.startswith("## "):
            cur = _axis_key(line[3:])
            sections[cur] = []
        elif cur is not None:
            sections[cur].append(line)
    rules = ["\n".join(sections.get(_axis_key(a), [])).strip() for a in axes]
    return " | ".join(rules) if all(rules) else None


def check_drafts(axes: list, drafts, need: int, taken: list[str]):
    """A problem with drafted agents (str), or None. `taken`: axioms texts they must differ from."""
    if not isinstance(drafts, list) or len(drafts) != need:
        got = len(drafts) if isinstance(drafts, list) else type(drafts).__name__
        return f"expected {need} agents, got {got}"
    seen = set()
    for t in taken:                          # a taken text counts as itself and as its rules
        seen.add(_norm(t))
        rules = rules_from_text(axes, t)
        if rules:
            seen.add(_norm(rules))
    names = set()
    for i, d in enumerate(drafts):
        if not isinstance(d, dict):
            return f"agent {i} must be an object"
        name, approach, axioms = d.get("name"), d.get("approach"), d.get("axioms")
        if not isinstance(name, str) or not name.strip() or not isinstance(approach, str) or not approach.strip():
            return f"agent {i} needs a non-empty name and approach"
        if not isinstance(axioms, dict):
            return f"agent {i} ({name}) needs an axioms object"
        missing = [a for a in axes if axis_text(axioms, a) is None]
        if missing:
            return f"agent {i} ({name}) has no rule for: {', '.join(missing)}"
        if _norm(name) in names:
            return f"agent names must be unique ({name})"
        names.add(_norm(name))
        keys = {_norm(" | ".join(axis_text(axioms, a).strip() for a in axes)), _norm(render_draft(axes, d))}
        if keys & seen:                      # same rules as another draft, or the same text as a seed's axioms.md
            return f"agent {i} ({name}) has the same axioms as another agent"
        seen |= keys
    return None


class Orchestrator:
    def __init__(self, cfg: dict, budget, model, run_dir):
        self.cfg, self.budget, self.model = cfg, budget, model
        self.op = cfg["operation"]
        self.axes = list(self.op["axes"])    # approved new axes are added here
        self.generation = 0
        self.all_agents: dict[str, Agent] = {}
        self.run_dir = Path(run_dir)
        self.agents_root = self.run_dir / "agents"
        self.logs_root = self.run_dir / "logs"
        self.orch_dir = self.run_dir / "orch"
        self.stop_threshold = None
        self.agents: list[Agent] = []

    def log(self, entry: dict) -> None:
        self.orch_dir.mkdir(parents=True, exist_ok=True)
        with open(self.orch_dir / "log.jsonl", "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")

    # ---- gen 0 ----------------------------------------------------------------------------------------------
    def _read_seeds(self, seeds_dir) -> list[dict]:
        root = Path(seeds_dir)
        if not root.is_dir():
            raise OrchestratorError(f"seeds folder {root} does not exist")
        limit = self.cfg["tools"]["max_file_chars"]

        def read(path: Path, label: str) -> str:
            if path.stat().st_size > limit * 4:
                raise OrchestratorError(f"seed file {label} is too big")
            try:
                text = path.read_bytes().decode("utf-8")
            except UnicodeDecodeError:
                raise OrchestratorError(f"seed file {label} is not UTF-8 text") from None
            if len(text) > limit:
                raise OrchestratorError(f"seed file {label} is too big ({len(text)} chars)")
            return text

        seeds = []
        for folder in sorted(p for p in root.iterdir() if p.is_dir() or p.is_symlink()):
            if folder.is_symlink():
                raise OrchestratorError(f"seed {folder.name} is a link; seeds must be real folders")
            files, axioms = {}, None
            for dirpath, dirs, names in os.walk(folder, followlinks=False):
                for name in dirs + names:
                    path = Path(dirpath) / name
                    rel = path.relative_to(folder).as_posix()
                    label = f"{folder.name}/{rel}"
                    if path.is_symlink():
                        raise OrchestratorError(f"seed file {label} is a link; seeds must hold real files")
                    if path.is_dir():
                        continue
                    if rel == "axioms.md":
                        axioms = read(path, label)
                    elif not _safe_rel(rel):
                        raise OrchestratorError(f"seed file {label} can't be copied into an agent")
                    else:
                        files[rel] = read(path, label)
            if axioms is None:
                raise OrchestratorError(f"seed {folder.name} has no axioms.md")
            seeds.append({"name": folder.name, "axioms": axioms, "files": files})
        if not seeds or len(seeds) > self.op["agents"]:
            raise OrchestratorError(f"seeds folder must hold 1 to {self.op['agents']} seed folders, has {len(seeds)}")
        return seeds

    def check_drafts(self, drafts, need: int, taken: list[str]):
        return check_drafts(self.axes, drafts, need, taken)

    def render(self, draft: dict) -> str:
        return render_draft(self.axes, draft)

    def start(self, connector, seeds_dir=None) -> list[Agent]:
        if self.stop_threshold is not None or self.agents:
            raise OrchestratorError("start() runs once per operation")
        n = self.op["agents"]
        seeds = self._read_seeds(seeds_dir) if seeds_dir is not None else []
        need = n - len(seeds)
        seed_texts = [s["axioms"] for s in seeds]

        def check(obj):
            t = obj.get("stop_threshold")
            if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t):
                return "stop_threshold must be a finite number"
            return self.check_drafts(obj.get("agents"), need, seed_texts)

        messages = [{"role": "system", "content": prompts.orch_system()},
                    {"role": "user", "content": prompts.gen0_message(
                        connector.brief(), self.axes, need, seed_texts, n, connector.n_steps(),
                        cycle_steps(connector, self.cfg))}]
        reply = ask_json(self.budget, self.model, "orchestrator", messages, check, self.op["orch_output_tokens"])

        rules = connector.cleaning_rules()
        starter = connector.starter_files()
        specs = [(s["axioms"], {**starter, **s["files"]}, s["name"]) for s in seeds]
        specs += [(self.render(d), dict(starter), d["name"]) for d in reply["agents"]]
        self.agents = self.create_all([(f"g0-{i:02d}", axioms, files, 0, []) for i, (axioms, files, _n)
                                       in enumerate(specs, 1)], rules["data_file"])
        self.all_agents.update({a.id: a for a in self.agents})
        self.stop_threshold = float(reply["stop_threshold"])
        self.log({"event": "gen0", "ids": [a.id for a in self.agents], "names": [s[2] for s in specs],
                  "seeds": len(seeds), "stop_threshold": self.stop_threshold,
                  "threshold_reason": reply.get("threshold_reason")})
        return list(self.agents)

    def create_all(self, specs, data_file: str) -> list[Agent]:
        """Create agents from (id, axioms, files, generation, parents). All or none: on any failure, what this call
        made is removed and OrchestratorError is raised."""
        made, out = [], []
        try:
            for agent_id, axioms, files, generation, parents in specs:
                if (self.agents_root / agent_id).exists() or (self.logs_root / f"{agent_id}.jsonl").exists():
                    raise OrchestratorError(f"agent {agent_id} already exists")
                made.append(agent_id)
                out.append(Agent.create(self.agents_root, self.logs_root, agent_id, axioms, files, data_file,
                                        generation=generation, parents=parents))
        except Exception as e:
            for agent_id in made:            # only ids that did not exist before this call
                shutil.rmtree(self.agents_root / agent_id, ignore_errors=True)
                (self.logs_root / f"{agent_id}.jsonl").unlink(missing_ok=True)
            if isinstance(e, OrchestratorError):
                raise
            raise OrchestratorError(f"creating agents failed: {type(e).__name__}: {e}") from None
        return out

    # ---- next generation ------------------------------------------------------------------------------------
    def _check_next(self, obj, drafts, suggested, survivors, new_axes):
        decisions = obj.get("decisions")
        if not isinstance(decisions, list) or len(decisions) != len(drafts):
            return f"expected one decision per draft ({len(drafts)}), in order"
        for i, d in enumerate(decisions):
            if not isinstance(d, dict) or d.get("draft") != i or not isinstance(d.get("adopt"), bool):
                return f"decision {i} must be {{draft: {i}, adopt: true|false, reason}}"
            if not isinstance(d.get("reason"), str) or not d["reason"].strip():
                return f"decision for draft {i} needs a reason"
        third = obj.get("third_survivor", False)
        if not isinstance(third, bool):
            return "third_survivor must be true or false"
        if third and not suggested:
            return "no third survivor was suggested, so third_survivor must be false"
        keep = survivors + ([suggested] if third else [])
        free = self.op["agents"] - len(keep)
        adopted = [drafts[i] for i, d in enumerate(decisions) if d["adopt"]]
        if len(adopted) > free:
            return f"adopted {len(adopted)} drafts but only {free} slots are free"
        taken = [self.all_agents[a].axioms for a in keep] + [render_draft(self.axes, d) for d in adopted]
        problem = check_drafts(self.axes, obj.get("fills", []), free - len(adopted), taken)
        if problem:
            return f"fills: {problem} (fill exactly the slots left after adopting)"
        axes = obj.get("axes", [])
        wanted = [_axis_key(x["axis"]) for x in new_axes]
        if not isinstance(axes, list) or [_axis_key(x.get("axis")) if isinstance(x, dict) else None
                                          for x in axes] != wanted:
            return "give one axes decision per suggested new axis, in order"
        if not all(isinstance(x.get("approve"), bool) and isinstance(x.get("reason"), str) and x["reason"].strip()
                   for x in axes):
            return "each axes decision needs approve (true|false) and a reason"
        return None

    def _fallback(self, drafts, survivors, selection, error: str):
        """Op. Orch's reply failed: adopt drafts in order, then copy agents into what is left: the bases, else the
        survivors, else the ranking (rank order, repeating). No model call. Returns (reply, copies)."""
        free = self.op["agents"] - len(survivors)
        adopted = list(range(min(free, len(drafts))))
        pool = ([b for b in selection["bases"] if b in self.all_agents] or list(survivors)
                or [r for r in selection["ranking"] if r in self.all_agents] or [a.id for a in self.agents])
        if not pool and free > len(adopted):
            raise OrchestratorError("no agent to copy and no draft to adopt: cannot make a generation")
        copies = [pool[i % len(pool)] for i in range(free - len(adopted))]
        self.log({"event": "fallback", "error": error, "adopted": adopted, "copies": copies})
        reply = {"decisions": [{"draft": i, "adopt": i in adopted, "reason": "fallback: Op. Orch reply failed"}
                               for i in range(len(drafts))],
                 "third_survivor": False, "fills": [], "axes": []}
        return reply, copies

    def _files_for(self, connector, agent_id):
        if agent_id and agent_id in self.all_agents:
            skipped = []
            files = self.all_agents[agent_id].work_files(self.cfg["tools"]["max_file_chars"], skipped=skipped)
            if skipped:
                self.log({"event": "files_skipped", "from": agent_id, "skipped": skipped[:50]})
            return files
        return dict(connector.starter_files())

    def next_generation(self, cycle: int, connector, selection: dict, eval_notes: dict, mutation: dict) -> list[Agent]:
        """Survivors stay unchanged; Op. Orch adopts or drops each Mutation draft with a reason, may keep the
        suggested 3rd survivor, fills empty slots, and approves or rejects new axes. Always `agents` agents."""
        gen = self.generation + 1
        drafts = list(mutation.get("drafts") or [])
        suggested = mutation.get("suggest_third_survivor")
        survivors = [s for s in selection["survivors"] if s in self.all_agents]
        if suggested not in self.all_agents or suggested in survivors:
            suggested = None
        new_axes = list(mutation.get("new_axes") or [])
        messages = [{"role": "system", "content": prompts.orch_system()},
                    {"role": "user", "content": prompts.next_gen_message(
                        self.axes, selection, eval_notes, mutation, drafts, suggested, survivors,
                        self.op["agents"], self.op["orch_notes_chars"])}]
        copies = []
        try:
            reply = ask_json(self.budget, self.model, "orchestrator", messages,
                             lambda o: self._check_next(o, drafts, suggested, survivors, new_axes),
                             self.op["orch_output_tokens"])
        except CapReached:                   # a budget stop is a stop, not a reason to improvise a generation
            raise
        except Exception as e:
            reply, copies = self._fallback(drafts, survivors, selection, f"{type(e).__name__}: {e}"[:300])

        keep = survivors + ([suggested] if reply.get("third_survivor") else [])
        specs, k = [], 0

        def next_id():
            nonlocal k
            k += 1
            return f"g{gen}-{k:02d}"

        for i, d in enumerate(drafts):
            decision = reply["decisions"][i]
            self.log({"event": "draft_decision", "cycle": cycle, "draft": i, "name": d["name"],
                      "adopt": decision["adopt"], "reason": decision["reason"]})
            if decision["adopt"]:
                specs.append((next_id(), render_draft(self.axes, d), self._files_for(connector, d.get("start_files_from")),
                              gen, list(d.get("parents") or [])))
        for f in reply.get("fills", []):
            specs.append((next_id(), render_draft(self.axes, f), dict(connector.starter_files()), gen, []))
        for base in copies:
            specs.append((next_id(), self.all_agents[base].axioms, self._files_for(connector, base), gen, [base]))
        if suggested:
            self.log({"event": "third_survivor", "cycle": cycle, "agent": suggested,
                      "kept": bool(reply.get("third_survivor")), "reason": reply.get("third_reason", "")})
        if len(keep) + len(specs) != self.op["agents"]:      # checked before any folder is made
            raise OrchestratorError(f"generation {gen} would have {len(keep) + len(specs)} agents, "
                                    f"expected {self.op['agents']}")
        new = self.create_all(specs, connector.cleaning_rules()["data_file"])
        for x, decision in zip(new_axes, reply.get("axes", [])):
            self.log({"event": "axis_decision", "cycle": cycle, "axis": x["axis"], "approve": decision["approve"],
                      "reason": decision["reason"]})
            if decision["approve"]:
                self.axes.append(x["axis"].strip())
        self.agents = [self.all_agents[a] for a in keep] + new
        self.all_agents.update({a.id: a for a in new})
        self.generation = gen
        self.log({"event": "generation", "cycle": cycle, "generation": gen, "ids": [a.id for a in self.agents],
                  "kept": keep, "new": [a.id for a in new]})
        if len(self.agents) != self.op["agents"]:
            raise OrchestratorError(f"generation {gen} has {len(self.agents)} agents, expected {self.op['agents']}")
        return list(self.agents)

    # ---- cleaner review --------------------------------------------------------------------------------------
    def review_deletions(self, cycle: int, deletions: list, cleaner) -> list[str]:
        """Read the cleaner's deletions and undo what is clearly not data, each with a logged reason."""
        if not deletions:
            return []
        known = {d["id"] for d in deletions}

        def check(obj):
            undo = obj.get("undo")
            if not isinstance(undo, list):
                return "undo must be a list"
            seen = set()
            for i, u in enumerate(undo):
                if not isinstance(u, dict) or u.get("id") not in known or u["id"] in seen:
                    return f"undo[{i}].id must be a listed deletion id, once"
                if not isinstance(u.get("reason"), str) or not u["reason"].strip():
                    return f"undo[{i}] needs a reason"
                seen.add(u["id"])
            return None

        messages = [{"role": "system", "content": prompts.orch_system()},
                    {"role": "user", "content": prompts.review_message(deletions, self.op["orch_notes_chars"])}]
        try:
            reply = ask_json(self.budget, self.model, "orchestrator", messages, check, self.op["orch_output_tokens"])
        except CapReached:
            raise
        except Exception as e:
            self.log({"event": "review_failed", "cycle": cycle, "error": f"{type(e).__name__}: {e}"[:300]})
            return []
        undone = []
        for u in reply["undo"]:
            try:
                cleaner.undo(u["id"])
                ok, error = True, None
                undone.append(u["id"])
            except Exception as e:
                ok, error = False, str(e)[:300]
            self.log({"event": "undo_decision", "cycle": cycle, "id": u["id"], "reason": u["reason"], "ok": ok,
                      "error": error})
            rec = cleaner.records.get(u["id"], {})
            if ok and rec.get("file") == "axioms.md" and rec.get("agent") in self.all_agents:
                agent = self.all_agents[rec["agent"]]
                agent.axioms = (agent.dir / "axioms.md").read_text(errors="replace")
        return undone

    def should_stop(self, loop_score: float) -> bool:
        return self.stop_threshold is not None and loop_score >= self.stop_threshold

    # ---- the run's last cycle --------------------------------------------------------------------------------
    def fallback_pick(self, loop_scores: dict, selection: dict | None = None) -> str | None:
        """The current agent with the best loop score (ties: natural id order); else the first current agent in the
        selection's ranking; None when no agent was scored (a stop before the first cycle end)."""
        ids = [a.id for a in self.agents]
        scored = [a for a in ids if isinstance(loop_scores.get(a), float) and math.isfinite(loop_scores[a])]
        if scored:
            return sorted(scored, key=lambda a: (-loop_scores[a], natural_key(a)))[0]
        ranked = [a for a in (selection or {}).get("ranking", []) if a in ids]
        return ranked[0] if ranked else None

    def final_review(self, cycle: int, selection: dict, eval_notes: dict, loop_scores: dict, target=None,
                     target_source: str = "orch") -> dict:
        """Op. Orch reads the last cycle's Eval notes and picks the final agent. Never raises: any failure (budget
        included, since the run is ending) gives the fallback pick."""
        ids = [a.id for a in self.agents]
        current = sorted(ids, key=lambda a: (-loop_scores.get(a, -math.inf), natural_key(a)))
        best = max(loop_scores.values(), default=None)

        def check(obj):
            if obj.get("selected") not in ids:
                return f"selected must be one of {ids}"
            if not isinstance(obj.get("reason"), str) or not obj["reason"].strip():
                return "reason must be a non-empty string"
            if not isinstance(obj.get("report", ""), str):
                return "report must be a string"
            return None

        messages = [{"role": "system", "content": prompts.orch_system()},
                    {"role": "user", "content": prompts.final_message(
                        target, target_source, best, [(a, loop_scores.get(a)) for a in current], selection,
                        eval_notes, self.op["orch_notes_chars"])}]
        try:
            reply = ask_json(self.budget, self.model, "orchestrator", messages, check, self.op["orch_output_tokens"])
            out = {"selected": reply["selected"], "why": reply["reason"].strip(), "report": reply.get("report", ""),
                   "fallback": False}
        except Exception as e:
            out = {"selected": self.fallback_pick(loop_scores, selection), "why": "fallback: best loop score",
                   "report": "", "fallback": True, "error": f"{type(e).__name__}: {e}"[:300]}
        self.log({"event": "final", "cycle": cycle, **out})
        return out
