# Project Apex: the idea

Project Apex is a competitive evolutionary synthesis engine. It produces task-specialized autonomous agents, called
**Agent Specs**, through automated natural selection. Populations of Swarm Subagents run in parallel over a
cryptographically verified **Decision Ledger**, constrained by hard safety gates, evidence-backed causal attribution
and hidden evaluation holdouts.

Sources: `design.md` (v1.2.0) for what and why, `CODE_STRUCTURE.md` for how, and `prototype/` for the working slice.
Section numbers (§) refer to design.md.

## The problem

Static prompt routing and procedurally generated skills are fragile in multi-agent systems. Hand-built agent
structures don't adapt to non-stationary tasks. Automated optimizers, for their part, tend to game whatever metric
they are scored on, and they leave no audit trail of why an agent changed.

## The central bet (§1)

Complex, non-stationary task execution is best mastered by evolving subagent populations, not by hardcoding agent
structures. The evolution must run inside structural defenses: L0 Hard Gates, a Causal Attribution Log, Behavioral
Signature distance constraints and a hidden holdout. A verifiable ledger must record every decision.

## Premises (§4 design principles)

1. **Mechanism without defense is incomplete.** Every optimization loop carries safeguards against metric gaming.
2. **Hidden evaluation wherever public evaluation is optimized.** Only the Evaluation Engine (the Custodian) can read
   the Hidden Score, and the Hidden Score is never a selection signal.
3. **Mutation is causally directed.** Each Mutation Proposal is guided by empirical evidence (a failing trace), not by
   random search or model confidence.
4. **Stable rubrics.** Evaluation criteria are frozen for a Rubric Window, so populations adapt to a fixed target.
5. **Hard gates are binary.** L0 is never traded off against L1 soft criteria.
6. **Diversity is maintained on purpose.** The goal is to prevent UCB1 monoculture collapse: UCB1 exploration in the
   MVP, Behavioral Signature distance constraints from Phase 2.
7. **State is deterministically serializable.** Every block is canonical JSON (RFC 8785), hashed and verifiable.
8. **Agent Specs carry quantified bounds.** A deployed spec states its success-rate lower bound within a named
   operational envelope.

## How it works

**Subagent and Mutation Units.** A Swarm Subagent executes a state machine. Its editable parts are its Mutation Units:
- **Graph Config:** the JSON state machine (nodes, transitions, step cap).
- **Prompt Axioms:** an ordered list of instruction strings that llm nodes reference.
- **Code Unit:** Python AST, from Phase 2.

**Evolution loop (§10).** An elitist (μ+λ) scheme. The defaults are P = 8 subagents (μ = 4 Survivors, λ = 4
Children), K = 10 tasks per Batch, and G_max = 10 Generations.
1. Generation 0 is made of Seeds, each the root of its own Lineage.
2. In each Generation, every member runs a Task Run on the same freshly sampled Batch of public tasks.
3. L0 failures are disqualified, and the rest are ranked by the Public Score (L1).
4. The top μ survive, and parents compete with their children.
5. λ parents are picked by **UCB1 over Lineages**, with rewards credited when each Child is evaluated.

**Mutation.** Each Child is a copy of its parent with **one in-place edit to exactly one Mutation Unit**.
- **Proposer:** Meta Muse Code writes the edit after reading the parent's failing public-test trace (or, if the
  parent passed everything, its most expensive trace).
- **Validation:** the edit is checked against its unit's schema and retried up to 3 times.
- **Evidence:** the proposal cites the ledger hash of that trace in the Causal Attribution Log.
- **Pruning:** members that don't survive are pruned, but their history stays in the ledger.

**Evaluation (§9).**
- **L0 Hard Gates:** no sandbox violation, no network access, the patch applies and leaves tests untouched, and the
  run stays within its timeout and token budget.
- **L1 Soft Criteria:** 0.7·pass_rate + 0.2·(1 − tokens/token_budget) + 0.1·(1 − latency/timeout).
- **L4 meta-signal:** tracks the divergence between the Public Score and the Hidden Score.
- **Later layers:** L2 robustness (Phase 3) and L3 diversity (Phase 2).

**Decision Ledger (§8).** An append-only Merkle-DAG that branches but never merges.
- **Contents:** Genesis records the run config, the L0 gate definition and the corpus manifest by hash. Each
  subagent's history is its own branch with Lamport clocks. Every model request and response and every tool call is
  stored as content-addressed data, so replays reuse the stored outputs.
- **Verification:** recomputes every hash. It also compares each branch head with the heads published outside the
  ledger every Generation, which catches a full rewrite.

**Agent Spec freezing (§13).** A Lineage is frozen when the one-sided 95% Clopper–Pearson lower bound of its
held-out success rate reaches p_min on every named task distribution.

## MVP scope (§9.1, §17 Phase 1)

- **Task family:** repairing small Python repositories with failing unit tests. There are 2 distributions
  (off-by-one, type errors), with about 30 public and 10 Held-out Tasks.
- **Tools:** read_file, run_tests (public tests only) and write_patch (tests and test-runner config are protected).
- **Hidden holdout:** hidden tests for every public task, plus the Held-out Tasks, which only the final Survivors run.
  The holdout is never mounted in a subagent's sandbox and never shown to Meta Muse Code.
- **Goal:** show that the automated mutate → evaluate → select loop improves agents, measured on the hidden holdout.
  The MVP set is too small to freeze Agent Specs, so it reports each Survivor's held-out success rate with a 95% interval.
- **Later phases:**
  - **Phase 2:** Meta Muse Spark with escalation on MAD-entropy spikes, Rubric Window governance, and the Code Unit.
  - **Phase 3:** SAM 3.1 visual parsing and the Signal Watcher.

## Status

The built system is Apex (`design.md`). It keeps the idea of evolving agents by selection but differs from the MVP
above: the core knows nothing about the task, and the task behind its connector is trading 13 renamed assets through
2025 instead of Python bug-fixing. Agents are defined by axioms and the files they write, not by a Graph Config.

Live runs are recorded in `RUN1_RESULTS.md` and `DEMO_LOG.md`. They show the loop working, not that a strategy makes
money, and none of them ran the held-out check.
