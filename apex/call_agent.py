"""call_agent: one agent, one step. Called only by Op. Orch's operation loop.

The step ends when the agent calls finish, sends a reply with no tool calls, hits a cap, or the model fails.
"""
import hashlib
import json
import os
import stat
from pathlib import Path

from . import prompts
from .agent import INTERPRETATION, interpretation_stub
from .budget import CallBudget, CapReached
from .connector import script_files
from .tools import Tool, ToolError, Workspace, core_toolset
from .tools.files import cut

FINISH = "finish"
SPAWN = "spawn_subagents"
_HASH_MAX = 2 * 1024 * 1024
_SUB_RESULT_CHARS = 2000


def replay_items(raw_output) -> list:
    """The reply items to send back next turn: messages and function calls only, without server ids or status
    (with store=False those ids point at nothing). Reasoning items are dropped."""
    items = []
    for it in raw_output or []:
        if not isinstance(it, dict):
            continue
        if it.get("type") == "message":
            content = it.get("content")
            parts = [{"type": "output_text", "text": p["text"]} for p in (content if isinstance(content, list) else [])
                     if isinstance(p, dict) and p.get("type") == "output_text" and isinstance(p.get("text"), str)]
            if parts:
                items.append({"type": "message", "role": "assistant", "content": parts})
        elif it.get("type") == "function_call":
            args = it.get("arguments")
            items.append({"type": "function_call", "call_id": it.get("call_id"), "name": it.get("name"),
                          "arguments": args if isinstance(args, str) else json.dumps(args)})
    return items


def _fingerprint(full: str, st) -> tuple:
    if stat.S_ISLNK(st.st_mode):
        return ("link", os.readlink(full))
    if not stat.S_ISREG(st.st_mode):
        return ("other", st.st_mode)
    if st.st_size > _HASH_MAX:
        return ("big", st.st_size, st.st_mtime_ns)
    try:
        fd = os.open(full, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except OSError:                                   # e.g. a script chmod-ed it to 000
        return ("unreadable", st.st_size, st.st_mtime_ns, st.st_mode)
    try:
        return ("file", hashlib.sha1(os.read(fd, _HASH_MAX + 1)).hexdigest())
    except OSError:
        return ("unreadable", st.st_size, st.st_mtime_ns, st.st_mode)
    finally:
        os.close(fd)


def snapshot(folder) -> dict:
    """{relative path: fingerprint} of every entry under `folder`: files (hashed up to 2 MB), links (to folders
    too), empty or unreadable folders (keys end in "/"). Never raises for what an agent's script left behind."""
    root = Path(folder)
    out = {}

    def unreadable(err):
        if getattr(err, "filename", None):
            out[Path(err.filename).relative_to(root).as_posix() + "/"] = ("unreadable-dir",)

    for dirpath, dirs, files in os.walk(root, followlinks=False, onerror=unreadable):
        here = Path(dirpath)
        if here != root and not dirs and not files:
            out[here.relative_to(root).as_posix() + "/"] = ("dir",)
        for name in files + [d for d in dirs if os.path.islink(os.path.join(dirpath, d))]:
            full = os.path.join(dirpath, name)
            try:
                out[(here / name).relative_to(root).as_posix()] = _fingerprint(full, os.lstat(full))
            except OSError:
                out[(here / name).relative_to(root).as_posix()] = ("gone",)
    return out


class _Step:
    def __init__(self, agent, step: int, connector, budget, model, advice=None):
        self.agent, self.step, self.connector, self.model = agent, step, connector, model
        self.advice = advice                        # own Eval weaknesses, or None
        self.cfg = budget.cfg
        self.cb = CallBudget(self.cfg, budget, agent.id)
        self.ws = Workspace(agent.dir, self.cfg)
        self.brief = self.rules = None              # read in run(), where a connector failure is caught
        self.cost = 0.0
        self.n_subs = 0

    def _base_tools(self):
        files = script_files(self.connector, self.agent.id, self.step)   # read-only in every run_script
        tools = core_toolset(self.ws, self.cfg, ro_files=files)
        tools.merge(self.connector.tools(self.agent.id, self.agent.dir, self.step))
        return tools

    # ---- subagents ------------------------------------------------------------------------------------------
    def _spawn(self, args) -> str:
        tasks, most = args["tasks"], self.cfg["limits"]["max_subagents"]
        if not tasks or len(tasks) > most or not all(isinstance(t, str) and t.strip() for t in tasks):
            raise ToolError(f"tasks must be 1 to {most} non-empty strings")
        tools = self._base_tools()                  # no spawn_subagents, no finish
        specs = tools.specs()
        system = prompts.subagent_system(self.agent, self.brief, self.rules)
        subs = []
        for task in tasks:
            self.n_subs += 1
            subs.append({"n": self.n_subs, "task": task, "turns": 0, "ended_by": None, "result": "",
                         "messages": [{"role": "system", "content": system}, {"role": "user", "content": task}]})
        turn_cap = self.cfg["limits"]["call_turns"]
        while any(s["ended_by"] is None for s in subs):
            for s in subs:                          # round-robin: one turn each
                if s["ended_by"] is not None:
                    continue
                if s["turns"] >= turn_cap:
                    s["ended_by"] = "cap:call_turns"
                    continue
                try:
                    reply = self.cb.call(self.model, "subagent", s["messages"], tools=specs, scope="subagent")
                except CapReached as e:             # the pool (or the cycle's dollars) is shared: all stop
                    for o in subs:
                        if o["ended_by"] is None:
                            o["ended_by"] = f"cap:{e.kind}"
                    break
                except Exception as e:              # LLMError, or any bug in the model path
                    s["ended_by"], s["result"] = "error", f"{type(e).__name__}: {e}"[:300]
                    continue
                s["turns"] += 1
                self.cost += reply["cost_usd"]
                if reply["text"]:
                    s["result"] = reply["text"]
                s["messages"] += replay_items(reply["raw_output"])
                outputs = [tools.run(c) for c in reply["tool_calls"]]
                s["messages"] += outputs
                self.agent.log({"event": "subagent", "step": self.step, "sub": s["n"], "turn": s["turns"],
                                "task": s["task"] if s["turns"] == 1 else None, "text": reply["text"],
                                "tool_calls": reply["tool_calls"], "outputs": outputs, "usage": reply["usage"],
                                "cost_usd": reply["cost_usd"]})
                if not reply["tool_calls"]:
                    s["ended_by"] = "reply"
        return json.dumps([{"task": s["task"], "ended_by": s["ended_by"], "result": cut(s["result"], _SUB_RESULT_CHARS)}
                           for s in subs])

    # ---- the agent's loop -----------------------------------------------------------------------------------
    def _setup(self, report):
        self.brief = self.connector.brief()
        self.rules = self.connector.cleaning_rules()
        tools = self._base_tools()
        tools.add(Tool(SPAWN, "Run helper subagents on side tasks, one per task. They have your file, script and "
                              "task tools (not this one) and share one token pool; each returns a short result.",
                       {"type": "object", "properties": {"tasks": {"type": "array", "items": {"type": "string"}}},
                        "required": ["tasks"]}, self._spawn))
        tools.add(Tool(FINISH, "End your work for this step.",
                       {"type": "object", "properties": {"summary": {"type": "string"}}},
                       lambda args: "step finished"))
        messages = [{"role": "system", "content": prompts.agent_system(self.agent, self.brief, self.rules)},
                    {"role": "user", "content": self._step_message(report)}]
        return tools, tools.specs(), messages

    def _step_message(self, report) -> str:
        """notes.md and the connector's starter-file names, read from the folder."""
        starter = self.connector.starter_files()
        folder = Path(self.agent.dir)
        files = {}
        for name in [prompts.NOTES, INTERPRETATION] + [n for n in starter if n not in (prompts.NOTES, INTERPRETATION)]:
            path = folder / name
            files[name] = (path.read_text(errors="replace") if path.is_file() and not path.is_symlink() else None)
        starters = {n for n in starter if files.get(n) is not None and files[n] == starter[n]}
        listing = sorted(p.name for p in folder.iterdir() if p.is_file() and not p.name.startswith("."))
        budget = {"tokens": self.cfg["limits"]["call_tokens"], "turns": self.cfg["limits"]["call_turns"]}
        empty = {INTERPRETATION} if files.get(INTERPRETATION) == interpretation_stub(self.agent.axioms) else set()
        return prompts.step_message(self.step, self.connector.n_steps(), report, files=files, listing=listing,
                                    budget=budget, starters=starters, empty=empty, advice=self.advice)

    def run(self, report) -> dict:
        before = snapshot(self.agent.dir)
        ended_by, error, summary, turns = None, None, "", 0
        try:                                        # a broken connector ends this agent's step, not the run
            tools, specs, messages = self._setup(report)
        except Exception as e:
            ended_by, error = "error", f"setup: {type(e).__name__}: {e}"[:300]
            messages = []
        self.agent.log({"event": "start", "step": self.step, "messages": messages})
        while ended_by is None:
            try:
                reply = self.cb.call(self.model, "agent", messages, tools=specs)
            except CapReached as e:
                ended_by = f"cap:{e.kind}"
                break
            except Exception as e:                  # LLMError, or any bug in the model path
                ended_by, error = "error", f"{type(e).__name__}: {e}"[:300]
                break
            turns += 1
            self.cost += reply["cost_usd"]
            if reply["text"]:
                summary = reply["text"]
            messages += replay_items(reply["raw_output"])
            self.agent.log({"event": "reply", "step": self.step, "turn": turns, "text": reply["text"],
                            "tool_calls": reply["tool_calls"], "status": reply["status"], "usage": reply["usage"],
                            "cost_usd": reply["cost_usd"]})
            if not reply["tool_calls"]:
                ended_by = "reply"
                break
            outputs, finished = [], False
            for call in reply["tool_calls"]:
                outputs.append(tools.run(call))
                if isinstance(call, dict) and call.get("name") == FINISH:
                    finished = True
                    args = call.get("arguments")
                    if isinstance(args, dict) and isinstance(args.get("summary"), str):
                        summary = args["summary"]
            messages += outputs
            self.agent.log({"event": "tools", "step": self.step, "turn": turns, "outputs": outputs})
            if finished:
                ended_by = "finish"
        after = snapshot(self.agent.dir)
        changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
        result = {"ended_by": ended_by, "turns": turns, "files_changed": changed,
                  "tokens": self.cb.used["agent"] + self.cb.used["subagent"], "cost": self.cost,
                  "summary": cut(summary, 500), "error": error}
        self.agent.log({"event": "end", "step": self.step, **result})
        return result


def call_agent(agent, report, step: int, connector, budget, model, advice=None) -> dict:
    """Run one step of one agent. Returns {ended_by, turns, files_changed, tokens, cost, summary}."""
    return _Step(agent, step, connector, budget, model, advice).run(report)
