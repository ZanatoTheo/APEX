# APEX v1.0 test plan (run after `1_11_plan.md`)
Updated: 2026-11-01

The build in `1_11_plan.md` only runs smoke checks (user, 2026-11-01). Everything here is run **after** the build,
by the user with Claude, in this order. Commands run from `product/` unless noted. Steps marked **live** need the
real key in `product/.env` (`cp .env.example .env`, then fill `MODEL_API_KEY`); they spend tokens.

## 1. Setup and model IDs (live)
- `python3 tools/live_checks.py models` → lists the IDs. Copy the exact Muse Spark and Muse Code IDs into
  `configs/meta.json` (`models.subagent.model_id`, `models.mutation.model_id`).
- Pass: both pinned IDs show `(listed)`. If Meta has no `/models` route (HTTP 404), take the IDs from Meta's docs.

## 2. Live contract (live, 4 calls)
- `python3 tools/live_checks.py contract`
- Pass: 8 tests ran, 0 skipped, OK. Note the tokens of the 4 calls.
- If it fails: the reply shape differs from the stub (fix `_parse` in `apex/llm_service.py`, test first against a
  stub that copies Meta's real reply); Meta rejects `store` / `instructions` / `max_output_tokens` (drop or rename
  the field); the pin doesn't match (pin the ID the reply reports).

## 3. Probe and corpus tuning (live)
- `python3 tools/live_checks.py probe` → the baseline once on all 30 public tasks (no held-out tasks).
- Pass: baseline public pass rate between ~30% and ~80% overall, with the `indirect` tier lower than `plain`.
- If out of band: retune 3–5 tasks in `tools/make_corpus.py` (vaguer prompt, bug moved into a helper, or the
  reverse), `python3 tools/make_corpus.py && python3 run.py corpus-check` → 40 OK, then probe again.
- Also check: parse-error rate (from the totals); if high, fix `prompts.py` before step 5.
- Read tier gaps with care (phase 4 review): the repo docstrings in `symptom` / `indirect` tasks still state the
  correct rule, so a tier mostly changes the prompt wording; and `ho_obo_last_field` / `ho_obo_nth_from_end` are close
  in shape to `obo_last_words` / `obo_last_n`, which can inflate the held-out score. Retune here if the gap matters.
- Phase 5 review notes (details: `../LOGIC.md` issue log R2, R3, R8, L4):
  - prompts that hint at the cause: indirect `te_count_above_mean`, `te_longest_name`, `ho_te_elapsed` name the
    type; symptom `te_full_name`, `te_over_limit` name the trigger. If these score like plain tasks, make the
    prompts vaguer;
  - held-out overlaps: `ho_te_next_port` ~ `te_latest_version` (text compare), `ho_te_label` ~ `te_greeting`
    (str + int). Compare their held-out pass rates with the twins' public rates;
  - `te_latest_version` has no TypeError, so the fake model treats it as off_by_one for mutation (fake-only).

## 4. Cost (no key needed)
- `python3 tools/live_checks.py estimate`
- Pass: the worst case fits `tokens_total − holdout_reserve`, and the held-out stage fits the reserve. Compare with
  the probe's tokens per task run to get a realistic figure.
- `configs/meta.json` is sized to the pessimistic bound (9.4M ceiling; every reply at max_tokens on every step). From
  the probe's tokens per task run, set a realistic `tokens_total` (e.g. 1.5× the expected spend) before step 5.
- Billing check: the engine charges 0 for a failed HTTP attempt (LOGIC.md R11). After step 5, compare `tokens spent`
  with the provider's usage page; a gap means billed retries.

## 5. First real run (live)
- `python3 tools/live_checks.py run` → `runs/v1-meta-1`, then `verify` (the tool runs both).
- Pass: the run finishes (stop reason `g_max reached` or `budget: …`, not `aborted`), `verify` OK.
- If a generation aborts on HTTP 429: lower `budget.max_concurrent` in `configs/meta.json` and run again with a
  new `--run-id`. A generation that runs past the token cap partway through is also discarded (R13).

## 6. Final-result acceptance (on `runs/v1-meta-1`)
- `report.md` lists every generation with best and mean public L1.
- The best public L1 of the last generation is above generation 0's.
- Held-out rates for the final survivors, with 95% Clopper–Pearson intervals.
- `python3 run.py stats runs/v1-meta-1 --tasks`: note the parse-error rate, the end outcomes, and mutation
  acceptance (accepted / proposals).
- Tokens spent ≤ `tokens_total`; note the wall time.
- Key leak check: `grep -rl "$(sed -n 's/^MODEL_API_KEY=//p' .env)" runs/v1-meta-1` → no output.
- Tamper demo on a copy (README "Verifying and the tamper demo") → `verify` FAIL with "hash mismatch".

## 7. Failure-fix loop
- `python3 tools/live_checks.py stats` → pick the biggest failure mode (parse errors, `max_steps`, rejected patches,
  rejected mutations). Fix it test-first, re-run the suite, then a short live run (`--run-id v1-meta-2`, small
  `g_max`) to confirm.

## 8. Unit tests deferred from the build
- `costs.estimate` (`apex/costs.py`): hand-computed worst case for the default config and for `configs/meta.json`.
- `run.py stats`: output sections, `--tasks`, exit 2 on a missing dir, exit 1 on a damaged ledger.
- `corpus.load_task`: `difficulty` accepts the three tiers, rejects others, defaults to `plain`.
- Probe table: the difficulty column matches each task's `task.json`.
- `tools/make_corpus.py`: running it twice gives an identical tree (hash `corpus/`, `holdout/`, `oracle/`).

## 9. Whole-code review
- `/code-review` (or `/quality-gate`) over `product/`.
- `/security-review` focused on key handling (`apex/llm_service.py`, `apex/envfile.py`, `tools/live_checks.py`).

## 10. Fake regression (no key needed)
- `python3 -m unittest discover -s tests` → OK.
- The same with `.env` vars exported and HTTPS blocked:
  `MODEL_API_KEY=banana APEX_LLM_CONFIG=configs/meta.json https_proxy=http://127.0.0.1:9 HTTPS_PROXY=http://127.0.0.1:9 python3 -m unittest discover -s tests` → OK.
- `python3 run.py corpus-check` → 40 OK; `python3 run.py run --seed 1234` → verify OK; `python3 run.py probe` →
  30 rows; every README command that needs no key runs.
