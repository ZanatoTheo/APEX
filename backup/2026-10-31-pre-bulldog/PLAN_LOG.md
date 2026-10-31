# PLAN_LOG — APEX docs revision

## Decisions
<!-- "Approved (date)" must be non-empty for every row (Phase 2 verification). -->

| ID | Items | Decision | Rationale | Approved (date) |
|---|---|---|---|---|
| D-01 | R2 | **Task domain = Python bug-fix.** Task = a small repo snapshot plus failing public tests. Tools: `read_file`, `run_tests`, `write_patch`. L0: no sandbox violation, no network, patch applies, within timeout. ~~L1 = 0.7·public_pass_rate + 0.2·token_cost + 0.1·latency~~ → **L1 superseded by D-06** (sign error). Hidden = held-out tests per task plus a held-out task set. 5 distributions: off-by-one, type errors, API misuse, edge cases, logic inversion. | Grading by tests is deterministic and cheap. Public/hidden tests give a natural holdout split. It reuses the Phase 1 sandbox. | User, 2026-10-26 |
| D-02 | R1 | **Evolution = (μ+λ) elitist + UCB1 parent selection.** P=8 (μ=4 survivors, λ=4 children), defaults. One generation: (1) evaluate all P on a batch of K=10 public tasks; (2) drop L0 failures and rank by L1; (3) keep the top μ; (4) pick parents by UCB1 over lineages; (5) **each child is its parent mutated once**: a single in-place edit in one scope (code / graph / prompt) that may add, modify or remove content, not an append; (6) write everything to the ledger. No crossover. Stop at G_max or the budget cap. | Keeps the doc's existing UCB1 wording. Smallest loop that tests the central bet. **User amendment:** "child = parent + 1 mutation" read as additive, which would let definitions accumulate (stated, then negated later) and grow without limit. A child is the mutated parent. | User, 2026-10-26; amended 2026-10-31 |
| D-03 | R3, R4 | **Roadmap Phase 1 gains:** (a) an automated mutate→eval→select loop, replacing scripted/human-reviewed mutation, ~~with an optional operator-approval toggle~~ (toggle dropped by D-08); (b) a static hidden holdout split read only by the evaluator and never shown to agents or the mutation model; (c) a stub attribution log in which each proposal cites the ledger hash of the failing trace. Rotation, custodian separation and regression-diff evidence stay in Phase 2. | (a) makes the MVP test the central bet (R3). (b) and (c) remove the dependency inversions (R4). | User, 2026-10-26 |
| D-04 | R5, R9 | **No merging in the MVP.** Lineages only fork; survivors are chosen by selection. The ledger is a tree with single parents. Remove the "commutative monoid" and conflict-resolution text; merging goes to Open Points. Hidden score is never used for selection, only for L4 tracking and Agent Spec freezing. | Removes the holdout leak (R5) and the undefined merge semantics (R9). | User, 2026-10-26 |
| D-05 | R1 (refines D-02) | **Loop parameters.** UCB1 arm = lineage (root ancestor id); one visit = one child produced from that lineage; reward = the child's L1 in [0,1], or 0 if it fails L0; c = √2. Each generation samples a fresh batch of K=10 public tasks, the same for all P. λ parent draws are made with replacement. Fewer than μ pass L0 → keep all passers and fill P with extra children. Zero pass → roll back to the previous survivors with a new batch (counts toward G_max). Stop at G_max = 10 or the token budget (`budget.tokens_total` in config). | The review found the loop could stall at zero survivors, overfit a fixed batch, or have no deterministic stop. | User, 2026-10-31 |
| D-06 | R1, R2 (corrects D-01) | **L1 = 0.7·pass_rate + 0.2·(1 − tokens/token_budget) + 0.1·(1 − latency/timeout)**, each term clamped to [0,1]. Tie-break: lower token cost, then the lexicographically lower block hash. | The D-01 formula (proposed by Claude) rewarded higher cost and latency and had no units. Normalizing against fixed budgets keeps scores comparable across generations and windows. | User, 2026-10-31 |
| D-07 | R1, R11 (review b) | **Mutation every generation, guided by traces.** Every child is a mutated parent. The edit is guided by the parent's failing public-test traces, which the stub attribution log cites. Escalation to Meta Muse Spark (MAD entropy, deadlock) is out of the MVP; the MVP keeps hard timeouts only. §10's "only on failure or entropy spike" trigger is replaced. | Resolves the contradiction between §10 and D-02. It also sidesteps R11 (entropy has no defined source) for the MVP. | User, 2026-10-31 |
| D-08 | R3 (scope) | **MVP cuts:** (a) the corpus covers 2 of 5 distributions (e.g. off-by-one, type errors), about 30 public and 10 hidden tasks; the other 3 come in roadmap Phase 3. (b) MVP mutation scopes are `prompt_axiom` and `graph_config` only; `code_ast` moves to roadmap Phase 2. (c) The operator-approval toggle is dropped. **Not cut:** the custom seccomp profile stays in Phase 1. **Added (required):** the bug-fix corpus and the tools `read_file`, `run_tests`, `write_patch` go into roadmap Phase 1. | D-03 added 3 items, above the ~2-component flag (PLAN.md Phase 3 risk). These cuts keep the 10-day sprint realistic. | User, 2026-10-31 |

## Change register
<!-- Decision ref = the D-NN this change implements ("—" if it comes straight from a review item). Lines = design.md line range after the edit, used to match diff hunks. -->

| ID | Item | Decision ref | Section | design.md lines | Decision | Summary |
|---|---|---|---|---|---|---|

## Checkpoints
### Phase 1 — Setup & baseline (2026-10-26) ✔
- **Done:** created `design.orig.md` (guarded by `test ! -e`), created `PLAN_LOG.md`.
- **Baseline sha256:** `52f262fc90979c949399eebdb9999639e62ec8e2f6a892e4f7558cc17d470881` (design.orig.md = design.md at baseline).
- **Verification:** `diff design.md design.orig.md` → exit 0; PLAN_LOG sections at lines 3/6/12.
- **Deviations:** none in substance. The plan file was moved to PLAN.md because of the freeze (user-approved), and the cp was retried once.
- **Problems:** none.
- **Review findings (checkpoint-reviewer):** 1 tick missing (fixed by this checkpoint). Open, awaiting user decision: 2 guard the cp in the plan text; 3 make design.orig.md read-only (sha recorded above); 4 link the register to D-IDs and hunks; 5 make the YAML and register-match verifications runnable; 6 unify the C-NN/D-NN ID format; 7 require the approval field in the Phase 2 check.

### Phase 2 — Blocker decisions (2026-10-31) ✔ closed after follow-up decisions D-05..D-08
- **Closing verification:** D-01..D-08 all approved=OK; R1, R2, R3, R4, R5, R9 covered; design.md sha256 unchanged (52f262fc…).
- **Resolved review findings:** (a) → D-05, (b) → D-07, (c) → D-06 (the leftover text at l.131–132 is fixed in Phase 3), (e) cuts → D-08. Still routed: (d) → Phases 3 and 5, (e) roadmap text and (f) → Phase 3, (g) → amend Phase 4 with user approval, (h) → Phase 4.
- **Done:** D-01..D-04 recorded, D-02 with the user's "child = mutated parent" amendment. Review findings 4 and 7 from Phase 1 applied (register/decision columns, approval-field check); 1, 2, 3, 5 and 6 ignored per the user.
- **Verification:** awk check → D-01..D-04 approved=OK; R1, R2, R3, R4, R5, R9 covered.
- **Deviations:** phase left unticked because the review showed the decisions are underspecified.
- **Problems:** the L1 formula in D-01 (proposed by Claude) has cost and latency with a positive sign and no normalization. This is Claude's error and needs correcting.
- **Review findings (checkpoint-reviewer):** (a) D-02 underspecified: UCB1 arm/reward/visit/c, K batch fixed or resampled, parent draws, <μ L0 survivors, G_max, budget cap. (b) §10 mutation trigger (failure/entropy) contradicts mutating every generation; escalation has no MVP scope. (c) L1 sign/normalization, ties at K=10, "style adherence"/"accuracy" leftovers at design.md:131–132. (d) Holdout integrity: Muse Code at host level (l.114), write_patch can edit tests, "custodian"/"rotation" wording at l.23/40/162/163. (e) Roadmap: l.328 defers the loop; l.330–331 duplicate stubs; D-03 adds 3 items (>~2 flag); the D-01 corpus and tools are missing from Phase 1. (f) UCB1 with no diversity term means the monoculture defense (l.45/164) is false for the MVP; it needs a Phase 2 marker and a residual-risk note. (g) PLAN.md Phase 4 "parent_hashes[]" conflicts with D-04. (h) block_index (l.243) vs D-03(c) citing a hash.
- **Phase 3 touch list (from review):** D-01 → l.6, 29–31, 35, 131–132, 153, 156–157 · D-02 → l.134, 137–140, 148, 231, 234 · D-03 → l.23, 40, 98, 106, 114, 162–163, 243, 324–333 · D-04 → l.123, 126, 98, 23, new Open Point in §18 (l.338–344).
- **Routing:** (a), (b), (c) and the cuts in (e) → follow-up decisions now. (d) → Phases 3 and 5. (e) roadmap text and (f) → Phase 3. (g) → amend Phase 4 text, needs user approval. (h) → Phase 4 (R6).

## Failed attempts
<!-- Format: tried X, failed because Y -->
- 2026-10-26 · Phase 1 · Writing the plan-mode file `~/.claude/plans/serene-tumbling-fiddle.md` was blocked by the freeze hook (it is outside `/home/theo/projects/APEX`). The user chose to use `PLAN.md` as the plan instead.
- 2026-10-26 · Phase 1 · The first `cp design.md design.orig.md` got no verdict from the auto-mode safety check. The retry succeeded.
