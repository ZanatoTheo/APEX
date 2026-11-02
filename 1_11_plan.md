# APEX v1.0: real Meta model + bigger corpus, built 2026-11-01
Progress: 100/100 · Updated: 2026-11-02

## Context
- Builds on the finished prototype (`prototype/`, 91 tests pass on this machine, Python 3.12.3). The prototype's
  plan and log now live in `prototype/PLAN.md` and `prototype/PLAN_LOG.md`.
- **v1.0 is built in `product/`**, a copy of `prototype/` (user, 2026-11-01). `prototype/` stays frozen as the
  fake-model slice; all v1.0 changes go to `product/` only.
- Read first: `CODE_STRUCTURE.md` (§2 model access by role, §5.6 sandbox, §6.5 errors/budget) and
  `prototype/README.md` "Adding llm_service.py" (the fixed contract).
- User decisions (2026-11-01):
  - v1.0 = **real model** (`apex/llm_service.py`) + **bigger corpus**.
  - Provider: **OpenAI-style API serving a Meta model**: the Responses API (`responses.create`) at
    `https://api.meta.ai/v1`, model `muse-spark-1.3`, key in `MODEL_API_KEY`. `llm_service.py` is written first,
    as its own phase.
  - Visual demo: tomorrow, maybe as the ideas_unhinged #1 experiment (replays). Not in this plan.
  - ideas_unhinged #3 (knockout) and #4 (crossover/species): later days, not in this plan (answer was cut off; see PLAN_LOG).
- Defaults picked here (say so if you want otherwise):
  - HTTP via stdlib `urllib` posting to `/responses`, no `openai` package (user, 2026-11-01).
  - Subagent role `muse-spark-1.3`; mutation role a **Muse Code** model (user, 2026-11-01; ID still needed).
  - Errors that retrying can't fix (400/401/403/404/422) skip `ModelClient`'s retries (user, 2026-11-01).
  - Key from `MODEL_API_KEY` only (`product/.env`). Every live check is in `1_11_test_plan.md`.
  - Corpus target from design §9.1: ~30 public + 10 held-out tasks (15 + 5 per distribution).
  - Task code still runs in a subprocess, not Docker (JC-33). The code under test is our own corpus plus
    model-written patches limited to `editable_paths`.

## Phase 1: product/ + llm_service.py for Meta's Responses API, tested offline (weight 15) [x]
- Detail: `~/.claude/plans/breezy-singing-cookie.md` (approved 2026-11-01).
- Files: `product/` (copy of `prototype/`, no runs/.tmp/plan files), `product/apex/llm_service.py` (new),
  `product/tests/test_llm_service.py` (new), `product/tests/test_llm_contract.py` (retry test),
  `product/apex/config.py` (`models.base_url`, `models.request_timeout_s`), `product/apex/models.py`
  (retryable check), `product/configs/meta.json` (new), `product/README.md` (title only).
- Actions:
  - Copy `prototype/` → `product/`; its 91 tests pass there.
  - Tests first, against a local stub `/responses` server on 127.0.0.1. They fail before the code exists.
  - `LLMService`: key from `MODEL_API_KEY`; POST `{base_url}/responses` with `model` (pinned per role),
    `instructions` (system prompt), `input` (other messages), `max_output_tokens`, `store: false`.
    Text = `output_text` parts of `message` items (reasoning skipped; `incomplete` → partial or ""), `model_id` =
    reply `model`, usage `input_tokens`/`output_tokens`. `LLMServiceError.retryable` False for 400/401/403/404/422.
  - `ModelClient.complete` stops retrying on `retryable = False`.
- Verify: `cd product && python3 -m unittest tests.test_llm_service tests.test_llm_contract -v` → all pass,
  the 4 `LLMServiceContractTest` tests skip (no `APEX_LLM_CONFIG`). Full suite `OK`.
  `python3 run.py run --config configs/meta.json` → stops on the Muse Code placeholder, no run dir.
  `prototype/` has no changes besides the moved plan files.
- Risks: the stub can drift from Meta's real reply shape (phase 2 catches it); the API key must never reach a
  blob or the ledger (a test checks the recorded blob).

**From phase 2 on (user, 2026-11-01): build now, test after the plan.** Each build phase ends with a full
`/checkpoint` (reviewer included) on smoke-level checks: the existing suite stays green, `corpus-check`, each new
command runs once. All live checks (models, contract, probe, the real run), corpus tuning, the failure-fix loop, the
missing unit tests and the whole-code review are in **`1_11_test_plan.md`**, run after this plan. Re-weighted
2026-11-01 (the live-only phase and the live halves of the old phases 7–8 moved to the test plan).

## Phase 2: .env loading, model listing, live-check tool (weight 8) [x]
- Files: `product/apex/envfile.py` (new), `product/run.py` (`models`; loads `.env` only when run as a command),
  `product/apex/llm_service.py` (`list_models`, shared `_request`), `product/tools/live_checks.py` (new),
  `product/.env.example`, tests (`test_envfile.py` new, `test_llm_service.py`, `test_smoke.py`, `test_live_checks.py`).
- Verify (done): suite OK, also with `.env` vars exported and HTTPS blocked; `tools/live_checks.py models` refuses
  the `banana` key. Live part: `1_11_test_plan.md` steps 1–2.

## Phase 3: probe command and run statistics (weight 12) [x]
- Files: `product/apex/stats.py` (new), `product/run.py` (`probe`; `run` and `probe` share `_execute`),
  `product/apex/evolution.py` (`heldout` flag: probes never run held-out tasks), `product/tests/test_stats.py` (new),
  `product/tests/test_smoke.py`.
- Verify (done): fake probe → one row per public task, `verify: OK`; suite OK. Live part: test plan step 3.

## Phase 4: corpus growth, off_by_one (weight 18) [x]
- Files: `product/tools/make_corpus.py`, regenerated `product/corpus/public/**`, `product/holdout/**`,
  `product/oracle/**`; `product/apex/corpus.py` (optional `difficulty`: plain | symptom | indirect);
  `product/run.py` + `product/apex/stats.py` (difficulty column in the probe table).
- Actions: off_by_one to 15 public + 5 held-out. New public ≈ 3 plain / 4 symptom / 4 indirect, held-out 1/1/1
  (fixed without probe data; the test plan retunes). Each task ≥ 3 public and ≥ 2 hidden tests.
- Verify: `python3 tools/make_corpus.py` → 19 public + 7 held-out; `python3 run.py corpus-check` → all OK; suite OK.
- Risks: a fix that passes public but fails hidden (corpus-check catches it).

## Phase 5: corpus growth, type_error (weight 18) [x]
- Files: same as phase 4.
- Actions: type_error to 15 public + 5 held-out, same tier mix.
- Verify: make_corpus → 30 public + 10 held-out; corpus-check → 40 OK; suite OK; `python3 run.py run --seed 1234`
  (fake) → `verify: OK`; `python3 run.py probe` (fake) → 30 rows.
- Risks: the fake demo (JC-34) changes shape with more tasks; fine as long as it runs and verifies.

## Phase 6: cost estimate and configs/meta.json sizing (weight 8) [x]
- Files: `product/apex/stats.py` (`estimate`, `format_estimate`), `product/run.py` (`estimate [--config]`, no key,
  no API call), `product/configs/meta.json` (`tokens_total` / `holdout_reserve` from the estimate; P=4, μ=2, K=3,
  g_max=8, `max_concurrent: 2`).
- Verify: `python3 run.py estimate` and `python3 run.py estimate --config configs/meta.json` print; suite OK.
- Risks: the estimate is a worst case (every call hits its cap), so real runs cost less; say so in the output.

## Phase 7: `run.py stats` (weight 8) [x]
- Files: `product/run.py` (`stats RUN_DIR [--tasks]`), `product/apex/stats.py`.
- Verify: `python3 run.py stats runs/demo-1234 --tasks` prints; a missing dir → exit 2; suite OK.
- Risks: none significant.

## Phase 8: docs and judgement calls (weight 13) [x]
- Files: `product/README.md` (v1.0: setup, commands, live-check order → `../1_11_test_plan.md`, corpus tiers,
  deviations), `idea.md` (status → v1.0 in `product/`), `JUDGEMENT_CALLS.md` (JC-39..JC-45).
- Verify: suite OK; corpus-check OK; `grep -c "^### JC-" JUDGEMENT_CALLS.md` → 45; README commands that need no key
  run once.
- Risks: none significant.

Weights: 15 + 8 + 12 + 18 + 18 + 8 + 8 + 13 = 100
