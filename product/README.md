# Apex v1.0 (product)

A working slice of Project Apex (`../design.md`, `../CODE_STRUCTURE.md`) for the Global Meta AI hackathon. It evolves
bug-fixing agents with a (μ+λ) loop and UCB1 parent selection. Every step is recorded in a hash-linked, verifiable
ledger, and the final survivors are scored on held-out tasks they never saw.

v1.0 is the prototype (`../prototype/`, frozen) plus:
- **a real Meta model** through `apex/llm_service.py`: Muse Spark for the agents, Muse Code for mutation;
- **a 30 + 10 task corpus** with difficulty tiers;
- **new commands** to inspect the corpus, the cost and a run: `probe`, `estimate` and `stats`.

Status (2026-11-02): built with smoke checks only. The live checks and the first real run follow
`../1_11_test_plan.md`. The logic behind each change, with traces, is in `../LOGIC.md`.

It runs on Python 3.12+ with only the standard library, plus `git` (for `git apply`). There is nothing to install.

## Setup (for the real model)

```bash
cp .env.example .env && chmod 600 .env      # then set MODEL_API_KEY=... in .env
```

`run.py` and `tools/live_checks.py` read `.env` themselves, only when run as commands. Variables already exported in
the shell win. Tests never read `.env`, so the offline suite stays offline even with a real key on disk. The key is
only ever sent in the `Authorization` header, never written to the config, ledger, blobs or logs.

`configs/meta.json` pins the models and sizes the budget. Set the Muse Code ID there once `run.py models` lists it.

## Commands

Without a key (the fake model drives both roles):

```bash
python3 run.py corpus-check                   # every task: buggy code fails, the reference fix passes public + hidden
python3 run.py run --seed 1234                # evolve 8 generations, verify the ledger, write runs/<id>/report.md
python3 run.py verify runs/<run-id>           # re-verify any time: OK, or FAIL with the problems
python3 run.py report runs/<run-id>           # rebuild report.md
python3 run.py stats runs/<run-id> --tasks    # outcomes, parse errors, tokens, mutation acceptance (+ one row per task run)
python3 run.py estimate --config configs/meta.json   # worst-case token use of a config (no key, no model call)
python3 run.py probe                          # the baseline once on all 30 public tasks, one row each with its tier
python3 -m unittest discover -s tests         # all tests (~30 s)
```

The live checks, in the order of `../1_11_test_plan.md`. Steps marked *key* call the real API:

```bash
python3 tools/live_checks.py models     # key: model IDs the endpoint offers; copy the exact IDs into configs/meta.json
python3 tools/live_checks.py contract   # key: 4 real calls, the llm_service contract test for both roles
python3 tools/live_checks.py probe      # key: the baseline with the real model on all public tasks
python3 tools/live_checks.py estimate   # no key: the cost bound for configs/meta.json
python3 tools/live_checks.py run        # key: the first real run (runs/v1-meta-1), then verify
python3 tools/live_checks.py stats      # no key: statistics of that run
```

`live_checks.py` refuses to start a *key* step when `MODEL_API_KEY` is empty or still the `banana` placeholder.

## What happens in a run

1. **Genesis** records hashes of the config, the L0 gate definition, the public task manifest, the holdout manifest,
   the RNG seed and the seed agent (design §8).
2. **Generation 0** is the baseline agent (`seeds/baseline.json`) plus P − 1 single mutations of it. Each one is the
   root of its own lineage and has its own ledger branch.
3. **Each generation:**
   1. Sample one batch of K public tasks, shared by every agent in the generation.
   2. Run every agent on every task. The agent works in its own workspace, then the final patch is re-applied to a
      fresh copy and run against the public tests (L0 gates + L1), and then against the task's **hidden tests**.
   3. Keep the top μ by L1 (L0 failures are disqualified).
   4. Refill to P with children. Parents are chosen by UCB1 over lineages. Each child is one validated edit to either
      the graph (`json_patch`) or the axioms (`axiom_edit`), proposed by the mutation model from the parent's worst
      public trace. The proposal cites that trace's ledger block and the hash of the failing test output.
   5. Append a `generation_event` block and publish all branch heads.
4. **Final:** the survivors run once on the held-out tasks. `probe` skips this stage (design §9.1).

Hidden results go only to `runs/<id>/blobs-holdout/`; the ledger stores their hashes. Selection works on `PublicResult`
objects, which have no hidden field. The mutation prompt is built from `blobs/` only.

## How an agent works a task

The baseline agent is a small state machine (`seeds/baseline.json`):
- **The loop:** `plan` asks the model for one JSON action (`read_file`, `write_patch` or `give_up`). A read returns to
  `plan`. An applied patch ends the run, and a rejected one returns to `plan`.
- **What it can't do:** the baseline never runs the tests, so a wrong patch that applies still ends as "done".
- **What evolution adds:** typically a `run_tests` step after the patch, which loops back to `plan` on a failure, plus
  axioms learned from failing traces.
- **What the model sees:** the axioms, the task prompt, the editable files and the test command. It never sees the
  tier, the hidden tests or the reference fix.

`../LOGIC.md` ("Agent dynamics") walks through a task with the baseline and with an evolved survivor.

## Corpus

| | off_by_one | type_error | total |
|---|---|---|---|
| public (`corpus/public/`) | 15 | 15 | 30 |
| held-out (`holdout/tasks/`) | 5 | 5 | 10 |

- **Tests:** each task has 3 public tests and 2 hidden tests (`holdout/hidden_tests/` for public tasks).
- **Difficulty tiers** (`difficulty` in `task.json`, shown by `probe` and `stats --tasks`, never shown to a model):
  - **plain:** the prompt gives the error and the right output;
  - **symptom:** the prompt gives only the symptom;
  - **indirect:** the bug sits in a helper the named function calls.
- **Tuning:** the tiers were set by hand before any real-model data. The live probe retunes them (JC-43).
- **Regenerating:** `tools/make_corpus.py` rebuilds `corpus/`, `holdout/` and `oracle/`. Then run `run.py corpus-check`.

## Costs

`run.py estimate` gives a **worst-case** bound: every reply hits `max_tokens`, each call re-sends the history, and
mutation retries replay rejected replies. `configs/meta.json` is sized to that bound (tokens_total 9.4M, reserve
1.35M for the held-out stage) as a ceiling, not an expected spend. Lower it once the probe shows the real tokens per
task run (test plan step 4).

Known accounting gaps (`../LOGIC.md` R11–R13):
- the engine charges 0 for an HTTP attempt that failed but may still have been billed;
- the runtime reserve uses chars ÷ 4;
- a generation that runs over the cap partway through is discarded rather than finished.

## Layout

```
ARCHITECTURE.md        what is where: design-§5-style maps of every module, class and function (file:line)
run.py                 CLI: run | probe | verify | report | stats | estimate | corpus-check | models
apex/
  canonical.py         JCS-subset canonical JSON + sha256
  ledger.py            SQLite blocks/tips, blob stores, genesis/fork/append/publish_heads, verify()
  config.py            defaults (JSON, integer ppm), loader, config hash
  corpus.py            public task loading (difficulty tiers), manifests, batch sampling (never opens holdout/)
  sandbox.py           workspaces, the tools read_file / run_tests / write_patch, the patch policy
  testrunner.py        runs unittest in a workspace and reports through a nonce line
  models.py            ModelClient (pin check, retries, blob records, budget), Budget, the llm_service loader
  llm_service.py       the real-model adapter: Meta Responses API over stdlib urllib
  envfile.py           reads product/.env for run.py and tools/live_checks.py
  fake_model.py        the deterministic stand-in model
  prompts.py           subagent and mutation prompts; reads the JSON action out of a reply, even inside prose
  agent.py             graph/axiom validation, the graph interpreter
  evaluation.py        L0/L1, three-workspace evaluation, hidden checks, Clopper–Pearson (the only holdout reader)
  evolution.py         JSON Patch / axiom edits, UCB1, mutation, the generation loop
  stats.py             run statistics from the public record only (probe, stats)
  costs.py             the worst-case cost bound (estimate)
  report.py            report.md
seeds/baseline.json    the baseline agent (graph + axioms)
corpus/public/         30 public tasks: task.json, repo/, tests/
holdout/               hidden tests for each public task, and 10 held-out tasks
oracle/                reference fixes: used by the fake model and corpus-check only
tools/make_corpus.py   regenerates corpus/, holdout/ and oracle/
tools/live_checks.py   the live-check steps (models, contract, probe, estimate, run, stats)
configs/               meta.json (the real-model config), llm.example.json
.env.example           template for .env (MODEL_API_KEY)
tests/                 unit tests, the llm_service tests, the live contract test, and the CLI smoke tests
```

## Verifying and the tamper demo

`run.py verify` recomputes every block hash and checks:
- the parent, height and Lamport rules, `branch_id = sha256(parent ‖ agent_id)`, and that branches are linear;
- every stored blob;
- the tips table, and every published head in `heads.jsonl`.

To see it catch an edit, change one block body (on a copy of a run):

```bash
python3 -c "
import sqlite3; db = sqlite3.connect('runs/<run-id>/ledger.sqlite')
h, body = db.execute(\"SELECT block_hash, body FROM blocks WHERE kind='agent_run' LIMIT 1\").fetchone()
db.execute('UPDATE blocks SET body=? WHERE block_hash=?', (body.replace('terminal:done', 'terminal:DONE', 1), h)); db.commit()"
python3 run.py verify runs/<run-id>       # FAIL: block …: hash mismatch (content was edited)
```

Someone who rewrites *and rehashes* the whole ledger is caught by the published heads. Here those heads live inside
the run directory (JC-36), so keep a copy elsewhere and pass it:
`python3 run.py verify runs/<id> --heads /safe/place/heads.jsonl`.

## Deviations (see `../JUDGEMENT_CALLS.md`)

- **JC-33 / JC-41: subprocess sandbox, now with a real model.**
  - Task code runs in a subprocess inside a temporary copy, with a timeout, `prlimit` caps, a scrubbed environment and
    `unshare -rn` (no network). Both work on this host (`corpus-check` prints them).
  - Code under test still runs in the test runner's process, so only point the real model at our own corpus (design
    §14).
- **JC-34: the fake model is an oracle gated by axioms.** It applies a task's reference fix with high probability only
  if the agent's axioms mention the task's bug family. So fake runs exercise the machinery; they don't measure agents.
- **JC-35: stdlib substitutes.** Canonical JSON without floats (scores in integer ppm), `unittest`, JSON configs, and
  JSON Patch with add/remove/replace only.
- **JC-36:** the holdout and heads are inside the repo.
- **JC-37:** small defaults (P=4, μ=2, K=3, G_max=8). Override them with `--config`.
- **JC-39 / JC-40:** a stdlib Responses-API adapter, Muse Spark + Muse Code at `api.meta.ai/v1`, key in `MODEL_API_KEY`.
- **JC-42:** `.env` is loaded only by the commands.
- **JC-43:** corpus tiers set by hand, before any probe data.
- **JC-44:** the probe never runs held-out tasks, and the budget is sized to the worst-case bound.
- **JC-45:** the v1.0 build was smoke-checked only. Deeper tests follow `../1_11_test_plan.md`.
- **Determinism:** batches, mutation scopes and the fake model are seeded. L1's latency term comes from the wall
  clock, and so do block timestamps, which feed the block hashes used to break ties (evolution.py: sort by −L1,
  tokens, tip block hash). So two runs with the same seed can still select differently. A run is
  reproduced from its logged ledger (design §7), not by re-running it.

## The real-model adapter (`apex/llm_service.py`)

`LLMService(config).complete(role, messages, max_tokens)` turns the chat messages into a Responses API request:
- **Request:** POST `{base_url}/responses` with `model`, `instructions` (the system prompt), `input`,
  `max_output_tokens` and `store: false`.
- **Return value:** `{"text", "model_id", "usage": {"input_tokens", "output_tokens"}}`. `ModelClient` checks
  `model_id` against the pinned ID and charges `usage` to the budget.
- **Errors:**
  - HTTP 3xx, 400, 401, 403, 404 and 422 are not retried;
  - other HTTP errors, network errors and malformed replies are retried by `ModelClient` with backoff;
  - redirects are refused, so the key is never re-sent.
- **Key safety:** the key is scrubbed from every error message.
- **Listing models:** `list_models()` (GET `/models`) backs `run.py models`.

Its offline tests run against a local stub server (`tests/test_llm_service.py`). The contract test against the real
API (`tests/test_llm_contract.py`) is skipped unless `APEX_LLM_CONFIG` is set and `MODEL_API_KEY` holds a real key.
`tools/live_checks.py contract` sets `APEX_LLM_CONFIG` for that one test run only.
