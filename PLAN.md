# Plan: APEX simple working prototype (thin vertical slice)
Progress: 100%

## Context
The docs plan (design.md + CODE_STRUCTURE.md) is complete (100%, archived as `PLAN.docs.md` / `PLAN_LOG.docs.md`). The next step is a **simple working prototype** that runs the whole Apex loop end to end on this machine. It should show (μ+λ) evolution of bug-fixing agents over a hash-linked, verifiable ledger, with a hidden holdout and a final report.
User decisions (2026-10-31):
- **Scope:** thin vertical slice, about 10 modules.
- **Model:** fake model only.
- **Runtime:** stdlib + subprocess.
- **Plan files:** archive the old ones and write a new PLAN.md.

Environment facts: Python 3.14 and git are present. There is no pip, uv, Docker or API key.

**Completeness target (user, 2026-10-31):** the prototype is complete except for `apex/llm_service.py`, the real-model adapter. The plan does not write that file. Everything around it is built for a real LLM:
- **Prompts:** the subagent and mutation prompts are real prompts, covering the system axioms, the tool descriptions, the JSON output contract, the unified-diff format and delimited tool output.
- **Parsing:** model output is parsed robustly. JSON wrapped in code fences or surrounded by prose is extracted, and bad output becomes the `error` outcome or a mutation retry.
- **Usage:** token usage is taken from the model's reported counts, not estimated.
- **Plug-in point:** selecting `--model llm` loads `apex.llm_service.LLMService`. If the file is absent, the run stops with a clear message pointing to the contract in the README.

The fake model is the default model and the stand-in for the tests. It consumes the same prompts and returns the same output format, so swapping in the real service changes no other file.

**`llm_service.py` contract** (in `apex/models.py` docstring + README):
```python
class LLMService:
    def __init__(self, config: dict): ...          # config["models"][role] → model_id etc.; keys from env vars only
    def complete(self, role: str, messages: list[dict], max_tokens: int) -> dict:
        # messages: [{"role": "system"|"user"|"assistant", "content": str}]
        # returns {"text": str, "model_id": str, "usage": {"input_tokens": int, "output_tokens": int}}
```
`models.py` wraps any service. The wrapper checks `model_id` against the pinned ID in config, records each request and response as a blob, and charges the budget.

**Prototype deviations from design/CODE_STRUCTURE** (each logged as a JC in `JUDGEMENT_CALLS.md` in Phase 0):
1. **No security sandbox.** Task code runs in a temp-dir copy via `subprocess`, with a timeout, `resource` rlimits and a scrubbed env. It uses `unshare -rn` for no-network only if that works unprivileged. This is not §14 isolation.
2. **The fake model is an oracle gated by axioms.** The subagent role returns a task's reference `solution.diff` only when its prompt axioms contain the skill keyword for that task's distribution (`boundar` → off_by_one, `type` → type_error). Otherwise it succeeds with a low seeded probability. The probability is higher on a retry that sees failing test output, which needs a verify loop in the graph. Token use is `len(text)//4`, so long axioms cost L1. The point is to exercise the machinery, not to measure real agents.
3. **Stdlib only.**
   - Canonical JSON is a JCS subset: sorted keys, compact separators, UTF-8. It rejects floats, NaN, ints beyond ±2^53 and duplicate keys. Scores are stored as integer ppm.
   - Tests are written with `unittest`, not pytest.
   - Config files are JSON, not YAML.
   - JSON Patch supports only add, remove and replace.
4. **Holdout and heads stay inside the repo.** The holdout is in `prototype/holdout/` and the heads file is `runs/<id>/heads.jsonl`. Isolation holds by convention: only `evaluation.py` reads the holdout.
5. **Smaller defaults:** P=4, μ=2, K=3, G_max=8 (planned 5; raised in Phase 5, see PLAN_LOG), 8 public + 4 held-out tasks (planned ~2). Budget and attribution are minimal stubs.
6. Open JCs keep their logged default options (e.g. JC-02 option 1).

## Layout (all new, under `APEX/prototype/`)
```
prototype/
  README.md            quickstart + deviations list
  run.py               argparse CLI: run | verify | report | corpus-check
  apex/
    canonical.py       JCS-subset dumps/loads + I-JSON guards; sha256 helper
    ledger.py          SQLite blocks/tips + blobs/ and blobs-holdout/; genesis, fork, append (Lamport), publish_heads, verify
    config.py          dataclass RunConfig, JSON load, config hash
    corpus.py          load task.json files, seeded batch sampling (never opens holdout/)
    sandbox.py         Workspace: copy repo, read_file / run_tests / write_patch (git apply --check; editable_paths, denied_paths, no rename/binary)
    models.py          ModelClient wrapper (pin check, blob recording, budget charge) + loader: "fake" | "llm" → llm_service
    fake_model.py      FakeModel implementing the LLMService contract (roles "subagent", "mutation")
    llm_service.py     NOT WRITTEN — the one missing piece (contract above)
    prompts.py         real system/user prompts for subagent and mutation roles; robust JSON extraction from replies
    agent.py           graph validation + interpreter (llm / tool / terminal nodes; JSON {"outcome","args"} contract; max_steps)
    evaluation.py      L0 gates, L1 (§9 formula, ppm ints), hidden check → blobs-holdout, Clopper–Pearson (bisection)
    evolution.py       seeding, UCB1 (lineage arms, delayed credit), mutation (json_patch subset / axiom_edit, max_attempts, redraw rule), generation loop per CODE_STRUCTURE §5.2
    report.py          report.md: per-generation best/mean L1, survivors, held-out rates + 95% CI, published heads
  seeds/baseline.json  baseline Graph Config (plan ⇄ read_file; plan → write_patch → done | back to plan on reject) + generic axioms (no skill keywords)
  corpus/public/<id>/  task.json, repo/, tests/, solution.diff (4 off_by_one + 4 type_error)
  holdout/             hidden_tests/<public_id>/, tasks/<held_out_id>/ (1 per distribution)
  tests/               test_canonical, test_ledger (incl. tamper), test_sandbox, test_agent, test_llm_contract, test_evolution (ucb1, patches, CP), test_smoke (e2e)
```

## Phase 0 — Setup and plan files (weight 5%) [x]
- Files:
  - Move the old plan files with a plain `mv`: `PLAN.md` → `PLAN.docs.md` and `PLAN_LOG.md` → `PLAN_LOG.docs.md`.
  - Write a new `PLAN.md` (this plan) and `PLAN_LOG.md` (Decisions / Failed attempts).
  - Append JC-33..JC-38 for deviations 1–6 to `JUDGEMENT_CALLS.md`.
  - Create the `prototype/` skeleton.
- Verification: `PLAN.docs.md` has the same sha256 as the old PLAN.md (recorded before and after the move). The new PLAN.md shows Progress 0%. `cd prototype && python3 -m unittest discover -s tests` runs and reports "NO TESTS RAN" (exit 5 on Python 3.12+, expected with no tests yet).

## Phase 1 — Canonical JSON and ledger (weight 20%) [x]
- Files: `apex/canonical.py`, `apex/ledger.py`, `tests/test_canonical.py`, `tests/test_ledger.py`
- Actions: implement CODE_STRUCTURE §5.1 pseudocode (fork/append/publish_heads/verify) and §6.4 storage on SQLite + `blobs/<aa>/<sha>`. Write failing tests first.
- Verification:
  - `python3 -m unittest tests.test_canonical tests.test_ledger` passes.
  - Tests cover: rejecting dup keys, NaN, floats and 2^53+1; editing one block body makes verify fail; rehashing every block makes verify fail on the heads mismatch; editing a blob makes verify fail.

## Phase 2 — Corpus and subprocess sandbox (weight 20%) [x]
- Files: `corpus/**`, `holdout/**`, `apex/corpus.py`, `apex/sandbox.py`, `run.py corpus-check`, `tests/test_sandbox.py`
- Actions:
  1. Write 10 tiny tasks. Each `solution.diff` is generated with `git diff --no-index` from a fixed copy, which is then deleted.
  2. Build the tools with the denied-paths list from CODE_STRUCTURE §5.6.
- Verification:
  - `python3 run.py corpus-check` reports, for every task: buggy → public tests fail; solution → public and hidden tests pass. The hidden-test half calls the holdout reader in `apex/evaluation.py` (an operator check, not agent or selection code), so "only `evaluation.py` reads the holdout" still holds. In Phase 2 this reader is a small `holdout_*` section that Phase 4 extends.
  - Sandbox tests show write_patch rejects `tests/`, a nested `conftest.py`, a rename hunk and paths outside `editable_paths`; read_file rejects `../` escapes; a sleep-forever test hits the timeout.

## Phase 3 — Model layer, prompts, fake model, agent runtime (weight 15%) [x]
- Files: `apex/models.py`, `apex/prompts.py`, `apex/fake_model.py`, `apex/agent.py`, `seeds/baseline.json`, `tests/test_agent.py`, `tests/test_llm_contract.py`
- Verification:
  - `test_llm_contract` runs the contract checks against the fake model: return shape, usage ints, `model_id` pin, and a reply wrapped in code fences that still parses. When `apex/llm_service.py` exists it runs the same checks against it, otherwise it is skipped.
  - `--model llm` without the file exits with the "llm_service.py missing" message.
  - The task prompt lists the editable files, so a real model can call read_file on them.
  - Graph validation rejects duplicate ids, unknown targets, unknown tools and graphs with no reachable terminal.
  - An agent with the `boundar` axiom fixes an off_by_one task, and the baseline fails it for the fixed seed.
  - Every step is recorded as a transition with a blob `result_hash`.
  - Hitting max_steps gives outcome `max_steps`.

## Phase 4 — Evaluation and evolution loop (weight 25%) [x]
- Files: `apex/evaluation.py`, `apex/evolution.py`, `apex/config.py`, `tests/test_evolution.py`
- Actions:
  1. L0, L1 and the tie-break per design §9.
  2. The hidden check writes only to `blobs-holdout/`, and the ledger gets hashes only.
  3. UCB1 per §10.
  4. Mutation per CODE_STRUCTURE §5.5, citing the trace block hash.
  5. Rollback and stop rules per §10.
- Verification:
  - Unit tests: UCB1 picks unvisited lineages first and credits on the next generation; JSON Patch add, remove and replace; axiom_edit bounds; two-sided 95% Clopper–Pearson for 0/10 → [0, 0.3085], 10/10 → [0.6915, 1] and 5/10 → [0.1871, 0.8129] (±0.0005).
  - A test asserts the selection code never imports or reads holdout data (grep check plus a type check: PublicResult has no hidden field).

## Phase 5 — CLI, report, smoke test, README (weight 15%) [x]
- Files: `run.py`, `apex/report.py`, `tests/test_smoke.py`, `README.md`
- Verification (actual output reported):
  1. `python3 -m unittest discover -s tests` passes in full.
  2. `python3 run.py run --seed 1234` finishes in under 60 s, timed with `time`. Its `report.md` shows the best L1 per generation, with survivors gaining skill axioms, plus held-out rates with 95% CIs.
  3. `python3 run.py verify runs/<id>` prints OK.
  4. After the README's tamper demo changes one block body with a SQL `UPDATE`, verify prints FAIL. (Editing a raw byte of the file could just corrupt SQLite.)
  5. The README has a section "Adding llm_service.py" with the contract, the env-var key rule, and the command `python3 -m unittest tests.test_llm_contract`, followed by `python3 run.py run --model llm`.

## Process rules
- /checkpoint after every phase (checkpoint-reviewer, Haiku), then STOP and report. (Under /bulldog: review runs, no stop.)
- Commits: propose one per phase, but only after asking permission (rule 4). The git repo root is above APEX and has many unrelated deletions, so a commit would stage only `projects/APEX/` paths.
- Hard problems → hard-problem protocol (independent=false); under /bulldog (independent=true) solve and log every attempt.

Weights total: 100
