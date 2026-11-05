# Project Apex: Code Structure

How the code is laid out. `design.md` says what the system does; `README.md` has the commands.

## Stack
Python 3.12, the OpenAI SDK and `httpx` for model calls, `numpy` and `pandas` for agents' strategies, `pytest` for
tests, and `bwrap` (bubblewrap) for the sandbox. Configs are JSON.

## Layout
```
run.py            command line: run, estimate, models, stop
apex/             the core, which knows nothing about the task
  env_connector/  the market task
  tools/          the tools every agent gets
configs/          run configs: default, live, run1-run5
environment/      price data and the files built from it
tests/            fake models and fake HTTP only
  fixtures/       toy connector and small data files
tools/            checks of the live API
```

## `apex/`
| File | What it does |
|---|---|
| `operation.py` | The run: steps, cycles, stop checks, held-out walk |
| `orchestrator.py` | Op. Orch: generation 0, next generation, deletion review, final pick |
| `call_agent.py` | One agent, one step: the tool loop and subagents |
| `agent.py` | An agent's state and folder |
| `prompts.py` | Every prompt |
| `selection.py` | Ranking, survivors, bases, worse-child penalty |
| `evaluator.py` | Eval's hidden notes |
| `mutation.py` | Mutation's drafts |
| `summarizer.py` | The per-step summary |
| `cleaner.py` | Removes task data from agents' files, with undo |
| `connector.py` | The connector interface and loader |
| `llm.py` | `call_llm`, retries, cost |
| `jsonreply.py` | Asks a model for a checked JSON object |
| `budget.py` | Dollar, token and turn caps |
| `estimate.py` | Worst-case cost of a cycle |
| `config.py` | Defaults and config checks |
| `envfile.py` | Reads `.env` |
| `runlog.py` | Writes `log.jsonl` |
| `fake_model.py`, `fake_run.py` | The scripted models for tests and `--fake` |

## `apex/tools/`
| File | What it does |
|---|---|
| `__init__.py` | Builds the core tool set |
| `registry.py` | `ToolSet`: runs a model's tool call and turns mistakes into readable errors |
| `files.py` | File tools kept inside the agent's folder |
| `sandbox.py` | `run_script` and `Session` under bubblewrap |

## `apex/env_connector/`
| File | What it does |
|---|---|
| `__init__.py` | The connector: release, scoring, tools, cleaning rules |
| `brief.md` | The task brief agents read |
| `feed.py` | Loads and checks the chunk file; hands out released days |
| `backtest.py` | Trades a portfolio day by day |
| `runner.py` | Runs a strategy inside the sandbox, one day at a time |
| `replay.py` | Lets an agent replay its strategy on released days |
| `starter_strategy.py` | The strategy a new agent starts with |
| `wayback.py` | The date-gated `wayback_fetch` tool |

## `environment/`
| File | What it does |
|---|---|
| `assets.json` | The assets and context series to fetch |
| `fetch_prices.py` | Downloads prices to `data/prices.csv` |
| `build_chunks.py` | Builds the training file, held-out file and `mapping.json` |
| `start.py` | Builds the files, shows the worst-case cost, starts a run |

## `tools/`
| File | What it does |
|---|---|
| `live_calls.py` | Five checks of the live API |
| `parallel_calls.py` | Checks that the API takes calls at the same time |

## Rules the layout keeps
- Only `apex/env_connector/` and `environment/` know the task. `tests/test_core_is_generic.py` checks this.
- `runner.py` and `replay.py` run in the sandbox and never import `apex`.
- Secrets never go in configs. The key is read from `$MODEL_API_KEY`, which `.env` can set.
- Tests never send a real request.
