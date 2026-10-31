# Plan: Revise design.md and write CODE_STRUCTURE.md (docs only)
Progress: 100%

## Context
The review of `design.md` (2026-10-26) found gaps that block an implementation plan. These are a missing evolution loop, no task domain, Phase 1 dependencies in the wrong order, and contradictions in the ledger and evaluation sections. This plan fixes `design.md` and then writes `CODE_STRUCTURE.md`. That file covers the repo layout, tech stack, file roles, deep dives and specs, and becomes the basis for the later implementation plan.
Scope: hackathon (10-day MVP). **Only `.md` files are written.** No code, no scripts.

**Change protocol (applies to every edit of `design.md`):**
1. Each change gets an ID `C-NN`. It is shown to the user with: location (section/line), original text, proposed text, and justification (which review item it fixes).
2. The user answers per change: approve / reject / amend. Only approved (or amended-then-approved) changes are written.
3. Each decision is logged in the `PLAN_LOG.md` → "Change register" (ID, item, decision, final text summary).
4. No edit to `design.md` happens outside this protocol, including typo or formatting fixes.
5. Choices in `CODE_STRUCTURE.md` that are not already in `design.md` (tech stack, layout) are also proposed and need approval before writing.
6. (Added 2026-10-31 at the user's request.) Whenever a situation needs human judgement, or would be much better with it, it is logged in `JUDGEMENT_CALLS.md` (ID `JC-NN`) with the options that would have been asked, the option taken, and its status.

**Review items (reference numbers used below):**
Blockers: R1 no evolution loop / generation / selection defined · R2 no target task domain · R3 Phase 1 has no automated evolution · R4 roadmap dependency inversions (hidden score, causal_attribution_id) · R5 merge-by-hidden-score leaks the holdout.
Major: R6 single `parent_hash` + `block_index` ambiguity · R7 Lamport clock ≠ branch id · R8 canonical serialization unsafe (use RFC 8785) / "Merkle" undefined · R9 "merge"/monoid undefined · R10 determinism vs LLM nondeterminism · R11 entropy & KL sources undefined · R12 99.9%/1000 statistically weak · R13 endpoint signatures / prompt injection defenses unrealistic · R14 cannot log to Genesis · R15 SAM/Muse capability and access, host-level AST · R16 no budget model.
Schema: R17 MutationProposal scope/payload/target_model · R18 EscalationEvent nullable entropy · R19 FitnessRecord missing generation/window/breakdown · R20 AgentSpec model pin · R21 SubagentInstance status/parent · R22 missing Tool Entry & Behavioral Signature schemas.
Minor: R23 N=50 fixed vs open · R24 "custodian" undefined · R25 Signal Watcher vs diversity tension · R26 markdown headings / math rendering.

## Phase 1 — Setup & baseline (weight 5%) [x]
- Files to edit / write / run: write `PLAN_LOG.md`; run `cp design.md design.orig.md`
- Actions:
  1. Make a frozen copy of the original design as `design.orig.md` (never edited).
  2. Create `PLAN_LOG.md` with sections: "Decisions", "Change register", "Failed attempts".
- Verification: `diff design.md design.orig.md` prints nothing; `PLAN_LOG.md` exists with the 3 sections.
- Risks / possible problems: none significant. If `design.orig.md` already exists, ask before overwriting.

## Phase 2 — Blocker decisions (weight 15%) [x]
- Files to edit / write / run: `PLAN_LOG.md` (Decisions)
- Actions:
  1. Ask the user to decide R2: the target task domain for the MVP (offer 2–3 concrete options with scoring functions).
  2. Ask the user to decide R1: the evolution model (population size, definition of a generation, selection algorithm such as UCB1/tournament, how offspring are produced).
  3. Ask the user to decide R3/R4: what moves into Phase 1 (e.g. a minimal automated mutate→eval→select loop, a minimal holdout split, a stub attribution log).
  4. Ask the user to decide R5/R9: the merge policy (public-score selection, deterministic rule, or no merging in MVP).
  5. Log each decision with its rationale.
- Verification: `PLAN_LOG.md` → the Decisions table has a row for R1, R2, R3/R4, R5/R9, each with a non-empty "Approved (date)" field (deferred items are logged as an Open Point and also need it filled).
- Risks / possible problems: the user may want to defer a decision. If so, log it as an explicit Open Point instead and carry it to Phase 3 as an Open-Points edit.

## Phase 3 — Apply blocker changes to design.md (weight 15%) [x]
- Files to edit / write / run: `design.md`, `PLAN_LOG.md`
- Actions:
  1. Draft change set C-xx from the Phase 2 decisions: new "Evolution Loop" section, task domain in Summary/Goals, revised §8 merge rule, revised §17 Roadmap.
  2. Present each change per the protocol and wait for per-change approval.
  3. Write only the approved changes and log each in the Change register.
- Verification: `diff design.orig.md design.md`. Every hunk maps to an approved C-ID in the register, and no hunk is unaccounted for.
- Risks / possible problems: the roadmap may grow beyond 10 days. Watch for this and flag it to the user if Phase 1 gains more than ~2 components.

## Phase 4 — Ledger & serialization changes (weight 10%) [x]
- Files to edit / write / run: `design.md`, `PLAN_LOG.md`
- Actions:
  1. Propose changes for R6, R7, R8, R10, R14: single `parent_hash` per D-04, with `height` + `block_hash` identity (amended 2026-10-31; was `parent_hashes[]`, which conflicted with D-04), hash-based `branch_id`, RFC 8785 JCS plus the hashed-field list, the determinism scope (replay from logged outputs), and the gate-version block instead of a Genesis write.
  2. Apply the protocol (present → approve → write → log).
- Verification: as in Phase 3 (diff ↔ register).
- Risks / possible problems: renaming "Merkle-DAG" affects many sections. Propose it as one change listing every location it touches.

## Phase 5 — Evaluation, escalation, threat model, budget (weight 10%) [x]
- Files to edit / write / run: `design.md`, `PLAN_LOG.md`
- Actions:
  1. Propose changes for R11 (entropy source, e.g. sample disagreement; define KL or remove it), R12 (confidence-bound threshold), R13 (model-ID pinning/canaries; tool-permission injection defense), R15 (model capability/access note; sandbox Meta Muse Code parsing), R16 (budget section).
  2. Apply the protocol.
- Verification: as in Phase 3.
- Risks / possible problems: R15 depends on facts about model availability that the user must confirm. If unknown, propose it as an Open Point, not as a claim.

## Phase 6 — Schema & minor changes (weight 10%) [x]
- Files to edit / write / run: `design.md`, `PLAN_LOG.md`
- Actions:
  1. Propose schema changes R17–R22 (one C-ID per schema).
  2. Propose minor changes R23–R25.
  3. Propose R26 (markdown headings, math notation) as a single formatting change, applied last.
  4. Apply the protocol.
- Verification: as in Phase 3. All schemas remain valid YAML (checked by eye for indentation and required-field consistency).
- Risks / possible problems: the R26 formatting diff could hide content changes. Apply it last, on its own, and verify with `diff -w`.

## Phase 7 — Design consistency pass (weight 5%) [x]
- Files to edit / write / run: `design.md`, `PLAN_LOG.md`
- Actions:
  1. Read the full revised `design.md`. List remaining cross-reference contradictions (terms, phase dependencies, schema ↔ text).
  2. Propose fixes per the protocol, if any.
- Verification: every R1–R26 item is in the register as applied, rejected, or deferred. The final diff fully matches the register.
- Risks / possible problems: new inconsistencies introduced by earlier changes. These are handled here, not silently.

## Phase 8 — CODE_STRUCTURE.md: stack & layout (weight 15%) [x]
- Files to edit / write / run: write `CODE_STRUCTURE.md`, `PLAN_LOG.md`
- Actions:
  1. Propose the tech stack (language, LLM SDKs, sandbox runtime, storage for the ledger, test framework, CLI/console) with a one-line justification each. Get approval.
  2. Propose the ideal end-product repo layout (tree) with a one-line role per file/folder. Mark which parts are MVP (Phase 1) and which come later. Get approval.
  3. Write both sections and log the decisions.
- Verification: every component in design §5 maps to at least one path in the layout, and every path maps back to a design component or support role.
- Risks / possible problems: over-engineering the layout for a hackathon. Keep MVP paths minimal and flag anything not used in Phase 1.

## Phase 9 — CODE_STRUCTURE.md: deep dives & specs (weight 10%) [x]
- Files to edit / write / run: `CODE_STRUCTURE.md`, `PLAN_LOG.md`
- Actions:
  1. Write short deep dives (each ≤ ~15 lines and a small diagram or pseudocode where useful): Ledger (block construction, hashing, branching), Orchestrator & generation loop, Evaluation engine (L0→L4, holdout isolation), Mutation pipeline, Sandbox & tool proxy, Escalation.
  2. Write the specs: config file format, key interfaces between modules, data/storage layout, error-handling and budget enforcement, testing strategy.
  3. Present the draft for approval before finalizing.
- Verification: each deep dive references the design section it implements, and no deep dive contradicts `design.md`.
- Risks / possible problems: deep dives may expose design gaps. If so, use the hard-problem protocol and do not edit `design.md` outside the change protocol.

## Phase 10 — Final cross-check (weight 5%) [x]
- Files to edit / write / run: `design.md`, `CODE_STRUCTURE.md`, `PLAN_LOG.md`, `JUDGEMENT_CALLS.md`; run `diff design.orig.md design.md`
- Actions:
  1. Cross-check terminology and schemas between the two docs.
  1b. (Added 2026-10-31 at the user's request.) Review Phases 3, 4 and 5, which ran without a human in the loop. Go through every C-ID in those phases and log each embedded judgement call (defaults, interpretations, trade-offs) in `JUDGEMENT_CALLS.md` with its options.
  2. Confirm with the user whether `design.orig.md` is kept or deleted (deletion needs permission).
  3. Propose a commit of the docs (**requires user permission**, per rule 4).
- Verification: the final diff matches the register 100%, and the user confirms both docs are ready to serve as input for the implementation plan.
- Risks / possible problems: late requests from the user. Treat them as amendments (rule 6) and route them through the change protocol.

Weights total: 100
