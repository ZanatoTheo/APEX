# Project Apex: Design Document
- Status: built (Apex)
- Version: 2.0.0
- Date: 2026-11-05

This document describes the system as built. Commands are in `README.md`, file locations in `CODE_STRUCTURE.md`, and
the original idea in `idea.md`.

## 1. Summary
Apex evolves a group of LLM agents on a task, one step at a time. Agents work on the task, a connector scores them,
and at each cycle's end the best stay while new ones replace the rest. The core in `apex/` knows nothing about the
task. Today's task is trading 13 renamed assets day by day through 2025, with no look-ahead.

## 2. Core concepts
| Term | Meaning |
|---|---|
| Agent | An LLM with its own folder, id (`g<generation>-<nn>`) and axioms |
| Axioms | The agent's idea, one rule per axis, in read-only `axioms.md` |
| Axis | A question every agent must answer. Defaults: signals, decision rule, sizing, adaptation, safety |
| Step | One release of task data, followed by the agents' work |
| Cycle | A group of steps, scored once at its end |
| Loop | All of the connector's steps once, split into cycles. After the last cycle the run wraps to the first |
| Generation | The set of agents after one round of selection and replacement |
| Connector | The only door between the core and a task |
| Run | One operation, stored in `runs/<time>-<4 hex>/` |

## 3. Goals and non-goals
Goals:
- See what the best agent for a task is, with every decision logged.
- Keep future data away from agents at every point.
- Keep cost capped, and let a task change by changing only the connector and `environment/`.

Non-goals:
- A claim that a strategy makes money. The market task is a test of the loop.
- Resuming a stopped run.

## 4. Roles
Every role is an LLM call through `call_llm`. All default to `muse-spark-1.3-contributor`. Op. Orch can use
`muse-wonder-1.0`.

| Role | Job |
|---|---|
| Op. Orch | Drafts generation 0, approves or rejects new agents, reviews the cleaner's deletions, makes the final pick |
| Agent | Works on its files in each step, using tools |
| Subagent | Does a side task for an agent, from one token pool shared by that agent's subagents |
| Summarizer | Writes the per-step summary Op. Orch reads |
| Evaluator (Eval) | Writes hidden notes on each agent at a cycle's end |
| Mutation | Reads every agent and drafts new ones |
| Cleaner | Finds task data that the patterns missed in agents' files |

## 5. The run
1. **Generation 0.** Op. Orch drafts the agents and a stop threshold. Each agent must give a rule for every axis, and
   no two may have the same axioms. Seed agents from `--seeds` go first.
2. **Each step.** The connector releases the step and tests every agent. Each agent then works, one after another or
   up to `operation.parallel_agents` at once. The summarizer writes the step's summary.
3. **Cycle end.** Scores are read, selection runs (§6) and Eval writes its notes.
4. **Stop check.** If the run stops, it makes the final pick (§9).
5. **Otherwise.** Mutation drafts, Op. Orch builds the next generation, the cleaner runs, and Op. Orch reviews its
   deletions.
6. **Held-out check (optional).** A copy of the picked agent walks a held-out set of steps once, with no evolution.
   Its folder is cleaned first, and training's result stays even if the walk fails.

## 6. Selection
Selection is plain code, with no model:
- Ranking is by score, high first. Ties go to the smaller id. A score that isn't a finite number ranks last.
- **Survivors:** the top `operation.survivors` (2) stay unchanged. Op. Orch may keep a third that Mutation suggests.
- **Bases:** agents with score >= avg + `base_margin` * |avg|. If nobody passes, the survivors are the bases, so
  Mutation always has a parent.
- **Worse-child penalty:** before ranking, a child that did worse than its parents loses
  `worse_child_penalty` * max(|avg|, max - min). Eval and the loop score use the raw scores.

## 7. Mutation and the next generation
Mutation sees each agent's axioms, Eval note, step summaries and files. It ties strategies to axes, looks for
unaddressed variables, combines agents whose strengths cover each other's weaknesses, and drafts free slots + 2
agents. It may suggest a third survivor and new axes. Its output stays hidden from agents.

Op. Orch decides on each draft with a reason and fills any free slots. If its reply fails after a retry, a fallback
adopts drafts in order and fills the rest with copies of the bases. If Mutation fails, Op. Orch fills the slots
itself. An adopted draft can start from another agent's work files. New agents get an empty `interpretation.md` with
one section per axiom, which they fill in as their own memory.

With `operation.advice_below` set, a survivor scoring below that value sees its own Eval weaknesses once, as a
suggestion it may ignore. Other agents' notes are never shown.

## 8. Agent step
An agent's first message holds its last report, its budget, the priority (the main files are the only thing scored),
its file list and its files' current text. Its tools are `write_file`, `edit_file`, `delete_file`, `read_file`,
`list_files`, `run_script`, `spawn_subagents` and `finish`, plus the connector's tools. A step ends on `finish`, a
reply with no tool calls, a cap, or a model failure.

A tool mistake never crashes the run: the agent gets an error it can read.

## 9. Stopping and the final pick
| Reason | Cause | Pick |
|---|---|---|
| `threshold` | Loop score reached the target | Op. Orch |
| `max_loops`, `max_cycles` | The limit was reached | Op. Orch |
| `time_limit` | At a cycle end, the next cycle won't fit `operation.max_minutes` | Op. Orch |
| `time_limit` | Time ran out inside a cycle, which then isn't scored | Fallback |
| `stopped_by_user` | `run.py stop` | Fallback |
| `budget:<kind>` | A budget cap stopped the run | Fallback |
| `error: ...` | Unexpected failure | None; the error is raised |

The target is the connector's `target_score` if it has one, else Op. Orch's threshold. The loop score scales an
agent's finite cycle scores to a whole loop. The fallback pick takes the current agent with the best loop score and
needs no model call. If Op. Orch's final reply fails, the fallback is used too.

## 10. The connector
A connector module exposes `make_connector(cfg, data=None)`. The object must have `brief`, `n_steps`, `release`,
`begin_cycle`, `run_step`, `cycle_score`, `tools`, `cleaning_rules` and `starter_files`. It may have `steps_per_cycle`,
`target_score` and `script_files`. The full table is in `apex/connector.py`. `tests/test_core_is_generic.py` fails if
words about the task appear in `apex/` outside `env_connector/`.

## 11. The market task
- **Data:** `environment/fetch_prices.py` downloads prices (Yahoo) and context series (FRED). `build_chunks.py` splits
  them into steps, renames the assets and rebases prices to 100. `mapping.json` stays outside `apex/` and all run folders.
- **Agent's work:** `strategy.py` defines `weights(history)`. Weights are long only and sum to at most 1.
- **Backtest:** each cycle starts at $100,000 in cash. Weights are set before the day, traded at its open with a 0.1%
  fee, and valued at its close. The strategy runs in the sandbox and gets one day at a time over a pipe, so it never
  holds the day it trades or a later one.
- **Score:** cycle return minus the return of an equal-weight buy-and-hold, which pays no fees.
- **Target:** based on a 60/40 buy-and-hold, so the reference comes from outside the agents.
- **Tools:** `read_prices`, `wayback_fetch` (archived pages dated no later than the released step) and
  `backtest_report`. Scripts also get read-only `/data/prices.csv`, `/data/context.csv` and `/data/replay.py`.
- **Years:** the year and held-out year come from `task.settings`. Defaults are 2025 and 2022.

## 12. Keeping the future hidden
After a loop's last cycle the run wraps to the first step, so anything an agent kept could reveal the future.
- **Cleaner:** between cycles it deletes the data file and files that are data as a whole, replaces pattern matches
  with a `[cleaned <id>]` marker, and asks a small model for further facts. Dates, price levels and asset names are
  all cleaned. Deletions are logged with their originals under `hidden/cleaner/`, so Op. Orch can undo them. Data that
  can't be removed raises `CleanerError`.
- **Logs:** an agent's log lives outside its folder, since it holds released data.
- **Hidden folder:** Eval notes and Mutation output are in `<run>/hidden/`, outside every agent folder.

## 13. Sandbox
`run_script` runs an agent's Python file under bubblewrap. It sees its own folder at `/work`, `/usr`, the venv, chosen
read-only files and a small `/tmp`. It has no network, an empty environment (so no API key), and limits on memory, file
size and time. File tools stay inside the agent's folder after symlinks are followed.

## 14. Budget
- **Per cycle:** `budget.cycle_usd` for all roles together.
- **Per agent step:** `limits.call_tokens`, `call_turns`, and one `subagent_tokens` pool.
- Every call is checked before sending, with its worst case. With parallel agents the counters aren't locked, so a
  few calls can pass the cycle cap.
- `run.py estimate` gives the worst case for one cycle before a run.

## 15. Model access
`call_llm` uses the OpenAI SDK on Meta's Responses API. Only function tools are sent, because the built-in web search
has no date gate. `store=False` means callers send back earlier output items. `call_llm` does its own retries, so they
can be counted and logged. The key comes only from `$MODEL_API_KEY` and never appears in an error message.

Every role except generation 0 has a fallback when a call fails. A failed generation 0 stops the run with exit 1.

## 16. Run folder
| Path | Holds |
|---|---|
| `config.json` | The config the run used |
| `log.jsonl` | One JSON line per event |
| `final.json` | Stop reason and picked agent; not written if the run is killed |
| `agents/<id>/` | Each agent's files |
| `logs/<id>.jsonl` | Each agent's call log |
| `orch/log.jsonl` | Op. Orch's decisions and step summaries |
| `hidden/` | Eval notes, Mutation output, cleaner deletions |
| `holdout/` | The held-out copy, when that check runs |

## 17. Known limits
- A killed run has no final pick, and no run can be resumed.
- The held-out walk has no time check and no command of its own for a finished run.
- After a stop inside a cycle, `cycles` in `final.json` counts the cut cycle, and a step cut between agents has no
  `step` event.

## 18. Not built
These parts of the original design were left out: a hash-chained decision ledger, layered fitness scoring, rubric
windows, escalation on entropy spikes, freezing and deploying Agent Specs, Graph Config topologies, behavioral
signatures, causal attribution, and Docker sandboxes. `idea.md` keeps the original idea.

## 19. One-line definition
Apex evolves LLM agents on any task behind a connector, keeping the future hidden and every decision logged.
