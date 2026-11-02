# Plan log

The prototype's log is now `prototype/PLAN_LOG.md`; the docs log is `PLAN_LOG.docs.md`.

## Open problems
- `MODEL_API_KEY` (Meta endpoint) is not set in this shell. Phases 2, 3 (real half), 6 and 7 need it.
- Muse Code model ID for the mutation role is still needed (`product/configs/meta.json` holds a `<set: …>`
  placeholder, so runs refuse to start). Needed before phase 2.
- The user's note on ideas_unhinged was cut off ("Let ideas_unhinged 3, 4, "). Read as "later days"; confirm.

## Noticed, not in scope
- `CODE_STRUCTURE.md` plans a Docker sandbox (§5.6), and Docker is installed on this machine now (it wasn't on the
  prototype host). With a real model writing patches, moving test runs into `--network=none` containers would close
  most of JC-33.
- `CODE_STRUCTURE.md` still says "Status: PENDING approval" and describes the ideal stack (uv, pydantic, Typer, YAML);
  the prototype's stdlib choices are logged as JCs but the document itself was never updated.
- `idea.md` refers to `ideas_unhinges.md`; the file is `ideas_unhinged.md`.
- This host has Python 3.12.3 (prototype was built on 3.14); the full suite passes (91 OK, 4 skipped, 13.7 s).
- `apex/ledger.py` `verify` never compares the genesis `public_manifest` / `holdout_manifest` with the files on
  disk, so a changed corpus goes unnoticed (old runs still verify OK after phase 4 regenerated the corpus). The
  `corpus.manifest` docstring says a changed task is detectable; that holds only by hand-comparing hashes.
- A malformed `holdout/tasks/*/task.json` raises `CorpusError` after the last generation (only `InfraError` is
  caught around the held-out stage), so the run ends without a final summary. Low risk: make_corpus writes them.
- Token accounting (phase 6 review, LOGIC.md R11–R13): (1) an HTTP attempt that fails is charged 0 by
  `ModelClient` even if the provider billed it, so the real bill can exceed `spent` (up to retries+1 HTTP calls per
  logical call); (2) `hold` = chars // 4 can under-reserve code/JSON; (3) a mid-generation BudgetExceeded becomes an
  infra error that discards the whole generation, and the held-out stage has no gate. Engine changes, not in v1.0 scope.

## Log
- 2026-11-01: moved the finished prototype plan to `prototype/PLAN.md` / `prototype/PLAN_LOG.md`; `PLAN.md` at the
  root is a symlink to `1_11_plan.md` so the progress hook and /checkpoint find it.
- 2026-11-01: plan created (0/100).
- 2026-11-01: decisions (user): v1.0 lives in `product/`, a copy of `prototype/` (prototype frozen); Meta Responses
  API at `https://api.meta.ai/v1`, key `MODEL_API_KEY`; stdlib `urllib`, no `openai` SDK; subagent `muse-spark-1.3`,
  mutation a Muse Code model; `ModelClient` skips retries on `retryable = False` (HTTP 400/401/403/404/422).
- 2026-11-01: phase 1 work done: `product/` copied (91 tests OK there); tests written first (import error + `4 != 1`
  before the code); `llm_service.py`, config keys `base_url` / `request_timeout_s`, retry check, `configs/meta.json`.
  `python3 -m unittest discover -s tests` → Ran 110 tests, OK (skipped=6). The CLI smoke test for a missing
  llm_service.py now skips by design; the no-key CLI path was checked by hand (exit 2, no run dir).
- 2026-11-01 Phase 1 product/ + llm_service.py (Meta Responses API, offline): done (0 → 15/100) — 113 tests OK
  (skipped=6). Review fixes, each test-first: a total call deadline (body read in chunks; a slow-drip reply used to
  outlive request_timeout_s), base_url check uses fullmatch (a trailing newline passed and then failed at call time
  with a retried ValueError; ValueError now maps to a non-retryable error), the key is scrubbed from "failed" replies
  too, stub fixes (reply fixed per request, free port instead of port 9, timeout test checks "timed out").
  Left as is: worst case ≈ 2 × request_timeout_s; a server dripping *headers* is still bounded only per read.
- 2026-11-01 Phase 2: added `product/.env.example` (MODEL_API_KEY, APEX_LLM_CONFIG) and `.env` to `product/.gitignore` (checked with git check-ignore). Live commands load it with `set -a; . ./.env; set +a`.
- 2026-11-01: decisions (user): write all code for phases 2–9 now; every check that needs the real key is deferred
  to the user (`product/.env` holds `MODEL_API_KEY=banana` as a placeholder). `/checkpoint` per phase; phases with
  a live part stay `[~]` (code done, live check pending). `run.py` loads `product/.env` when run as a command, never
  in tests. Corpus tiers (plain / symptom / indirect) are fixed without probe data and retuned in phase 6.
  Plan detail: `~/.claude/plans/breezy-singing-cookie.md`.
- 2026-11-01 Phase 2 .env loading, model listing, live-check tool: code done, live check pending (stays [~], 15/100)
  — 136 tests OK (skipped=6), also OK with `.env` vars exported and outbound HTTPS blocked. Review fixes, test-first:
  the offline suite could reach api.meta.ai when a real key was exported (ModelsCommandTest now drops the key; the
  live contract class also skips on an empty/`banana` key; `APEX_LLM_CONFIG` left `.env.example` and is set only by
  `tools/live_checks.py contract`); `tools/live_checks.sh` replaced by `tools/live_checks.py`, which reads `.env`
  with the same parser as run.py (bash broke on `$`, spaces, CR); envfile handles BOM, CR, inline ` #` comments and
  last-wins; llm_service strips the key, refuses redirects (urllib resent the key header to the new host), and
  cleans the key before cutting error text (a key past char 300 leaked its start). User's `product/.env` still has an
  `APEX_LLM_CONFIG` line: harmless now unless the file is sourced; can be deleted.
- 2026-11-01: decision (user): the live checks pending from phase 2 (models, contract) move to the end of phase 3, with the live probe on the current 8 tasks; phase 4 waits for the probe table. Phases 2 and 3 get [x] after that run.
- 2026-11-01 Phase 3 probe + run statistics: code done, live checks pending (stays [~], 15/100) — full suite OK
  (skipped=6), also with `.env` vars exported and HTTPS blocked; fake probe 8 rows, verify OK; fake full run still
  evaluates held-out (4/4 per survivor). Review fixes, test-first: probe no longer runs held-out tasks (repeated
  probes would be a held-out feedback loop, design §9.1; `evolution.run(heldout=False)`); an aborted probe (e.g. 429
  after retries) now exits 1 with the stop reason instead of an empty table and exit 0; no stats after a failed
  verify; `stats.StatsError` names the stored block hash on a damaged ledger; tests match probe rows by column,
  `call()` turns argparse SystemExit into a code, and the holdout-isolation test records every file stats reads.
  Not changed (logged): an infra error in one task still discards the whole generation's results (atomic
  generations, CODE_STRUCTURE §5.2); if a live probe hits this, lower `budget.max_concurrent` in configs/meta.json.
- 2026-11-01: decision (user): build the rest of v1.0 now with smoke-level checks only; every deeper test (live
  checks, corpus tuning, failure-fix loop, deferred unit tests, whole-code review) moves to `1_11_test_plan.md`, run
  after the plan. Each build phase still ends with a full `/checkpoint` (reviewer). Plan re-numbered and re-weighted:
  the live-only phase and the live halves of old phases 7–8 left the plan; phases 2 and 3 ticked (their code was
  checkpointed). Progress 15 → 35/100. A one-off structure: not to be reused unless asked.
- 2026-11-01 Phase 4 corpus growth, off_by_one: done (35 → 53/100) — off_by_one now 15 public + 5 held-out
  (new public 3 plain / 4 symptom / 4 indirect, new held-out 1/1/1); optional `difficulty` in task.json and
  `corpus.Task`; tier column in the probe table; `test_evolution` counts held-out tasks instead of assuming 4.
  Checks: make_corpus → 19 + 7; corpus-check 26 OK; suite 149 OK (skipped=6). Review: fixed the ambiguous
  `obo_line_number` docstring; tuning notes (held-out tasks close to public ones, docstrings that state the rule)
  went to test plan step 3; the manifest and held-out CorpusError items went to Noticed.
- 2026-11-02: new working rule (user): write the code's logic down first, in `LOGIC.md` (traces, how each defined
  thing is used in the product, an issue log by stage); print tests and their explanation in chat before writing them.
- 2026-11-02 Phase 5 corpus growth, type_error: done (53 → 71/100) — type_error now 15 public + 5 held-out (new
  public 3 plain / 4 symptom / 4 indirect, new held-out 1/1/1); corpus 30 + 10. Checks: make_corpus → 30 + 10;
  corpus-check 40 OK; suite OK (skipped=6); fake `run --seed 1234` → verify OK, 2 survivors × 10 held-out; fake
  probe → 30 rows. Review: no code bug; two held-out tasks repeated public failure modes (`ho_te_checksum`,
  `ho_te_add_tag`) → replaced by `ho_te_count_unique`, `ho_te_format_all`; LOGIC.md wording fixed; prompt hints,
  `te_latest_version` ~ `ho_te_next_port`, older twin `ho_te_label` ~ `te_greeting` → test plan step 3;
  `te_latest_version` labelled type_error without a TypeError → JC for phase 8. Logic-strategy report in LOGIC.md
  issue log and the phase 5 recap.
- 2026-11-02: /bulldog started for phases 6–8 (user: stay on master, no branch; smoke-level checks; logic first in
  LOGIC.md, plus the agent-dynamics section). independent=true for the run.
- 2026-11-02 Phase 6 cost estimate and meta.json sizing: done (71 → 79/100) — new `apex/costs.py` (`estimate`,
  `format_estimate`; not in stats.py, whose guard test forbids naming the held-out store: LOGIC C1), `run.py
  estimate [--config]`. Review: the per-run bound was wrong (history is re-sent: run_cap = 2·token_budget + call) and
  mutation retries replay replies; fixed and re-traced (LOGIC R9–R10, all numbers match). meta.json budget →
  tokens_total 9 400 000 / holdout_reserve 1 350 000: a pessimistic ceiling, lower it after the live probe. Checks:
  estimate prints for both configs; missing config → exit 2; suite OK (skipped=6).

- 2026-11-02 Phase 7 `run.py stats`: done (79 → 87/100) — `stats RUN_DIR [--tasks]`: exit 2 when not a run, exit 1
  on damage (all reading and formatting in one try; no partial output); tiers only where the task.json still matches
  the run's genesis manifest (`stats.run_tiers`, else `?`); a corrupt summary.json no longer fails the command.
  Review findings R15–R20 in LOGIC.md (4 fixed, R19 logged, R20 wording). Checks: demo-1234 --tasks exit 0;
  runs/nope exit 2; deleted end blob / null steps / text ledger → exit 1; retuned tier → `?`; suite OK (skipped=6).
- 2026-11-02 Phase 8 docs and judgement calls: done (87 → 100/100) — product/README.md rewritten for v1.0 (setup,
  commands with/without key, agent dynamics, corpus, costs, layout, deviations, llm_service); idea.md "Status" (v1.0)
  and the ideas_unhinged.md link; JC-39..JC-45. Review R21–R27 all fixed, incl. one code change: tools/live_checks.py
  now loads .env only under `__main__` (as run.py). Checks: every keyless README command exit 0; corpus-check OK;
  JC count 45; suite OK (skipped=6).
- 2026-11-02: /bulldog finished, 100/100, no blocked phase. Not committed (user: ask first); on master as chosen.
- 2026-11-02 (outside the plan) product/ARCHITECTURE.md: design-§5-style ASCII mind maps of product/ — Map 0 (the
  system as built, with not-built boxes dashed), one map per component listing every constant, class, method and
  function with file:line and what it does, plus data, commands, tests (147) and known gaps. Says what, not how
  (user). Generated from the code by a scratchpad script (line numbers read via ast; fails if a definition is
  missing). First draft (Mermaid + how-it-works) was replaced after the user's amendment.
