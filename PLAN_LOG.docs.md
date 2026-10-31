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
| C-01 | R2 | D-01 | §1 | p3: 6 | PENDING (bulldog) | MVP task family sentence |
| C-02 | R2, R3 | D-01, D-03 | §3 Goals | p3: 35 | PENDING (bulldog) | MVP goal: loop improves agents on hidden holdout |
| C-03 | R2 | D-01 | §3 Non-goals | p3: 39 | PENDING (bulldog) | MVP envelope named |
| C-04 | R1 | D-02 | §2 | p3: 27–29 | PENDING (bulldog) | Generation / Lineage / Child terms (Child revised after review: a copy, parent unchanged) |
| C-05 | R4, R5 | D-03, D-04 | §2 Hidden Score | p3: 23 | PENDING (bulldog) | evaluator-only, never used for selection |
| C-06 | R1 | D-02 | §2 Mutation Proposal | p3: 25 | PENDING (bulldog) | single-unit patch |
| C-07 | R5 | D-03, D-04 | §4 | p3: 44 | PENDING (bulldog) | holdout principle |
| C-08 | (f) | — | §4 | p3: 49 | PENDING (bulldog) | diversity = Phase 2 + residual risk |
| C-09 | — | D-07 | §4 | p3: 51 | PENDING (bulldog) | escalation = Phase 2 |
| C-10 | R5, R9 | D-04 | §8 | p3: 127–128, 130 | PENDING (bulldog) | no merging; monoid/hidden-score rule removed |
| C-11 | R2 | D-01, D-06 | §9 L0/L1 | p3: 135–136 | PENDING (bulldog) | concrete gates; corrected L1 + tie-break |
| C-12 | (f) | D-04 | §9 L3/L4 | p3: 138–139 | PENDING (bulldog) | L3 Phase 2; hidden score limited to 2 uses |
| C-13 | R2, (d) | D-01, D-03, D-08 | new §9.1 | p3: 140–145 | PENDING (bulldog) | task family, holdout isolation |
| C-14 | R1 | D-02, D-05, D-07, D-08 | §10 | p3: 146–168, 169–170 | PENDING (bulldog) | evolution loop, UCB1, mutation, pruning (revised after review: gen 0, parent pick, UCB1 n=0 and reward timing, refill P−s, copy wording, no-failure fallback) |
| C-15 | — | D-04 | §5 table | p3: 102 | PENDING (bulldog) | ledger row: no merging |
| C-16 | — | D-08 | §5 table | p3: 110 | PENDING (bulldog) | console: no manual review |
| C-17 | — | D-07 | §11 | p3: 172 | PENDING (bulldog) | scope line: Phase 2+ |
| C-18 | R23 | D-05 | §12 | p3: 178 | PENDING (bulldog) | default N=50; MVP = single window |
| C-19 | (d), (f) | D-03, D-05 | §15 | p3: 193–195 | PENDING (bulldog) | 3 threat rows aligned to MVP |
| C-20 | (d) | D-01 | §14 | p3: 187 | PENDING (bulldog) | MVP tool set |
| C-21 | R3, R4 | D-03, D-07, D-08 | §17 | p3: 356–372 | PENDING (bulldog) | roadmap rewrite |
| C-22 | R9 | D-04 | §18 | p3: 381 | PENDING (bulldog) | Open Point: ledger merging |
| C-23 | P3 review #1 | D-02, D-07, D-08 | §2, §5, §6 Meta Muse Code rows | p3: 12, 107, 117 | PENDING (bulldog) | one unit per proposal; code_ast Phase 2; one call per child |
| C-24 | P3 review #2 | D-07 | §12 Operator Governance | p3: 179 | PENDING (bulldog) | recalibration = Phase 2 |
| C-25 | R7, P4 review #1, #3 | — | §8 Branching + Ordering | p4: 129–130 | PENDING (bulldog) | branch_id = SHA-256(parent hash ‖ agent_id); root branch; single writer; Lamport rule |
| C-26 | R8, P4 review #7 | — | §8 Canonical | p4: 132 | PENDING (bulldog) | I-JSON validation; RFC 8785 JCS; hashed-field rule |
| C-27 | R6, R8, P4 review #2, #3, #5 | — | §8 new bullets | p4: 133–135 | PENDING (bulldog) | Merkle DAG defined; Genesis records by hash; verification + published heads |
| C-28 | R10, P4 review #4 | — | §7 | p4: 121 | PENDING (bulldog) | determinism scoped; request+response stored; replay ≠ block bytes |
| C-29 | R14, P4 review #5 | — | §12 Gate patch | p4: 184 | PENDING (bulldog) | gate-version block on root branch, by hash |
| C-30 | R6, (h) | D-04 | §16 Ledger Block | p4: 208, 210, 212, 219, 239–240 | PENDING (bulldog) | height; parent_hash/result_hash descriptions |
| C-31 | (h) | D-03 | §16 Attribution | p4: 278, 282–285, 290 | PENDING (bulldog) | block_hash; MVP evidence description |
| C-32 | P4 review #2 | — | §15 Ledger Tampering | p4: 202 | PENDING (bulldog) | defense = §8 verification + published heads |
| C-33 | R11 | D-07 | §11 MAD | p5: 179 | PENDING (bulldog) | entropy via sample disagreement; MAD z > 3.5 |
| C-34 | R11 | — | §10 KL | p5: 173 | PENDING (bulldog) | KL defined on tool-call distributions; Phase 2 |
| C-35 | R11 | — | §15 Causal Overfitting | p5: 206 | PENDING (bulldog) | fresh-batch re-evaluation as defense |
| C-36 | R12, P3 review #7 | — | §13 | p5: 188–189 | PENDING (bulldog) | Clopper–Pearson bound; MVP freezes no specs |
| C-37 | R13 | — | §15 Model Swap | p5: 202 | PENDING (bulldog) | model-ID pinning + canaries |
| C-38 | R13 | — | §15 Prompt Injection | p5: 203 | PENDING (bulldog) | data/instruction separation, scoped tools |
| C-39 | R15 | — | §6 Isolation | p5: 118 | PENDING (bulldog) | Muse Code output untrusted; code only in sandbox |
| C-40 | R15 | — | §18 | p5: 394 | PENDING (bulldog) | Open Point: model availability |
| C-41 | R16, P3 review #6a, P5 review #4 | — | §10 Stopping + Budget | p5: 163–164 | PENDING (bulldog) | per-run and per-engine caps with defaults; holdout reserve; mutation-call bound |
| C-42 | P5 review #7 | — | §17 Phase 2 | p5: 381 | PENDING (bulldog) | KL drift + canaries on roadmap |
| C-43 | P5 review #5 | — | §18 | p5: 390 | PENDING (bulldog) | KL threshold added to calibration Open Point |
| C-44 | R17 | D-02 | §16 Mutation Proposal | pf: 267, 278, 280–290, 292 | PENDING (bulldog) | one-unit scope; patch_payload {format, content}; generator_model |
| C-45 | R18 | — | §16 Escalation | pf: 369–370 | PENDING (bulldog) | mad_entropy_value nullable |
| C-46 | R19 | D-06 | §16 Fitness | pf: 312–340 | PENDING (bulldog) | generation, window, L1 components, nullable hidden/divergence |
| C-47 | R20 | — | §16 Agent Spec | pf: 377–419 | PENDING (bulldog) | model_pins; distributions with lower_bound_95 |
| C-48 | R21 | D-02 | §16 Subagent Instance | pf: 247, 251–253, 262–263 | PENDING (bulldog) | parent_agent_id; status enum |
| C-49 | R22 | D-01 | §16 new Tool Entry | pf: 423–444 | PENDING (bulldog) | tool schema with denied_paths |
| C-50 | R22 | — | §16 new Behavioral Signature | pf: 445–468 | PENDING (bulldog) | Phase 2 schema |
| C-51 | R24 | — | §2 Custodian | pf: 24 | PENDING (bulldog) | term defined |
| C-52 | R25 | — | §11 Signal Watcher | pf: 182 | PENDING (bulldog) | Phase 3; signals logged only |
| C-53 | — | — | Header | pf: 3–4 | PENDING (bulldog) | version 1.2.0 draft, date |
| C-54 | R26 | — | §9, §10, §15, §16, §18 | pf: 143, 174, 202, 453, 492 | PENDING (bulldog) | LaTeX → Unicode |
| C-55 | R26 | — | whole doc | all heading/fence lines | PENDING (bulldog) | markdown headings, list header, code fences; words unchanged |

| C-56 | P6 review #1 | — | §16 Ledger Block | p6: 215–220, 236, 243, 247 | PENDING (bulldog) | block kind; optional agent_id; branch_id description |
| C-57 | P6 review #2 | — | §16 new Graph Config + Agent Spec ref | p6: 418, 455–500 | PENDING (bulldog) | MVP topology schema |
| (fixes) | P6 review #3–#7 | — | C-46 / C-47 / C-49 / C-52 / C-55 | p6: 330–340 / 404–415 / 504, 522 / 14 / 176 | PENDING (bulldog) | batch_id; p_min; denied_paths required; glossary; blank line |

| C-53r | — | — | Header | p7: 3 | PENDING (bulldog) | version line no longer cites a C-ID range |
| C-58 | consistency | — | §2 rows | p7: 11, 13, 18, 21–22, 25, 27 | PENDING (bulldog) | glossary aligned with MVP and phases |
| C-59 | consistency | — | §2 new terms | p7: 31–34 | PENDING (bulldog) | Genesis, Batch, UCB1, Canary Task |
| C-60 | consistency | — | §5 diagram note | p7: 102 | PENDING (bulldog) | target vs MVP components |
| C-61 | consistency | — | §5 rows | p7: 109, 112, 117 | PENDING (bulldog) | Sandbox Pool, Evaluation Engine, Registry |
| C-62 | consistency | — | §6 | p7: 120, 124 | PENDING (bulldog) | single writer; Muse Code role |
| C-63 | consistency | D-08 | §7 | p7: 130 | PENDING (bulldog) | MVP topology = Graph Config + axioms |
| C-64 | consistency | — | §9 L0/L2 | p7: 147, 149 | PENDING (bulldog) | proxy wording; L2 Phase 3 |
| C-65 | consistency | — | §14 | p7: 201 | PENDING (bulldog) | denied paths mentioned |
| C-66 | consistency | — | §15 Sandbox Escape | p7: 214 | PENDING (bulldog) | proxy wording |
| C-67 | consistency | — | §17 Phase 1 | p7: 564 | PENDING (bulldog) | run report bullet |
| C-68 | P7 review #1–#3 | — | §2 Hidden Score / Escalation Event; §5 Attribution row | p7r: 25, 27, 120 | PENDING (bulldog) | definitions match schemas and phases |
| C-69 | P7 review #4 | — | §1 | p7r: 7–8 | PENDING (bulldog) | scope note (JC-09) |
| C-70 | P7 review #5 | D-03 | §16 Attribution | p7r: 338 | PENDING (bulldog) | evidence = result_hash inside the cited block |
| C-71 | P7 review #6 | — | §4, §12 | p7r: 61, 203 | PENDING (bulldog) | gate patching Phase 2 |
| C-72 | P7 review #7 | D-05 | §10 | p7r: 179 | PENDING (bulldog) | gen-0 zero-pass → stop (JC-10) |
| C-73 | P7 review #7 | — | §2 new terms | p7r: 37–43 | PENDING (bulldog) | Seed … Prompt Axiom |
| C-74 | P9 deep dive (JC-02) | — | §6 Swarm Subagent, Isolation Level | p9: 135 | PENDING (bulldog), conditional on JC-02 | MVP: orchestrator interprets graph; tools/tests in network-less container (rationale revised after P9 review #2) |
| C-75 | P9 deep dive (JC-02) | — | §14 Sandbox Specification | p9: 213 | PENDING (bulldog), conditional on JC-02 | MVP containers --network=none; proxy from Phase 2 (rationale revised after P9 review #2) |
| C-76 | P9 deep dive (JC-02) | — | §17 Phase 2 | p9: 583 | PENDING (bulldog), conditional on JC-02 | egress proxy listed as Phase 2 (rationale revised after P9 review #2) |
| C-77 | P9 deep dive (reward hacking) | — | §14 MVP Tool Set | p9: 212 | PENDING (bulldog) | write_patch limited to editable paths; rejects test-runner config |
| C-78 | P9 deep dive (mutation) | D-05 | §10 Mutation, new bullet | p9: 186 | PENDING (bulldog) | validation retries ×3, one redraw, then empty slot (JC-19) |
| C-79 | P9 consistency with C-78 | — | §10 Budget | p9: 181 | PENDING (bulldog), reject with C-78 | count = proposals; retries up to 3 calls each |
| C-80 | P9 review #1 | D-04 | §8 No Merging | p9: 148 | PENDING (bulldog) | hidden results in ledger by hash only; content in separate store |
| C-81 | P10 review #1.5 (JC-02) | — | §9 L0 gates | p10: 156 | PENDING (bulldog), conditional on JC-02 | network gate: MVP --network=none |
| C-82 | P10 review #1.1 (JC-02) | — | §15 Prompt Injection | p10: 222 | PENDING (bulldog), conditional on JC-02 | no network in MVP; proxy from Phase 2 |
| C-83 | P10 review #1.2 | D-02 | §10 Mutation | p10: 184 | PENDING (bulldog) | one proposal ≤ max_patch_ops (5) ops (JC-17) |
| C-84 | P10 review #1.6 | — | §6 Meta Muse Code row | p10: 134 | PENDING (bulldog), reject with C-78 | one proposal per child; up to 3 calls |

"pf:" = line numbers in `backup/design.before-format.md` (before C-55 shifted every line). C-55 is verified separately: stripping its markup reproduces that file exactly.

"p9:" = line numbers in `design.md` after Phase 9 (= `backup/design.after-phase9.md`), diffed against `backup/design.after-phase7.md` (Phase 8 left design.md unchanged).

"p10:" = line numbers in `design.md` after Phase 10 (= `backup/design.after-phase10.md`), diffed against `backup/design.after-phase9.md`.

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

### /bulldog run (started 2026-10-31): deviations that apply to all remaining phases
- The user is away until the next morning, so the per-change approval step cannot happen live. Every change is applied with status **PENDING** and documented (original text, new text, reason) in `CHANGES.md` (a new file, not in the plan) for morning approval. Rejected changes are reverted from the snapshots.
- Backups: `backup/2026-10-31-pre-bulldog/` (design.md, PLAN.md, PLAN_LOG.md as of the start of the run), `design.orig.md`, and per-phase snapshots `backup/design.after-phaseN.md`.
- independent=true was not set: `~/.claude/state/independent` is outside the freeze. The run uses independent=false, so a hard problem → stop and log.
- No git commands (the user said do not commit).
- Phase verification is adapted: "every hunk maps to an approved C-ID" becomes "every hunk of the diff from the previous snapshot maps to a C-ID (PENDING)". The phase snapshots chain together, so the final check covers orig → final.

### Phase 3 — Blocker changes (2026-10-31) ✔
- **Done:** C-01..C-22 applied for D-01..D-08; review fixes C-23, C-24, plus revisions to C-04 and C-14.
- **Verification:** `diff backup/design.after-phase2.md design.md` → 29 hunks, all mapped in the register (the reviewer independently confirmed the mapping and ranges).
- **Deviations:** C-IDs added beyond the drafted set (C-23, C-24) from review findings.
- **Problems:** none blocking.
- **Review findings (checkpoint-reviewer):** #1 Meta Muse Code rows → fixed by C-23. #2 §12 Spark governance → fixed by C-24. #3 in-place vs elitism → C-04/C-14 now say child = copy with one in-place edit, parent unchanged. #4 refill vs λ → P − s parents. #5 UCB1 n=0, gen 0, parent choice, reward timing → added to C-14. #6a token_budget/timeout undefined → Phase 5 (budget, R16). #6b no failing trace → fallback to the most expensive trace (C-14). #7 §13 "5 named distributions" → Phase 5 (R12 rewrite).

### Phase 4 — Ledger & serialization (2026-10-31) ✔
- **Done:** C-25..C-31 for R6, R7, R8, R10, R14 and (h); review fixes folded into C-25..C-29, plus new C-32.
- **Verification:** `diff backup/design.after-phase3.md design.md` → 13 hunks, all mapped. All 8 §16 schema blocks parse with PyYAML, and required ⊆ properties holds for every one.
- **Deviations:** PLAN.md Phase 4 action amended (parent_hashes[] → single parent_hash, per D-04; an obvious contradiction).
- **Problems:** my first branch_id rule was circular (caught by review, fixed).
- **Review findings (checkpoint-reviewer):** #1 circular branch_id → fixed (C-25). #2 hash recompute can't catch a rewrite → published branch heads (C-27, C-32). #3 Lamport rule, single writer, height/clock checks → fixed (C-25, C-27). #4 replay vs block bytes, requests not stored, store unnamed → fixed (C-28). #5 Genesis fields, gate by hash, gate-block placement → fixed (C-27, C-29). #6 "Merkle DAG" misnomer → **left for the user**: not obvious, wording only, noted in CHANGES.md C-27. #7 I-JSON precondition → fixed (C-26).

### Phase 5 — Evaluation, escalation, threat model, budget (2026-10-31) ✔
- **Done:** C-33..C-41 (R11, R12, R13, R15, R16, P3 review #6a/#7); review fixes folded in, plus C-42 and C-43.
- **Verification:** `diff backup/design.after-phase4.md design.md` → 10 hunks, all mapped. Clopper–Pearson figures recomputed numerically (1/1000 → 0.47%; 0/≈3000 → 0.10%).
- **Deviations:** none beyond the bulldog-wide ones.
- **Problems:** C-38 contradicted §14 (fixed; architecture question → JC-02).
- **Review findings (checkpoint-reviewer):** #1 network vs proxy → wording fixed, JC-02. #2 i.i.d. tasks, holdout size, "each lineage" → fixed (C-36). #3 entropy resolution, MAD=0, re-sampling side effects, undefined terms → fixed (C-33), defaults JC-03. #4 mutation-call bound, holdout starvation → fixed (C-41), defaults JC-05. #5 KL infinite, different batches, no threshold → fixed (C-34, C-43). #6 overclaims → softened (C-35, C-37, C-38). #7 roadmap gaps, text-patch "schema" → C-42, C-39; canary scope JC-04.

### Phase 6 — Schemas & minor (2026-10-31) ✔
- **Done:** C-44..C-55 (R17–R22, R24–R26; R23 already resolved by C-18); review fixes, plus C-56 and C-57. JC-06, JC-07, JC-08 logged.
- **Verification:**
  - Content hunks (after-phase5 → before-format) all mapped.
  - C-55 verified as format-only: stripping the markup reproduces `backup/design.before-format.md` exactly. The later blank-line fix is a known +1-line exception.
  - All 11 fenced YAML schemas parse, with nested required ⊆ properties.
- **Problems:** YAML 1.1 parses an unquoted `on` as boolean true, so the Graph Config `required: [on, to]` mismatched. Caught by the parse check and fixed (quoted).
- **Review findings (checkpoint-reviewer):** #1 root-branch blocks → C-56. #2 graph schema missing → C-57, JC-08. #3 denied_paths optional → required (C-49). #4 Signal Watcher glossary → C-52. #5 missing batch_id, seeds, run config, gate block → batch_id (C-46); seeds = Graph Config (C-57); gate block = kind gate_version (C-56); run config and model pins → CODE_STRUCTURE.md (Phase 9). #6 p_min → C-47. #7 lazy-continuation paragraph → blank line (C-55). Low items (undefined §2 terms Genesis/batch/canary/UCB1/Evaluation Engine; Jaccard vs array state_path; I-JSON bound not in schema) → Phase 7.

### Phase 7 — Consistency pass (2026-10-31) ✔
- **Done:** full read of design.md. C-53 revised; C-58..C-67 applied, then review fixes C-68..C-73. JC-09 and JC-10 logged.
- **Verification:**
  - `diff backup/design.after-phase6.md design.md`: every hunk mapped (20 + 9 hunks).
  - R1–R26 all present in the register.
  - The reviewer confirmed all numbers agree across sections (P, μ, λ, K, G_max, 800/40/77/40, 2 M reserve = 40 × 50k, L1 weights, H(X) partitions, Clopper–Pearson figure).
- **Deviations:** none.
- **Review findings (checkpoint-reviewer):** #1 Hidden Score scope, #2 Attribution row phase tag, #3 Escalation triggers → C-68. #4 vision overclaims → C-69 + JC-09. #5 evidence identifier → C-70. #6 gate patch tags → C-71. #7 gen-0 zero pass → C-72 + JC-10; undefined terms → C-73.

### Phase 8 — CODE_STRUCTURE.md stack & layout (2026-10-31) ✔
- **Done:** CODE_STRUCTURE.md §1 scope, §2 tech stack, §3 repo layout ([MVP]/[P2]/[P3] markers), §4 component map. Marked PENDING. Assumes JC-02 option 1. JC-11..JC-16 logged.
- **Verification:** all 12 design §5 components appear in the map (script check plus a manual check on Task Ingress, which the script's slice skipped); all 25 mapped paths exist in the tree; design.md unchanged (cmp with the after-phase7 snapshot).
- **Deviations:** the stack was not approved live (bulldog); logged as JCs instead.
- **Review findings (checkpoint-reviewer):** #1 second holdout reader → corpus.py never opens the holdout; holdout.py hashes its manifest. #2 holdout in repo → moved to `$APEX_HOLDOUT_DIR` (JC-16). #3 mounts and blob leakage → explicit mount rule in pool.py; separate blobs-holdout/; mutation reads blobs/ only. #4 heads next to the ledger → published outside runs/ (JC-15). #5 I-JSON not enforced by rfc8785 → canonical.py guards stated. #6 resource caps, gate definition, RNG/seeding homes → added (stack row, gates.py, rng.py, seeding.py). #7 design §6/§14 vs host-side interpreter → Phase 9 C-IDs (pending, conditional on JC-02).

### Phase 9 — CODE_STRUCTURE.md deep dives & specs (2026-10-31) ✔ (bulldog, no stop)
- **Done:** CODE_STRUCTURE §5 (7 deep dives, each citing its design section) and §6 (config, task.yaml, interfaces, storage, errors/budget, tests). Design C-74..C-80 applied as PENDING. JC-17..JC-19 logged.
- **Deviations from plan:** step 3 ("present the draft for approval") was replaced by PENDING status, as in all bulldog phases. The deep dives exposed design gaps (JC-02 network contradiction, write_patch reward hack, mutation failure rule, hidden-in-ledger wording). These were fixed through the change protocol as C-74..C-80, not through the hard-problem protocol: each fix was clear, and all are reversible per C-ID.
- **Problems/bugs found:** C-77 (a root-level or nested conftest.py could fake passing tests). C-79 (the design's mutation-call bound ignored retries). Budget headroom by worst case would leave about 20% unused (JC-18).
- **Review findings (checkpoint-reviewer), all fixed:**
  - #1 hidden.py wrote to the ledger itself, which broke the single writer, and design §8 said hidden scores have no part in the ledger → orchestrator forwards hashes; C-80.
  - #2 C-74/C-75 rationale wrong (the MVP already runs agent patches) → texts revised, JC-02 reworded.
  - #3 nested conftest.py / rename and symlink hunks → globs at any depth, header rejection, tests.
  - #4 append on a new branch had an undefined tip and last_clock, and no agent_run appends → fork seeds the tip, the loop appends agent_run.
  - #5 dict-key iteration, lineage vs parent, None child, children_of(-1), tie-break replay note → fixed.
  - #6 agents index missing state_machine_version, `evidence` vs `empirical_evidence_link`, `lambda` key → fixed.
  - #7 parse/apply outside the retry loop, max_steps outcome, timeout 120 vs 300, "entry points" → fixed.
- **Verification:** diff after-phase7 → design hunks 135, 148, 181, 186, 212–213, 583 = C-74, C-80, C-79, C-78, C-77, C-75, C-76 (all mapped). design.md: 11 YAML blocks parse, 0 required⊄properties. CODE_STRUCTURE: 2 YAML blocks parse. §5.1–5.7 each cite a design section. Snapshot: backup/design.after-phase9.md.
- **Tooling note:** the freeze hook rejected one combined sed+heredoc command as "unparseable", although its targets were inside APEX. It was redone with Edit; nothing outside the freeze was touched.

### Phase 10 — Final cross-check (2026-10-31) ✔ (bulldog; awaiting the user's morning review)
- **Done:**
  - Terminology and schema cross-check between design.md and CODE_STRUCTURE.md: status lifecycle, Fitness Record ids, run-log states marked code-only, denied-path list marked stricter than design.
  - Retrospective of Phases 3–5 (action 1b): JC-20..JC-29, plus JC-30..JC-32 from the review.
  - Reading order added to CHANGES.md.
  - Design C-81..C-84 applied as PENDING.
- **Deviations from plan:**
  - Action 2 (ask whether to keep design.orig.md) could not be asked while the user is away. It is **kept**, as the user asked for backups.
  - Action 3 (propose a commit): **no commit**, per the user's "Do not commit". A commit can be proposed after the morning review.
  - The verification criterion "the user confirms both docs are ready" is pending the morning review.
- **Problems/bugs found:** network-proxy leftovers in §9 L0 and §15 (C-81, C-82) that contradicted C-74..C-76. The "one edit" op cap was missing from the design (C-83). A stale "one call per child" (C-84). JC-17 cited D-05 instead of D-02. JC-18 claimed the design requires atomic generations.
- **Review findings (checkpoint-reviewer), all handled:**
  - Q1.1/Q1.5 → C-82/C-81.
  - Q1.2 → C-83.
  - Q1.3 → run-log states marked code-only (CODE_STRUCTURE §6.5).
  - Q1.4 → code list marked stricter than design §14.
  - Q1.6 → C-84.
  - Q2 JC-17 citation and JC-18 context fixed; JC-29 now consistent through C-82.
  - Q3 → JC-30 (UCB1 credit timing), JC-31 (trace choice), JC-32 (causal overfitting).
  - Q4 reading order confirmed correct.
- **Verification:**
  - design.orig.md sha256 unchanged (52f262fc…).
  - Snapshot chain orig → after-phase2 (0 hunks) → 3 (29) → 4 (13) → 5 (10) → 6 (72) → 7 (25) → 9 (6) → 10 (4) → design.md (0).
  - Each phase's hunks were mapped to C-IDs at its checkpoint; the Phase 10 hunks 134, 156, 184, 222 map to C-84, C-81, C-83, C-82.
  - Register and CHANGES.md list the same 84 IDs (plus the C-53 revision).
  - JC-01..JC-32 are unique, all OPEN.
  - 11 + 2 YAML blocks parse.

### Amendment (2026-10-31, user, during Phase 5)
- New rule: judgement calls are logged in `JUDGEMENT_CALLS.md` (JC-NN) with their options (PLAN.md protocol item 6).
- Phase 10 gains action 1b: a retrospective review of Phases 3–5 for embedded judgement calls.
- JC-01 logged (Merkle-DAG naming, from Phase 4 review #6).

## Failed attempts
<!-- Format: tried X, failed because Y -->
- 2026-10-26 · Phase 1 · Writing the plan-mode file `~/.claude/plans/serene-tumbling-fiddle.md` was blocked by the freeze hook (it is outside `/home/theo/projects/APEX`). The user chose to use `PLAN.md` as the plan instead.
- 2026-10-26 · Phase 1 · The first `cp design.md design.orig.md` got no verdict from the auto-mode safety check. The retry succeeded.
