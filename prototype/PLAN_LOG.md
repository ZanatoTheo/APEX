# PLAN_LOG — APEX prototype

The previous log (docs revision) is archived as `PLAN_LOG.docs.md`.

## Decisions
| ID | Decision | Source | Date |
|---|---|---|---|
| P-01 | Thin vertical slice (~10 modules) under `prototype/` | user (plan Q&A) | 2026-10-31 |
| P-02 | Fake model only; real adapter `apex/llm_service.py` is the single file left unwritten, with a fixed contract | user (plan Q&A + plan rejection note) | 2026-10-31 |
| P-03 | Python stdlib + subprocess "sandbox"; no Docker, no installs | user (plan Q&A) | 2026-10-31 |
| P-04 | Old plan archived to `PLAN.docs.md` / `PLAN_LOG.docs.md`; new PLAN.md for the prototype | user (plan Q&A) | 2026-10-31 |
| P-05 | Run under /bulldog (independent=true), freeze on `/home/theo/projects/APEX` | user | 2026-10-31 |
| P-06 | Prototype deviations from design logged as JC-33..JC-38 | plan Phase 0 | 2026-10-31 |

## Phase log

### Phase 0 — Setup and plan files (2026-10-31) ✔ (bulldog)
- **Done:**
  - Archived PLAN.md → PLAN.docs.md and PLAN_LOG.md → PLAN_LOG.docs.md.
  - Wrote a new PLAN.md and PLAN_LOG.md.
  - Logged JC-33..JC-38 in JUDGEMENT_CALLS.md.
  - Created the prototype/ skeleton.
- **Deviations from plan:** `unittest discover` with no tests exits 5 ("NO TESTS RAN"), not 0. The plan text is corrected.
- **Problems/bugs found:** the freeze hook blocks *reads* outside APEX in Bash, and it can't parse heredocs or `;`-chained commands. Workarounds: Write/Edit tools, and `&&` chains.
- **Review findings (checkpoint-reviewer), all fixed:**
  1. Exit-code text corrected.
  2. corpus-check reads the holdout through evaluation.py (stated in Phase 2).
  3. sha256 recorded: PLAN.md before the move and PLAN.docs.md after are both `beb5c242d287a267…`; PLAN_LOG `884292fa…` is also unchanged.
  4. JC-36 now says it overrides JC-15/JC-16; JC-38 explains why JC-02 option 1 is used.
  5. The tamper demo is a SQL UPDATE, and the run must take under 60 s.
  6. Clopper–Pearson reference values added.
  7. test_llm_contract added to the layout.
- **Verification:**
  - 38 `### JC-` entries.
  - sha256 matches.
  - PLAN.md shows Progress 0% (now 5%).
  - `python3 -m unittest discover -s tests` → "Ran 0 tests … NO TESTS RAN".

### Phase 1 — Canonical JSON and ledger (2026-10-31) ✔ (bulldog)
- **Done:**
  - `apex/canonical.py`: JCS subset with UTF-16 key order. It rejects floats, NaN, ints beyond 2^53, duplicate keys and lone surrogates, and every parse failure becomes a CanonicalError.
  - `apex/ledger.py`: BlobStore, plus the Ledger operations genesis/fork/append/publish_heads.
  - `verify(run_dir, heads_file=None, required_genesis_actions=())`: read-only and never raises. It checks hashes, the schema and field types, parent/height/clock rules, consecutive Lamport clocks, the branch_id derivation, agent_id consistency, linear branches, blob integrity, the tips table, and published heads (ancestor plus last-entry match).
  - Tests were written first. They failed with import errors before the code existed.
  - `tests/__init__.py` routes tempfile into `prototype/.tmp` (freeze).
- **Deviations from plan:** none in scope. verify has two extra parameters (an out-of-band heads file and the required Genesis actions); run.py uses them in Phase 5.
- **Problems/bugs found:** the first draft of the rehash test only rewrote branch_id on height-1 blocks. Fixed before the first run.
- **Review findings (checkpoint-reviewer), all fixed:**
  1. Type-checking of block fields; verify reports instead of raising, with a final safety net.
  2. Cycle-safe ancestor walk.
  3. loads maps ValueError and RecursionError to CanonicalError and rejects lone surrogates.
  4. Malformed heads lines are reported per line.
  5. verify creates no directories.
  6. The out-of-band `heads_file` parameter, plus a test. Keeping heads inside the run dir is still JC-36.
  7. All agent_ids on a branch must match.
  - Spec gaps: consecutive Lamport clocks (the single-writer form of max(parent, last)+1) and the Genesis action check are added. A DB-level UNIQUE(branch_id, parent_hash) was not added (the single writer makes it moot, and verify catches it).
- **Verification:** `python3 -m unittest tests.test_canonical tests.test_ledger` → `Ran 27 tests … OK`.

### Phase 2 — Corpus and subprocess sandbox (2026-10-31) ✔ (bulldog)
- **Done:**
  - `tools/make_corpus.py` generates 8 public tasks (4 off_by_one, 4 type_error) with hidden tests, plus 4 held-out tasks (2 + 2), `oracle/<id>.diff` and `oracle/index.json`.
  - `apex/corpus.py` with type-validated task.json and sampling.
  - `apex/sandbox.py`:
    - The Workspace and its tools.
    - The patch policy: a/ b/ prefixes required, denied names at any depth, editable_paths, no rename/mode/binary/new/delete hunks.
    - Test runs go through `apex/testrunner.py`, which reports with a nonce line, exits with os._exit, and must have an exit code that agrees with its result.
    - The process group is always killed, prlimit caps apply, and the tests hash is re-checked after every run.
  - `apex/evaluation.py`: the holdout reader.
  - `run.py corpus-check`.
- **Deviations from plan:**
  - 4 held-out tasks instead of ~2 (more trials for the confidence intervals).
  - Diffs come from `difflib`, not `git diff --no-index`. The generator is kept for reproducibility.
  - Fixes live in `oracle/`, outside holdout/, because the fake model needs held-out fixes too.
  - task.json `test_command` is display-only; the runner always runs unittest discovery.
  - `unshare -rn` is not permitted on this host, so there is no network isolation (JC-33). prlimit caps are on.
- **Problems/bugs found:** none beyond the review.
- **Review findings (checkpoint-reviewer), all fixed:**
  1. A fake unittest summary from agent code: fixed with the nonce runner. Deeper in-process tampering stays accepted under JC-33.
  2. Test tampering was not detected: the hash is now re-checked, and a change is a "tests modified" violation.
  3. `git apply -p1` vs the policy for unprefixed paths: a/ b/ prefixes are now required, quoted paths are rejected and `diff --git` lines are checked. Regression tests added.
  4. Leaked child processes and an unbounded communicate.
  5. PATH and `python3`: the runner uses sys.executable, and the caps status is printed.
  6. Workspace init leak.
  7. task.json types and the sample() bounds.
- **Verification:**
  - `python3 -m unittest tests.test_sandbox` → Ran 16 tests OK.
  - `python3 run.py corpus-check` → 12/12 OK (buggy fails public, the fix passes public and hidden), "corpus-check: OK" in 3.5 s.

### Phase 3 — Model layer, prompts, fake model, agent runtime (2026-10-31) ✔ (bulldog)
- **Done:**
  - `apex/config.py`: JSON defaults (ppm ints), strict merge and validation, path resolution, hash.
  - `apex/models.py`: the llm_service contract docstring, a loader with a clear "llm_service.py is missing" error, a pin-placeholder check, ModelClient (shape check, pin check, retries with backoff, blob record, budget charge) and a thread-safe Budget.
  - `apex/prompts.py`: real subagent and mutation prompts, delimited tool output, robust JSON extraction.
  - `apex/fake_model.py`.
  - `apex/agent.py`: graph and axiom validation per design §16, and the interpreter.
  - `seeds/baseline.json`.
  - Tests: test_agent and test_llm_contract (the llm_service class runs automatically once the file exists).
- **Deviations from plan:**
  - config is a validated dict, not a dataclass.
  - Default token_budget is 20000 (was 8000), so a real model has room.
  - check nodes support one predicate, `has_patch` (JC-08).
- **Problems/bugs found:** none beyond the review.
- **Review findings (checkpoint-reviewer):**
  1. The fake oracle covers held-out tasks: **by design** (JC-34; held-out success = skill transfer). A note is added to JC-34, and the README will say it. Code not changed.
  2. llm→llm without a user turn: a "Continue" turn is added.
  3. The budget pre-check now includes the prompt estimate. A per-call timeout is required in the contract docstring.
  4. An llm node without an error edge now retries in place, bounded by max_steps.
  5. History growth: tool outputs older than the last 4 messages are shortened to 600 characters, and token_budget is 20000.
  6. JSON extraction requires the "outcome"/"format" key.
  7. A forged opening `<tool_output` is escaped.
  - Lower-priority items: word-start skill keyword match, an empty-read guard, mutation retries replay the rejected reply, and the mutation prompt documents axiom_refs/predicate.
- **Verification:** `python3 -m unittest tests.test_agent tests.test_llm_contract` → Ran 26 tests OK (skipped=3: the llm_service contract class, absent by design).

### Phase 4 — Evaluation and evolution loop (2026-10-31) ✔ (bulldog)
- **Done:**
  - `apex/evaluation.py`:
    - L0 gate definition v1, L1 in ppm, and the three-workspace evaluate_task.
    - PublicResult and TaskPublic, with no hidden field.
    - Fitness Records: the public copy, plus a hidden copy written by write_hidden_fitness, which returns only a hash.
    - Clopper–Pearson by bisection, evaluate_heldout, and holdout_report for the report.
  - `apex/evolution.py`:
    - JSON Patch subset and axiom_edit.
    - UCB1 with delayed credit, pending visits within a call and redraw exclusion.
    - make_child: trace-guided, retries replay the rejected reply, and the proposal record carries the attribution.
    - The loop: seeding, a thread pool for task runs with a single-writer append, ranking with tie-break, rollback, refill, generation_event, publish_heads, final held-out, summary.json.
- **Deviations from plan:** the determinism test is narrowed to what the seed fixes (generation 0, batches, model replies). Selection after generation 0 can differ between runs because of wall-clock latency and timestamps in the hash tie-break; this is documented in the README and was accepted in CODE_STRUCTURE §5.2.
- **Problems/bugs found:**
  - The Clopper–Pearson lower bound had the wrong target (α/2 instead of 1−α/2). Fixed before the first test run.
  - The isolation test regex matched a docstring; it now matches code identifiers only.
  - `test_same_seed_same_selection` was flaky (see the deviation).
- **Review findings (checkpoint-reviewer):**
  1. A non-reproducible hash tie-break: **accepted/documented** (above). No code change.
  2. A missing or contradicted test result dropped out of the pass-rate denominator: it now counts as 0 of at least 1.
  3. The UCB1 redraw repeated the failed lineage: it is now excluded.
  4. Non-InfraError exceptions escaped run(): any evaluation exception now aborts the generation atomically, and run() always closes the ledger and cleans up (try/finally).
  5. Children were mutated in the last generation and never evaluated: skipped now.
  6. The budget check didn't reserve for in-flight calls: Budget.reserve/settle added, with a test.
  7. A stale payload in proposal records: reset on every attempt.
- **Verification:**
  - `python3 -m unittest tests.test_evolution` → OK, including Clopper–Pearson 0/10 → [0, 0.3085], 10/10 → [0.6915, 1] and 5/10 → [0.1871, 0.8129] within ±0.0005.
  - Full suite: Ran 88 tests OK (skipped=3).

### Phase 5 — CLI, report, smoke test, README (2026-10-31) ✔ (bulldog)
- **Done:**
  - `run.py` commands: run, verify (`--heads` for an out-of-band copy), report, corpus-check.
  - `apex/report.py`, plus `evaluation.holdout_report`, so hidden numbers are read only in evaluation.py.
  - `tests/test_smoke.py` (CLI end to end).
  - `README.md`: quickstart, run walkthrough, layout, tamper demo, deviations, "Adding llm_service.py".
  - `configs/llm.example.json`.
  - A clean sample run in `prototype/runs/demo-1234/`.
- **Deviations from plan:**
  - Default G_max raised from 5 to 8. The first demo after the Phase 4 fixes evolved no skill. In 4 probe runs, G_max=5 evolved one skill per run and G_max=8 evolved both. JC-37 and PLAN deviation 5 are updated.
  - `report` no longer takes `--config`: the baseline now comes from the run's own summary.json.
- **Problems/bugs found:**
  - A spurious "agent_id differs" line after tampering with a branch's first block. Fixed in verify.
  - The demo report crashed on a run made before summary.json recorded the seed agent. The demo was regenerated; prototype runs have no backward compatibility.
- **Review findings (checkpoint-reviewer):**
  1. `--model` default silently overrode a config's provider: it is now only an override.
  2. InfraError escaping the loop: **false positive**. evolution.py:304 already catches every evaluation exception (since the Phase 4 fix).
  3. The exact pin match is now documented in the contract and README.
  4. The contract test now covers the mutation role and skips cleanly without APEX_LLM_CONFIG. The README explains APEX_LLM_CONFIG vs --config.
  5. Any startup failure is caught, reported, and an empty run dir is removed.
  6. `report` on a dir without summary.json gives a clean error. The baseline comes from the run. A non-object config raises ConfigError.
  7. Held-out intervals: the pooled row is labelled correlated/optimistic, with a note that n=4 intervals are wide.
- **Verification (actual output):**
  1. `python3 -m unittest discover -s tests` → `Ran 91 tests … OK (skipped=4)`. The 4 skips are the llm_service contract class, absent by design.
  2. `time python3 run.py run --seed 1234 --run-id demo-1234` → 12.1 s. Report: best L1 rises from 60.3% (gen 0) to 99.0% (gens 5–7). The best agent gains types (gen 1), a verify loop (gen 4) and boundary (gen 5). Held-out is 8/8, pooled 95% CI [0.631, 1.000].
  3. `python3 run.py verify runs/demo-1234` → OK.
  4. After the SQL UPDATE of one agent_run body: `FAIL` + "hash mismatch (content was edited)", exit 1. Shown on a scratch copy of the demo, which was then regenerated clean.
  5. The README section "Adding llm_service.py" is present. Without the file, `run --model llm` exits 2 with the pointer message and leaves no run dir.

## Failed attempts
<!-- Format: tried X, failed because Y -->
- 2026-10-31 · Phase 0 · tried `cp ~/.claude/plans/<plan>.md PLAN.md`: the freeze hook blocked it because the *source* path is outside APEX (the hook doesn't distinguish reads). Wrote PLAN.md with the Write tool from the approved text instead.
