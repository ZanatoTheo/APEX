# Apex

Apex evolves a group of LLM agents on a task, one step at a time. Every role (agents, subagents, Eval, Mutation,
the Summarizer, the cleaner and Op. Orch, the operator that picks, breeds and replaces agents) runs on
`muse-spark-1.3-contributor`. Calls go through the OpenAI SDK to `https://api.meta.ai/v1`.

Op. Orch's model can be chosen per run with `--orch_spark` (Spark Contributor, the default when neither flag is given)
or `--orch_wonder` (`muse-wonder-1.0`, normal pricing: Wonder has no contributor mode on pay-as-you-go). `run.py run`,
`estimate`, `models` and `environment/start.py` all take them.

The core in `apex/` knows nothing about the task. The task lives only in `apex/env_connector/` (today: trading 13
renamed assets through 2025) and `environment/` (price data and the files built from it). To change the task, change
only those two.

How the system works: `design.md`. Where each part lives: `CODE_STRUCTURE.md`. Results of the live runs:
`RUN1_RESULTS.md`, `DEMO_LOG.md`, and Run 5's cycle log in `runs/`.

## Setup
1. A Python 3.12 venv with the pinned packages (`openai`, `httpx`, `numpy`, `pandas`, `pytest`):
   ```
   python3.12 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```
2. `bwrap` (bubblewrap) on the PATH: agents' scripts run inside it.
3. The API key, in `.env` (`cp .env.example .env`; never in a config file, never committed):
   ```
   MODEL_API_KEY=...
   ```
   A key already set in the shell wins over the file.
4. Market data: `environment/data/` is not in git. Fetch it before a market run (step 3 of "Going live").

Tests use fake models and fake HTTP only; they never send a real request:
```
timeout 600 .venv/bin/python -m pytest -q
```

## Commands
| Command | What it does |
|---|---|
| `run.py run --connector <module> [--data <file>] [--holdout <file>] [--seeds <dir>] [--max-loops N] [--max-cycles N] [--fake] [--config <file>] [--out <dir>]` | runs the operation; `--fake` uses a scripted model (no API calls) |
| `run.py estimate [--config <file>] [--data <file>]` | the worst-case cost of one cycle, per role (with `configs/live.json`, `--data` is the training file, e.g. `environment/data/chunks_2025_gap1.json`) |
| `run.py models [--config <file>]` | checks that each role's model ID is available to the key |
| `environment/fetch_prices.py [--dry-run]` | downloads daily prices (Yahoo) and context series (FRED) to `environment/data/prices.csv` |
| `environment/build_chunks.py` | builds the training and held-out files and `mapping.json` from the CSV |
| `run.py stop [--run-dir <dir>] [--out <dir>]` | asks a running operation to stop cleanly |
| `environment/start.py [--time-gap N] [--holdout-year <year>\|none] [--skip-holdout] [--fake] [--max-loops N] [--max-cycles N] [--config <file>] [--out <dir>]` | builds the files, prints the worst-case cost, then runs; steps are 1 day unless `--time-gap` says otherwise |
| `tools/live_calls.py [--config <file>] [--dry-run]` | 5 checks of the real API (6 requests, about a cent) |
| `tools/parallel_calls.py [--config <file>] [--orch wonder\|spark] [--n N] [--dry-run]` | checks that the API takes a run's calls at the same time (real requests, under a cent per model) |

`configs/live.json` is the config for live runs: the market connector, longer retries (waits of 5, 10, 20, 40, 80 and
160 s, about 5 minutes per call), a 600 s request timeout (replies aren't streamed, so a 16,000-token Mutation reply
must arrive within it) and `max_cycles` 4. Everything else is the default (10 agents, $2.50 per cycle).
`configs/run1.json` to `run5.json` are the configs of the past runs (run 2 was never launched). `operation.parallel_agents`
(default 1) sets how many agents of a step work at the same time; `configs/run5.json` sets 6.

## Going live, in this order
1. Put the key in `.env` (see Setup).
2. `.venv/bin/python run.py models --config configs/live.json`: every role's model is `found`.
3. `timeout 600 .venv/bin/python environment/fetch_prices.py`: 13 tickers and 3 FRED series, 2015–2025.
4. `.venv/bin/python tools/live_calls.py --config configs/live.json`: all 5 checks `ok`. Stop here on any `FAIL`;
   check 2 (the tool round trip) is the one agents can't work without.
5. Launch, detached so it survives closing the terminal:
   ```
   mkdir -p runs
   setsid nohup env PYTHONUNBUFFERED=1 .venv/bin/python environment/start.py --config configs/live.json \
     --skip-holdout > runs/night-$(date +%Y%m%d-%H%M).log 2>&1 &
   pgrep -f environment/start.py      # the process id, for stopping it ($! can be a dead pid after setsid)
   ```

## Watching a run
- `tail -f runs/night-<time>.log`: the `run dir:` line, then one line per cycle (best agent, money spent).
- `runs/<run dir>/log.jsonl`: one JSON line per event (`step`, `cycle_end`, `generation`, `cleaner`, `stop`, …).
- `runs/<run dir>/agents/<id>/`: each agent's files; `runs/<run dir>/logs/`: each agent's call log.
- `runs/<run dir>/final.json`: the picked agent and the stop reason, written when the run ends.

## Stopping a run
`.venv/bin/python run.py stop` (or `--run-dir runs/<dir>`) asks the run to stop cleanly: it ends before its next
agent step with reason `stopped_by_user`, a fallback pick and `final.json`. Use the kill below only if it hangs.

`kill -- -<pid>`, with the pid from `pgrep -f environment/start.py`. The minus sign stops the whole process group
(setsid made the run its leader), so a sandboxed script still running stops too. The run ends at once, without a final
pick: `log.jsonl` and the agent folders stay, `final.json` is not written. There is no resume.

## Cost and time
Per cycle: 28 one-day steps, 10 agents, every role on Spark Contributor (`run.py estimate`). The $2.50 cap per
cycle stops the run if a cycle reaches it.

| Case | Per cycle | 4 cycles |
|---|---|---|
| Worst case, Op. Orch on Spark (default) | $1.61 | $6.45 |
| Worst case, `--orch_wonder` | $2.44 | $9.76 |

Most of it is the agents ($1.01) and their subagents ($0.45); Op. Orch is about $0.01 on Spark and $0.84 on Wonder.

Run 1 averaged 38 s per agent step, which gives about 3 hours per default cycle (280 agent steps, one after another).
Run 5 (7-day steps, 6 agents at the same time, Op. Orch on Wonder) did 4 cycles in about 2 hours for about $0.71.
`tools/live_calls.py` prints the real latency per request.

`operation.max_minutes` (null by default; `configs/run1.json` sets 77) limits a run's time. At a cycle end, if the
next cycle would not fit (time so far + the last cycle's length), the run ends with reason `time_limit` and Op. Orch's
normal final pick. If the time runs out inside a cycle, the run ends before the next agent's step: that cycle is not
scored and the pick is the fallback from finished cycles (no model call). A step already running is not cut.
The check counts the generation before each cycle too. The held-out walk has no time check, so the limit
holds only with `--skip-holdout`.

The test year is set in the run config, under `task.settings` (free keys the core passes through unread):
`"task": {"connector": "apex.env_connector", "settings": {"year": 2022, "holdout_year": null}}`. Defaults: year
2025, held-out year 2022; `--holdout-year` on the command line wins. The held-out year must be before the year, so
for 2022 or earlier set `holdout_year` to null (history then starts in 2015) or an earlier year. `environment/start.py`
builds `chunks_<year>_gap<g>.json` from `prices.csv` (2015–2025); a year with no data stops before any model call.

## Known limits
- If the first Op. Orch call (generation 0) fails after its retries, the run stops at once (exit 1). Every later
  failed call has a fallback: the agent's step ends, Eval or Mutation give nothing, Op. Orch's fallback pick is used.
- The held-out walk of a finished run's picked agent has no command of its own yet; `start.py` without
  `--skip-holdout` runs it at the end of training.
