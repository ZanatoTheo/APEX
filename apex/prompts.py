"""Prompts of the agents and their subagents. Generic: the task comes only from the brief."""
import json
import re

from .agent import INTERPRETATION
from .tools.files import cut

CREATIVE_RULE = ("Make the approaches inventive. Build each one by joining the task with a field far from it "
                 "(for example signal processing, network theory, physics, ecology, epidemiology, information "
                 "theory, control theory, game theory, linguistics). Each approach names a concrete mechanism "
                 "(why it should work) and a concrete method (the math or algorithm it uses). No plain threshold "
                 "rules (\"if X is above Y, do Z\") and no vague words: every rule must be specific enough to "
                 "code. Spread the agents across different fields; unrelated ideas may aim at the same goal.")

AXIOM = ("Shared axiom: build systems that allocate resources and react to what happens. Do not try to predict "
         "everything yourself. Prefer structured systems, logically justified, over guesses you cannot "
         "verify by reasoning.")

_KEY = re.compile(r"[a-z][a-z0-9_]{0,23}")      # a short snake_case name, never a sentence or an id


def report_numbers(report):
    """Keep only numbers (and None) under short snake_case keys, through dicts and lists. Text never reaches an
    agent through its report (values or keys), so no Eval reasoning can leak this way."""
    if isinstance(report, dict):
        out = {}
        for key, value in report.items():
            if not isinstance(key, str) or not _KEY.fullmatch(key):
                continue
            kept = report_numbers(value)
            if kept is not _DROP:
                out[key] = kept
        return out
    if isinstance(report, (list, tuple)):
        return [v for v in (report_numbers(x) for x in report) if v is not _DROP]
    if report is None or isinstance(report, (bool, int, float)):
        return report
    return _DROP


_DROP = object()


def _data_rule(rules: dict) -> str:
    f = rules["data_file"]
    return (f"Facts about the task's data go only in {f} ({rules['what_counts_as_data']}). Never put them in "
            f"notes.md, in code or in any other file: {f} is deleted at the end of each cycle, everything else is "
            f"kept, and data facts found elsewhere are removed. Text shown as [cleaned …] was a data fact removed at a "
            f"cycle end; files that are data as a whole are deleted.")


def agent_system(agent, brief: str, rules: dict) -> str:
    return f"""You are agent {agent.id}, one of several agents working on the same task. Each agent tests a \
different approach, and the ones that do best are kept.

{AXIOM}

Your axioms (your approach; read-only, in axioms.md):
{agent.axioms}

The task:
{brief}

How a step works:
- A step is simulated, not real time. At the start of each step you get your results so far, as numbers.
- Work only in your folder, with your tools: write, edit, read, list and delete files; run Python scripts \
(sandboxed: no network, numpy and pandas available); spawn subagents for side tasks (they share one token pool).
- Your memory between steps is your files. Keep plans and lessons in notes.md.
- {_data_rule(rules)}
- When your work for this step is done, call finish with a one-line summary."""


def subagent_system(agent, brief: str, rules: dict) -> str:
    return f"""You are a helper of agent {agent.id}. Do the one task you are given, in the agent's folder, with \
your tools. When it is done, reply with a short result and no tool calls.

{AXIOM}

The agent's task:
{brief}

- {_data_rule(rules)}"""


NOTES = "notes.md"
MAIN_FILE_CHARS = 6000              # each file shown in the step message


def step_message(step: int, n_steps: int, report, files=None, listing=None, budget=None, starters=(),
                 empty=(), advice=None) -> str:
    """The step's first message. With `files` ({name: text or None}: notes.md and the main files), it also holds
    the budget, the priority and the files' current text, so no turn goes to re-reading them."""
    parts = [f"Step {step + 1} of {n_steps} is released.",
             f"Your results so far (numbers only): {json.dumps(report_numbers(report))}"]
    if advice:
        parts.append(f"A suggestion from a reviewer (your score last cycle was {advice['score']:.4g}). Weigh it "
                     "against your own judgment; you may ignore it. Weak points the reviewer saw:\n"
                     + "\n".join(f"- {cut(str(w), 400)}" for w in advice["weaknesses"]))
    if budget:
        parts.append(f"Your budget for this step: {budget['tokens']} tokens in all, counting every turn's full input "
                     f"(the whole conversation is sent again each turn), and at most {budget['turns']} turns. "
                     "Plan for a handful of turns.")
    if files is not None:
        mains = [n for n in files if n not in (NOTES, INTERPRETATION)]
        if mains:
            names = ", ".join(mains)
            parts.append(f"Your score comes only from {names}. The starter version is only a baseline. Change "
                         f"{names} first, check it with run_script in this same step, read the result, fix it if "
                         "needed, then finish. Scripts that don't change it don't raise your score.")
        if INTERPRETATION in files:
            parts.append(f"{INTERPRETATION}: for each axis, what your axiom means in practice: the concrete signals, "
                         "formulas and parameters, and where your code applies them. Keep it and the code in step.")
        parts.append("Files in your folder: " + (", ".join(listing) if listing else "(none)"))
        for name, text in files.items():
            mark = (" (still the starter: replace it)" if name in starters else
                    " (still empty: write it first)" if name in empty else "")
            body = "(missing)" if text is None else cut(text, MAIN_FILE_CHARS)
            parts.append(f"--- {name}{mark} ---\n{body}")
        parts.append("Those are the files' current contents: don't spend turns reading them again.")
    parts.append("Do your work for this step, then call finish.")
    return "\n".join(parts)


# ---- Op. Orch --------------------------------------------------------------------------------------------------
def orch_system() -> str:
    return """You are Op. Orch, the operator of an evolution of agents that all work on one task.
Your stance: see what the best agent is, not build the best agent. You deploy agents with clearly different \
approaches, let them work, and keep what holds up. You only drop what clearly does not hold. You never plan \
centrally: you do not rewrite agents' approaches or tell them how to work.
Answer only with the JSON object you are asked for."""


def render_axioms(name: str, approach: str, axioms: dict) -> str:
    lines = [f"# {name.strip()}", "", approach.strip(), ""]
    for axis, text in axioms.items():
        lines += [f"## {axis}", text.strip(), ""]
    return "\n".join(lines)


def gen0_message(brief: str, axes: list, need: int, seed_axioms: list, n_agents: int, n_steps: int,
                 steps_per_cycle: int) -> str:
    seeds = "\n\n".join(f"--- seed {i + 1} ---\n{text}" for i, text in enumerate(seed_axioms)) or "(none)"
    axis_lines = "\n".join(f"- {a}" for a in axes)
    example = json.dumps({"stop_threshold": 0.0, "threshold_reason": "…", "agents": [
        {"name": "…", "approach": "one or two sentences", "axioms": {a: "one rule" for a in axes}}]}, indent=1)
    return f"""The task, as every agent will see it:
{brief}

The operation runs {n_agents} agents. One loop is {n_steps} steps; a cycle is {steps_per_cycle} steps, after which \
agents are scored, the best are kept and new ones are drafted.

An agent's axioms are its approach: one rule per axis. The axes are:
{axis_lines}

Seed agents given by the user (kept as they are):
{seeds}

Draft {need} new agents. Each must test a clearly different approach from every other agent and every seed.
{CREATIVE_RULE}
Also set stop_threshold: the score (as the task defines it, over one full loop) at which an agent is clearly good \
enough to stop the operation. It is fixed for the whole operation. Say why in threshold_reason.

Reply with only a JSON object of this shape (exactly {need} agents; the axioms keys are the axes above):
{example}"""


def summary_system() -> str:
    return ("You summarize one step of an operation for its operator, Op. Orch. Be short: what each agent did, "
            "what changed, and anything odd (errors, caps, agents that changed nothing). Use only the rows given.")


def summary_prompt(step: int, rows: str) -> str:
    return f"Step {step + 1}. One row per agent (report numbers, how its step ended, files changed, its own summary):\n{rows}"


# ---- Evaluator -------------------------------------------------------------------------------------------------
def eval_system() -> str:
    return """You are the Evaluator of an evolution of agents that all work on one task. For one agent, judge the \
logic of its approach and its work: strong points, weak points, flaws that come from its axioms, and fixes to its \
axioms that you can justify. Judge the logic, not luck: if a score looks like luck, say so. Your notes are never \
shown to agents; only the operator and the Mutation agent read them.
Answer only with the JSON object you are asked for."""


def eval_message(brief: str, axes: list, agent_id: str, axioms: str, rank: int, n: int, score, avg: float,
                 steps: list, files: str) -> str:
    example = json.dumps({"strengths": ["…"], "weaknesses": ["…"], "axiom_flaws": ["…"],
                          "axiom_fixes": [{"axis": axes[0].split(":")[0], "fix": "…", "why": "…"}]}, indent=1)
    return f"""The task:
{brief}

The axes of every agent's axioms:
{chr(10).join('- ' + a for a in axes)}

Agent {agent_id}: rank {rank} of {n} this cycle, score {score} (average {avg}).

Its axioms:
{axioms}

Its steps this cycle (from its log):
{json.dumps(steps)}

Its files:
{files}

Reply with only a JSON object of this shape (each fix names one axis above):
{example}"""


# ---- Mutation and the next generation --------------------------------------------------------------------------
def mutation_system() -> str:
    return """You are the Mutation agent of an evolution of agents that all work on one task. You read every agent \
(kept or not): its axioms, the Evaluator's hidden notes, its steps and its files. You tie each strategy to the axes \
of its axioms and explain why it held up or failed; find variables no agent addresses on each axis; combine agents \
whose strengths cover each other's weaknesses; and draft new agents for the operator, Op. Orch, to adopt or drop. \
You may suggest one more agent to keep unchanged (a 3rd survivor) and new axes.
""" + CREATIVE_RULE + """ \
Combining two agents' ideas into one new mechanism is welcome.
Answer only with the JSON object you are asked for."""


def _worse_lines(selection: dict) -> str:
    """One line per agent that did worse than its parents (selection.parent_penalty), or "(none)"."""
    flags = selection.get("worse_than_parents") or {}
    return "\n".join(f"- {a}: score {f['score']} below its parents' {f['ref']} ({f['basis'].replace('_', ' ')}); "
                     f"ranked with -{f['penalty']:.4g}" for a, f in flags.items()) or "(none)"


def mutation_message(brief: str, axes: list, selection: dict, blocks: list, need: int) -> str:
    example = json.dumps({
        "axis_analysis": [{"axis": axes[0].split(":")[0], "held_up": "…", "failed": "…", "unaddressed": ["…"]}],
        "drafts": [{"name": "…", "approach": "…", "axioms": {a: "one rule" for a in axes}, "parents": ["<agent id>"],
                    "start_files_from": "<agent id or null>", "why": "…"}],
        "suggest_third_survivor": None, "third_reason": "", "new_axes": [{"axis": "name: what it covers", "why": "…"}]},
        indent=1)
    agents = "\n\n".join(
        f"--- {b['id']} ({b['role']}, score {b['score']}) ---\nAxioms:\n{b['axioms']}\nEvaluator notes: "
        f"{json.dumps(b['eval'])}\nSteps: {json.dumps(b['steps'])}\nFiles:\n{b['files']}" for b in blocks)
    return f"""The task:
{brief}

Axes:
{chr(10).join('- ' + a for a in axes)}

This cycle: survivors (kept unchanged) {selection['survivors']}; bases (score >= {selection['threshold']}) \
{selection['bases']}; average {selection['avg']}.
Agents that did worse than their parents (ranked with a penalty):
{_worse_lines(selection)}

Every agent, best first:
{agents}

Draft exactly {need} new agents, each different from every other draft and every survivor. parents are the \
agents it combines; start_files_from is the agent whose files it starts with (or null for the task's starter \
files).
Reply with only a JSON object of this shape:
{example}"""


def next_gen_message(axes: list, selection: dict, eval_notes: dict, mutation: dict, drafts: list, suggested,
                     survivors: list, n_agents: int, notes_chars: int = 40000) -> str:
    listed = "\n".join(f"[{i}] {d['name']}: {d['approach']} (parents {d.get('parents')}; why: {d.get('why', '')})"
                       for i, d in enumerate(drafts)) or "(none: Mutation failed; fill every free slot yourself)"
    third = (f"Mutation suggests keeping {suggested} as a 3rd survivor: {mutation.get('third_reason', '')}"
             if suggested else "No 3rd survivor was suggested (third_survivor must be false).")
    new_axes = "\n".join(f"- {x['axis']}: {x.get('why', '')}" for x in mutation.get("new_axes") or []) or "(none)"
    example = json.dumps({"decisions": [{"draft": 0, "adopt": True, "reason": "…"}], "third_survivor": False,
                          "third_reason": "", "fills": [{"name": "…", "approach": "…",
                                                         "axioms": {a: "one rule" for a in axes}}],
                          "axes": [{"axis": "<as suggested>", "approve": False, "reason": "…"}]}, indent=1)
    return f"""End of cycle. Survivors kept unchanged: {survivors}. Ranking with scores: \
{json.dumps(selection['scores'])}. The operation always has {n_agents} agents.
Agents that did worse than their parents (ranked with a penalty):
{_worse_lines(selection)}

Evaluator notes (hidden from agents):
{cut(json.dumps(eval_notes), notes_chars)}

Mutation's axis analysis: {cut(json.dumps(mutation.get('axis_analysis', [])), notes_chars // 4)}
Mutation's error, if any: {mutation.get('error', 'none')}

Drafts:
{listed}

{third}

Suggested new axes:
{new_axes}

Decide, without rewriting anyone's approach:
- adopt or drop each draft, with a reason (drop only what clearly does not hold);
- third_survivor: true only to keep the suggested agent;
- fills: new agents of your own for the slots still free after the survivors and adopted drafts (exactly that \
many; none if no slot is free);
- approve or reject each suggested new axis, with a reason.
Reply with only a JSON object of this shape:
{example}"""


# ---- Cleaner and Op. Orch's review of its deletions ------------------------------------------------------------
def cleaner_system() -> str:
    return """You clean an agent's files between cycles of an evolution of agents. Find every fact about the task's \
data that the files still hold, so it can be removed before the agent goes on. Keep general lessons, rules, methods \
and code logic: remove only the data facts. Quote each fact exactly as it appears in the file (a short, exact span).
Answer only with the JSON object you are asked for."""


def cleaner_message(rules: dict, files: str) -> str:
    example = json.dumps({"facts": [{"file": "notes.md", "quote": "exact text", "reason": "why it is data"}]})
    return f"""What counts as data for this task: {rules['what_counts_as_data']}

The agent's files:
{files}

Reply with only a JSON object of this shape (an empty list if there is nothing to remove):
{example}"""


def review_message(deletions: list, chars: int) -> str:
    rows = "\n".join(json.dumps({"id": d["id"], "agent": d["agent"], "file": d["file"], "kind": d["kind"],
                                 "source": d["source"], "reason": d.get("reason", ""),
                                 "original": cut(str(d.get("original") or ""), 300)}) for d in deletions)
    example = json.dumps({"undo": [{"id": "c1-0001", "reason": "a general lesson, not data"}]})
    return f"""The cleaner removed these from agents' files at the end of the cycle (data facts must not be carried \
into later cycles):
{cut(rows, chars)}

Undo only what is clearly not data (a general lesson, a rule, code logic). When in doubt, leave it removed.
Reply with only a JSON object of this shape (an empty list to undo nothing):
{example}"""


# ---- the run's last cycle --------------------------------------------------------------------------------------
def final_message(target, target_source: str, loop_score, current: list, selection: dict, eval_notes: dict,
                  chars: int) -> str:
    """`current`: [(agent id, loop score or None)], best loop score first."""
    example = json.dumps({"selected": "<agent id>", "reason": "…", "report": "a short report for the user"})
    rows = "\n".join(f"- {a}: loop score {s}" for a, s in current)
    return f"""The operation is over. Pick the final agent: the one whose work best holds up.
Target loop score ({target_source}): {target}. Best loop score reached: {loop_score}.
A loop score is an agent's score over all the cycles it ran, scaled to one full loop.

Current agents, best loop score first: {json.dumps([a for a, _ in current])}
{rows}

Last cycle's ranking with scores: {json.dumps(selection['scores'])}
Evaluator notes on the last cycle (hidden from agents):
{cut(json.dumps(eval_notes), chars)}

selected must be one of the current agents. Say why in reason, and give the user a short report on the operation.
Reply with only a JSON object of this shape:
{example}"""
