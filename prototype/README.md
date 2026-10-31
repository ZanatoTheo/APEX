# Apex prototype

A small working slice of Project Apex (`../design.md`, `../CODE_STRUCTURE.md`). It evolves bug-fixing agents with a
(μ+λ) loop and UCB1 parent selection. Every step is recorded in a hash-linked, verifiable ledger, and the final
survivors are scored on a hidden holdout.

It runs on Python 3.12+ with only the standard library, plus `git` (for `git apply`). There is nothing to install.

**The one missing piece is `apex/llm_service.py`**, the adapter to a real model. Until it exists, a deterministic
fake model drives both model roles (see [Adding llm_service.py](#adding-llm_servicepy)).

## Quickstart

```bash
cd prototype
python3 run.py corpus-check                 # each task: buggy code fails, the reference fix passes public + hidden tests
python3 run.py run --seed 1234              # evolve for 8 generations (~12 s), verify the ledger, write report.md
python3 run.py verify runs/<run-id>         # re-verify any time: prints OK or FAIL with the problems
python3 run.py report runs/<run-id>         # rebuild report.md
python3 -m unittest discover -s tests       # all tests (~30 s)
```

`run` prints one line per generation and ends with `verify: OK` and the path of `runs/<run-id>/report.md`. The report
contains:
- **For each generation:** the batch, the best and mean public L1, the skills of the best agent, the survivors, and the L4 divergence (public − hidden pass rate).
- **For each final survivor:** its graph and the axioms it evolved beyond the baseline.
- **Held-out results:** success rates on the held-out tasks with 95% Clopper–Pearson intervals.
- **Published heads:** the branch heads published each generation.

## What happens in a run

1. **Genesis** records hashes of the config, the L0 gate definition, the public task manifest, the holdout manifest,
   the RNG seed and the seed agent (design §8).
2. **Generation 0** is the baseline agent (`seeds/baseline.json`) plus P − 1 single mutations of it. Each one is the
   root of its own lineage and has its own ledger branch.
3. **Each generation:**
   1. Sample K public tasks.
   2. Run every agent on every task. The agent works in its own workspace, then the final patch is re-applied to a
      fresh copy and run against the public tests (L0 gates + L1), and then against the task's **hidden tests**.
   3. Keep the top μ by L1 (L0 failures are disqualified).
   4. Refill to P with children. Parents are chosen by UCB1 over lineages. Each child is one validated edit to either
      the graph (`json_patch`) or the axioms (`axiom_edit`), proposed by the mutation model from the parent's worst
      public trace. The proposal cites that trace's ledger block and the hash of the failing test output.
   5. Append a `generation_event` block and publish all branch heads.
4. **Final:** the survivors run once on the held-out tasks.

Hidden results go only to `runs/<id>/blobs-holdout/`; the ledger stores their hashes. Selection works on `PublicResult`
objects, which have no hidden field, and the mutation prompt is built from `blobs/` only.

## Layout

```
run.py               CLI: run | verify | report | corpus-check
apex/
  canonical.py       JCS-subset canonical JSON + sha256
  ledger.py          SQLite blocks/tips, blob stores, genesis/fork/append/publish_heads, verify()
  config.py          defaults (JSON, integer ppm), loader, config hash
  corpus.py          public task loading, manifests, batch sampling (never opens holdout/)
  sandbox.py         workspaces, the tools read_file / run_tests / write_patch, the patch policy
  testrunner.py      runs unittest in a workspace and reports through a nonce line
  models.py          ModelClient (pin check, retries, blob records, budget), Budget, the llm_service loader + contract
  fake_model.py      the deterministic stand-in model
  llm_service.py     ← not written: the real-model adapter
  prompts.py         subagent and mutation prompts, robust JSON parsing of replies
  agent.py           graph/axiom validation, the graph interpreter
  evaluation.py      L0/L1, three-workspace evaluation, hidden checks, Clopper–Pearson (the only holdout reader)
  evolution.py       JSON Patch / axiom edits, UCB1, mutation, the generation loop
  report.py          report.md
seeds/baseline.json  the baseline agent (graph + axioms)
corpus/public/       8 public tasks (4 off-by-one, 4 type errors): task.json, repo/, tests/
holdout/             hidden tests for each public task, and 4 held-out tasks
oracle/              reference fixes: used by the fake model and corpus-check only
tools/make_corpus.py regenerates corpus/, holdout/ and oracle/
configs/             llm.example.json
tests/               unit tests, the contract test for llm_service, and the CLI smoke test
```

## Verifying and the tamper demo

`run.py verify` recomputes every block hash and checks:
- the parent, height and Lamport rules, `branch_id = sha256(parent ‖ agent_id)`, and that branches are linear;
- every stored blob;
- the tips table, and every published head in `heads.jsonl`.

To see it catch an edit, change one block body:

```bash
python3 -c "
import sqlite3; db = sqlite3.connect('runs/<run-id>/ledger.sqlite')
h, body = db.execute(\"SELECT block_hash, body FROM blocks WHERE kind='agent_run' LIMIT 1\").fetchone()
db.execute('UPDATE blocks SET body=? WHERE block_hash=?', (body.replace('terminal:done', 'terminal:DONE', 1), h)); db.commit()"
python3 run.py verify runs/<run-id>       # FAIL: block …: hash mismatch (content was edited)
```

Someone who rewrites *and rehashes* the whole ledger is caught by the published heads. In this prototype those heads
live inside the run directory (JC-36), so keep a copy elsewhere and pass it:
`python3 run.py verify runs/<id> --heads /safe/place/heads.jsonl`.

## Prototype deviations (see `../JUDGEMENT_CALLS.md`)

- **JC-33: no security sandbox.** Task code runs in a subprocess inside a temporary copy, with a timeout, `prlimit`
  caps and a scrubbed environment. It gets `unshare -rn` (no network) only where the kernel allows it; this host
  doesn't. The test runner resists faked results printed by agent code, and edits to tests are detected, but code
  under test runs in the runner's process. Do not point a real model at untrusted tasks without a real sandbox
  (design §14).
- **JC-34: the fake model is an oracle gated by axioms.** It applies a task's reference fix with high probability
  only if the agent's axioms mention the skill for that bug family ("boundar…" for off-by-one, "type…" for type
  errors). Otherwise its patch is usually a harmless no-op. Retries after a failing test run do better, which rewards
  graphs with a verify loop. The oracle covers held-out tasks too, so held-out success measures whether the evolved
  skill transfers to unseen tasks. Hidden tests are never shown to any model.
- **JC-35: stdlib substitutes.**
  - Canonical JSON follows RFC 8785 for the values allowed here. Floats are rejected, so all scores are integer
    **ppm**: the Fitness Record fields keep the design's names but hold ppm values.
  - Tests use `unittest`, configs are JSON, and JSON Patch supports add/remove/replace only.
- **JC-36: the holdout and heads are inside the repo.** They live in `holdout/` and `runs/<id>/heads.jsonl`,
  because the workspace freeze covers APEX/ only.
- **JC-37: small defaults.** P=4, μ=2, K=3, G_max=8, 8 public + 4 held-out tasks. Override them with `--config`
  (keys as in `apex/config.py` DEFAULTS).
- **Determinism:** batches, mutation scopes and the fake model are seeded. L1's latency term and the block
  timestamps used for tie-breaks come from the wall clock, so two runs with the same seed can still select
  differently. A run is reproduced from its logged ledger (design §7), not by re-running it.

## Adding llm_service.py

Create `apex/llm_service.py` with one class:

```python
class LLMService:
    def __init__(self, config: dict):
        # config is the full run config. config["models"]["subagent"|"mutation"]["model_id"] is the model ID
        # pinned for each role. Read API keys from environment variables only, never from the config.
        ...

    def complete(self, role: str, messages: list[dict], max_tokens: int) -> dict:
        # messages: [{"role": "system" | "user" | "assistant", "content": str}, ...]
        #   messages[0] is the system prompt; the rest alternate but may repeat a role (merge if your API needs it).
        # Return {"text": str, "model_id": str, "usage": {"input_tokens": int, "output_tokens": int}}
        #   model_id = the model the API says it served; it must equal the pinned ID exactly (pin the exact,
        #   e.g. dated, ID your API reports). usage = the API's own counts.
        # Raise on API/transport errors (ModelClient retries with backoff, then aborts the generation).
        # Use a request timeout (e.g. 120 s): the agent's run timeout is only checked between steps.
        ...
```

Everything else is already in place:
- **Prompts:** the system prompt carries the axioms and the action menu; the action format is
  `{"outcome": …, "args": …}`; tool output arrives in `<tool_output>` tags; the diff format is described.
- **Reply parsing:** JSON is extracted from plain replies, code fences or replies with prose around them. A bad
  reply becomes an `error` outcome, and the agent retries.
- **Records and budget:** every call is stored as a blob, and token use is charged from your `usage`.

Then:

```bash
cp configs/llm.example.json configs/llm.json            # set the two model_id values
export YOUR_PROVIDER_API_KEY=…                           # whatever your service reads
APEX_LLM_CONFIG=configs/llm.json python3 -m unittest tests.test_llm_contract   # contract tests (both roles)
python3 run.py run --config configs/llm.json            # provider "llm" comes from the config
```

The two ways to name the config are separate. `APEX_LLM_CONFIG` is read only by the contract tests, which are skipped
when it is unset. `run.py` reads only `--config`. `--model fake|llm` overrides the config's provider, and without
`--model` the config decides. Without the file, an llm run exits with a message pointing here, and a failure inside
your service's `__init__` (e.g. a missing key) is reported without leaving a run directory behind.
