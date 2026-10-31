# Project Apex: Code Structure

> **Status: PENDING approval.** Written during the unattended /bulldog run (2026-10-31). Stack and layout choices that aren't fixed by `design.md` are judgement calls JC-11..JC-14 (stack, layout) and JC-17..JC-19 (deep-dive defaults) in `JUDGEMENT_CALLS.md`. The layout assumes **JC-02 option 1**:
> - The subagent's state machine is interpreted by trusted orchestrator code on the host, and model calls are made from the host.
> - Task containers only run tools and tests, with `--network=none`.
> - The egress proxy (design §14) is deferred to Phase 2.
>
> If you choose JC-02 option 2, `sandbox/proxy.py` moves to the MVP and `agent/runtime.py` runs inside the container.

This document is the base for the implementation plan. It describes the **ideal end product's** repository and marks what the 10-day MVP builds (`[MVP]`) versus later roadmap phases (`[P2]`, `[P3]`, design §17). Section references (§N) point to `design.md`.

## 1. Scope

- **MVP goal (design §3):** an automated (μ+λ) loop that evolves bug-fixing agents (Graph Config + Prompt Axioms) on a Python task corpus and reports hidden-holdout results, with every step in a verifiable hash-linked ledger.
- **One process, one machine.** The orchestrator owns the ledger (single writer, §8) and a pool of sandbox containers. No distributed components in the MVP.
- **Deterministic where it can be:**
  - All randomness (batch sampling, scope choice, seed mutations) comes from one seeded RNG recorded in Genesis.
  - All model I/O is stored, so runs can be replayed (§7).

## 2. Tech stack

| Concern | Choice | Why |
|---|---|---|
| Language | Python 3.12 | The design is Python-centric (AST mutation, pytest corpus); one language end to end. |
| Packaging / env | uv + `pyproject.toml` | Fast, lockfile-based, one tool for env and scripts. |
| Schemas and config | pydantic v2 | §16 schemas as typed models with validation; JSON Schema export for docs and checks. |
| Config format | YAML (PyYAML) | Readable run configs; the parsed config is hashed into Genesis. |
| Canonical JSON | `rfc8785` package | RFC 8785 JCS (§8). Implementing it by hand is error-prone. |
| Hashing | `hashlib.sha256` (stdlib) | §8. |
| Ledger store | SQLite (stdlib `sqlite3`) + content-addressed blob directory | One file per run, transactional appends, simple queries for branch tips. See JC-11. |
| Graph patches | `jsonpatch` (RFC 6902) | `json_patch` format (§16, JC-06). |
| Sandbox | Docker Engine in rootless mode, via the `docker` Python SDK | §14: rootless, custom seccomp, `--cap-drop=ALL`, `--network=none`, read-only root FS, plus `--memory`, `--pids-limit` and `--cpus` caps, because run_tests executes arbitrary buggy-repo code. Prerequisite: cgroup v2 delegation for rootless Docker (README). |
| Model access | Own `ModelClient` protocol with adapters: OpenAI-compatible (`httpx`) and Anthropic (official SDK); model IDs per role in config | §18 "Model Availability": Meta Muse access is unconfirmed, so the code depends on roles, not providers. See JC-12. |
| Statistics | Pure-Python Clopper–Pearson (bisection on the binomial CDF) | Avoids a SciPy dependency for one function (§13). |
| CLI (MVP Operator Console) | Typer | `apex run / verify / report / corpus check`. See JC-13. |
| Tests / lint | pytest (+ `-m docker` marker for integration), ruff | Standard and fast. |

## 3. Repository layout

```
apex/
├── pyproject.toml              [MVP] deps, ruff/pytest config, `apex` console script
├── README.md                   [MVP] quickstart: build sandbox image, check corpus, run, verify, report
├── apex.example.yaml           [MVP] annotated run config with the §10 defaults
├── docker/
│   ├── sandbox.Dockerfile      [MVP] task-run image: Python + pytest, non-root user, no extra tools
│   └── seccomp.json            [MVP] custom seccomp profile (§14)
├── corpus/
│   ├── manifest.yaml           [MVP] public tasks: id, distribution, file hashes (hashed into Genesis)
│   └── public/<task_id>/       [MVP] repo/ (buggy snapshot), tests/ (public tests), task.yaml (prompt, editable_paths, test_command; §6.2)
│                               The holdout is NOT in the repo: $APEX_HOLDOUT_DIR (default ~/.apex/holdout/) holds
│                               hidden_tests/<task_id>/, tasks/<held_out_id>/ and its own manifest; never committed (JC-16)
├── seeds/
│   └── baseline.yaml           [MVP] baseline Graph Config + Prompt Axioms; generation 0 = this + P−1 mutations
├── runs/<run_id>/              [MVP] (gitignored) ledger.sqlite, blobs/, blobs-holdout/, report.md (heads are published outside runs/, see writer.py)
├── src/apex/
│   ├── cli.py                  [MVP] Typer entry point (Operator Console, MVP form)
│   ├── config.py               [MVP] RunConfig model: population, budgets, weights, model roles, seed; load + hash
│   ├── orchestrator.py         [MVP] Swarm Orchestrator: run lifecycle, worker pool, owns the ledger writer
│   ├── budget.py               [MVP] token accounting, per-run caps, holdout reserve (§10 Budget)
│   ├── rng.py                  [MVP] one seeded RNG with named sub-streams (batches, scopes, seeding); seed recorded in Genesis
│   ├── report.py               [MVP] run report: survivors, held-out rates with 95% intervals, published heads
│   ├── schemas/                [MVP] pydantic mirrors of §16
│   │   ├── ledger.py           Block, StateTransition, BlockKind
│   │   ├── agents.py           SubagentInstance, GraphConfig, AgentSpec
│   │   ├── evolution.py        MutationProposal, PatchPayload, AttributionEntry
│   │   ├── evaluation.py       FitnessRecord, RubricWindowRecord
│   │   ├── tools.py            ToolEntry
│   │   ├── escalation.py       [P2] EscalationEvent
│   │   └── signature.py        [P2] BehavioralSignature
│   ├── ledger/                 Decision Ledger (§8)
│   │   ├── canonical.py        [MVP] I-JSON validation (duplicate keys rejected via object_pairs_hook, NaN/Infinity via
│   │   │                             parse_constant, integers beyond ±2^53), RFC 8785 serialization, block_hash
│   │   ├── blobs.py            [MVP] content-addressed stores: blobs/ (model I/O, tool results, public test output) and
│   │   │                             blobs-holdout/ (hidden-test results; read only by evaluation/ and ledger/verify.py)
│   │   ├── store.py            [MVP] SQLite tables: blocks, branch tips
│   │   ├── writer.py           [MVP] single writer: genesis, append, fork, Lamport clock; publishes heads to the console,
│   │   │                             the report and $APEX_HEADS_FILE outside runs/ (default ~/.apex/heads/<run_id>.jsonl; JC-15)
│   │   ├── verify.py           [MVP] full verification + comparison with published heads
│   │   └── attribution.py      [MVP stub] Causal Attribution Log entries (trace block + failing output hash)
│   ├── models/                 model access by role
│   │   ├── client.py           [MVP] ModelClient protocol, Completion, usage, pinned-model-ID check
│   │   ├── openai_compat.py    [MVP] adapter for OpenAI-compatible endpoints
│   │   ├── anthropic.py        [MVP] adapter using the Anthropic SDK
│   │   └── replay.py           [MVP] serves recorded responses from blobs (tests and §7 replays)
│   ├── agent/                  Swarm Subagent
│   │   ├── graph.py            [MVP] Graph Config validation: unique ids, targets, reachable terminal, known tools
│   │   ├── prompts.py          [MVP] prompt assembly: axioms + delimited tool output (§15 prompt injection)
│   │   └── runtime.py          [MVP] interpreter: runs one subagent on one task, emits transitions
│   ├── sandbox/                Sandbox Pool (§14)
│   │   ├── pool.py             [MVP] container lifecycle and mounts (agent run: the task's repo/ + public tests/ only;
│   │   │                             evaluation run: + that task's hidden tests), concurrency cap, timeouts, resource caps,
│   │   │                             violation detection
│   │   ├── tools.py            [MVP] read_file / run_tests / write_patch with denied_paths enforcement
│   │   └── proxy.py            [P2] authenticated egress proxy (needed once agent-authored code runs; JC-02)
│   ├── tasks/                  Task Ingress
│   │   └── corpus.py           [MVP] load + verify the public manifest, public pool, batch sampling (never opens the holdout)
│   ├── evaluation/             Evaluation Engine (§9)
│   │   ├── gates.py            [MVP] L0 gate definition (versioned data, hashed into Genesis) and the checks
│   │   ├── scoring.py          [MVP] L1, tie-break
│   │   ├── holdout.py          [MVP] the only reader of $APEX_HOLDOUT_DIR (MVP custodian): hashes its manifest for Genesis,
│   │   │                             mounts hidden tests into evaluation sandboxes, writes results to blobs-holdout/
│   │   ├── hidden.py           [MVP] hidden score, L4 divergence, Clopper–Pearson interval
│   │   ├── engine.py           [MVP] evaluate(agent, batch) → FitnessRecord
│   │   ├── robustness.py       [P3] L2 stress suites
│   │   └── diversity.py        [P2] L3 behavioral distance
│   ├── evolution/              §10
│   │   ├── loop.py             [MVP] generation loop: sample, evaluate, select, refill, rollback, stop
│   │   ├── seeding.py          [MVP] generation 0: baseline + P−1 mutations, one lineage per seed
│   │   ├── ucb1.py             [MVP] lineage statistics and parent selection
│   │   ├── mutation.py         [MVP] Meta Muse Code role: public trace → proposal → validate → child copy
│   │   │                             (reads blobs/ only; never blobs-holdout/)
│   │   ├── patches.py          [MVP] apply json_patch / axiom_edit; python_ast [P2]
│   │   └── drift.py            [P2] KL drift check
│   ├── escalation/             [P2] entropy.py, deadlock.py, spark.py (Meta Muse Spark role)
│   ├── governance/             [P2] rubric_window.py, gate_patch.py
│   ├── registry/               [P2] Agent Spec Registry: freeze, store, export
│   ├── watcher/                [P3] Signal Watcher
│   └── vision/                 [P3] SAM 3.1 pipeline
└── tests/
    ├── unit/                   [MVP] canonical, ledger, verify-tamper, ucb1, scoring, patches, graph, budget
    ├── integration/            [MVP] sandbox tools and gates against real containers (marker: docker)
    └── e2e/test_smoke.py       [MVP] 2 generations, P=4, K=2, replay model, fake corpus
```

## 4. Component map (design §5 → code)

| Design component | Code | MVP? |
|---|---|---|
| Task Ingress | `tasks/corpus.py`, `corpus/` | MVP |
| Swarm Orchestrator | `orchestrator.py`, `budget.py` | MVP |
| Swarm Subagent | `agent/`, `seeds/` | MVP |
| Sandbox Pool | `sandbox/`, `docker/` | MVP (proxy P2) |
| Decision Ledger | `ledger/` (except attribution) | MVP |
| Causal Attribution Log | `ledger/attribution.py` | MVP stub |
| Evaluation Engine | `evaluation/` | MVP (L2 P3, L3 P2) |
| Meta Muse Code | `evolution/mutation.py`, `evolution/patches.py`, `models/` | MVP |
| Meta Muse Spark | `escalation/spark.py` | P2 |
| Signal Watcher | `watcher/` | P3 |
| SAM 3.1 | `vision/` | P3 |
| Agent Spec Registry | `registry/` | P2 (unused in MVP) |
| Operator Console | `cli.py`, `report.py` | MVP (CLI + report) |
| (support) | `config.py`, `rng.py`, `schemas/`, `ledger/blobs.py`, `models/replay.py`, `evolution/loop.py`, `evolution/seeding.py`, `evolution/ucb1.py` | MVP |

## 5. Deep dives

### 5.1 Ledger (design §8): `ledger/`
- **Branches.**
  - `root` holds `genesis`, `generation_event` and `gate_version` blocks.
  - Each subagent has its own branch of `agent_run` blocks, one block per task run, whose transitions are the run's steps.
  - A branch is forked from its parent agent's tip (seeds fork from Genesis).
- **What a transition points to.** Every `result_hash` points to a blob record:
  - `{request, response, model_id, usage}` for a model call
  - `{tool, args, result}` for a tool call
  - test output
  - mutation proposals and attribution entries, referenced from `generation_event` blocks
- **Hidden results** are stored in `blobs-holdout/`. The ledger holds only their hashes, in the root-branch `generation_event` (design §8, C-80). The orchestrator appends them like every other block.
```
fork(parent_tip_hash, agent_id):                  # parent agent's tip; Genesis for a seed (design §8)
    branch_id = sha256(parent_tip_hash + agent_id)   # 64-hex prefix ⇒ unambiguous
    tips[branch_id] = parent_tip_hash; return branch_id
append(kind, branch_id, transitions):            # called only by the orchestrator thread
    parent = blocks[tips[branch_id]]             # first block of a branch → the forked-from tip
    blk = {kind, height: parent.height + 1, timestamp: now(), parent_hash: parent.block_hash,
           branch_id, lamport_clock: max(parent.lamport_clock, last_clock) + 1, state_transitions}
    check_ijson(blk); blk.block_hash = sha256(jcs(blk))           # hash excludes block_hash itself
    with sqlite.transaction(): insert(blk); tips[branch_id] = blk.block_hash
    last_clock = blk.lamport_clock               # ledger-wide max (single writer ⇒ no race)
publish_heads(g): write {generation: g, tips} to console, report, $APEX_HEADS_FILE
verify(): replay blocks in lamport order → recompute hashes, parent/height/clock rules,
          blob hashes (both stores) → compare final tips with every published heads entry
```
- **Genesis** transitions record: the run config (hash of the parsed config), the L0 gate definition (`evaluation/gates.py`), the public manifest, the holdout manifest hash (from `evaluation/holdout.py`), and the RNG seed.

### 5.2 Orchestrator and generation loop (design §10): `orchestrator.py`, `evolution/loop.py`
```
pop = seeding.generation0(baseline, P)                       # P lineages, branches forked from Genesis
prev_survivors = []
for g in range(G_max):
    if not budget.can_start_generation(): break              # holdout_reserve stays untouched
    batch = corpus.sample(K, rng.batches)                     # root: generation_event{batch manifest hash}
    runs, hidden_refs = engine.evaluate_all(pop, batch)       # parallel; runs: per-agent PublicResult (no hidden)
    for run in runs.all_task_runs(): ledger.append("agent_run", run.branch_id, run.transitions)
    results = runs.per_agent()                                # agent_id → PublicResult (l1, tokens, tip block_hash)
    if g > 0: ucb1.credit(children_prev, results)
    ranked = rank([r for r in results.values() if r.l0_passed], key=(-l1, tokens, tip_block_hash))
    if not ranked:
        if g == 0: stop("seeds fail L0")
        survivors = prev_survivors                            # rollback: this batch is discarded
    else:
        survivors = ranked[:μ]; mark(survivors: survived, rest: pruned, L0 failures: disqualified)
    children = []
    for lineage in ucb1.pick(P - len(survivors), lineages_of(survivors)):   # with replacement
        child = mutation.make_child(best_survivor(lineage), results)        # design §10 step 4
        if child is None: child = mutation.make_child(best_survivor(ucb1.pick(1, ...)), results)
        if child is not None: children.append(child)          # second failure → slot empty (C-78)
    pop, prev_survivors, children_prev = survivors + children, survivors, children
    ledger.generation_event(g, selection, proposals, hidden_refs); ledger.publish_heads(g)
heldout = holdout.run_final(prev_survivors)                   # uses budget.holdout_reserve
report.write(run, heldout)                                    # rates + Clopper–Pearson 95% intervals
```
- **Status (design §16 Subagent Instance):** a new agent is `active`. It is `evaluating` while its generation runs, then `survived`, `pruned` or `disqualified`. A survivor becomes `evaluating` again in the next generation. After a rollback, the discarded members are `disqualified`. `escalated` and `frozen` are unused in the MVP.
- **Concurrency:** a `ThreadPoolExecutor(max_concurrent_sandboxes)` runs task runs. Workers return transitions, and only the orchestrator thread calls `ledger.append` (single writer).
- **Atomic generations:** a generation's `generation_event` is appended only after all its runs finish. If the budget runs out mid-generation, in-flight runs finish, the generation is recorded as `aborted`, and the run goes to the final held-out evaluation with the last complete survivors.
- **Type separation:** `engine.evaluate_all` returns `PublicResult` objects, which have no hidden field, plus opaque `hidden_refs` (hashes into `blobs-holdout/`, written there by `evaluation/hidden.py`). The orchestrator only forwards the hashes to the ledger, so it stays the single writer, and selection code can't read hidden scores by construction.
- **Tie-break stability:** `tip_block_hash` is the agent's last `agent_run` block of this generation. Its hash includes a timestamp, so it differs between runs. Replay (design §7) re-derives selection from the *logged* blocks, not by re-hashing, so the recorded order stays reproducible.

### 5.3 Agent runtime (design §7, §16 Graph Config): `agent/runtime.py`
```
node, steps, ctx = graph.start, 0, [task.prompt]
while node.kind != "terminal" and steps < graph.max_steps:
    if node.kind == "llm":   out = models.complete("subagent", prompts.build(axioms[node.axiom_refs], ctx))
                             outcome, args = parse(out, allowed=labels(node))   # JSON {"outcome", "args"}; bad → "error"
    if node.kind == "tool":  res = session.exec(node.tool, args); outcome = res.status; ctx += delimited(res)
    if node.kind == "check": outcome = PREDICATES[node.id](session)             # fixed set (JC-08)
    record(step, result_hash = blobs.put(...)); node = next_node(node, outcome); steps += 1
if node.kind != "terminal": outcome = "max_steps"             # logged; not an L0 failure by itself (design §9)
patch = session.diff()                                        # final patch = workspace vs original snapshot
```
- **Prompt injection:** tool output enters the prompt only inside `<tool_output tool="…">…</tool_output>`, and the system axioms say it is data, not instructions (design §15).
- **Output contract:** an llm node's output must name one of *its own* transition labels. That keeps the model inside the graph.

### 5.4 Evaluation and holdout isolation (design §9, §9.1, §13): `evaluation/`
There are three containers per task run. Holdout material is mounted only in the last one.
1. **Agent container:** the task's `repo/` (writable copy) and public `tests/` (read-only). The runtime drives tools here.
2. **Public check:** a fresh container on the patched copy runs public tests, giving `pass_rate`. The L0 gates (design §9) are checked here:
   - no sandbox violation (§5.6) and no network access (design §9, C-81). With `--network=none`, a network attempt can't succeed
   - the patch applies cleanly to a fresh copy and leaves test files untouched (test-directory hash unchanged). As defense in depth for C-77, a patch path outside `editable_paths` also fails this gate
   - the run finished within `timeout_s` and `token_budget`
3. **Hidden check:** `holdout.py` mounts that task's hidden tests into another fresh container on the same patched copy. The hidden pass rate goes to `blobs-holdout/`, and only its hash is returned (as `hidden_refs`) for the ledger.

There is one Fitness Record per agent per generation (design §16). Its `batch_id` is the batch manifest hash, and its `rubric_window_id` is the constant `w0` in the MVP (single window, design §12). Fitness Records in `blobs/` carry `hidden_score: null` and `divergence_metric: null`. The evaluator writes the completed record to `blobs-holdout/`, and `report.py` reads it at the end.

This isolation holds for agent code and for the mutation prompt (`mutation.py` builds prompts only from `blobs/`). It is *convention* against a malicious operator on the same host, which is accepted for the MVP (JC-16).

### 5.5 Mutation pipeline (design §10 Mutation): `evolution/mutation.py`, `evolution/patches.py`
```
make_child(parent, results):
    trace = worst public run of parent this generation (lowest pass_rate), else its most expensive run
    scope = rng.scopes.choice(config.mutation.scopes)                  # graph_config | prompt_axiom
    prompt = unit content + trace excerpt (failing public test output, last N steps) + patch-format spec
    for attempt in 1..max_attempts:                                     # default 3; each call counts in budget
        try:
            payload = parse(models.complete("mutation", prompt))
            unit = patches.apply(copy(parent.unit[scope]), payload)     # json_patch | axiom_edit
            validate(unit); check(ops(payload) <= max_patch_ops)        # graph.validate / axiom bounds (JC-17)
            break
        except (ParseError, PatchError, ValidationError) as e:
            prompt += error(e)                                          # design §10 (C-78)
    else: return None    # caller redraws one parent by UCB1; a second failure leaves the slot empty this generation (JC-19)
    child = copy(parent) with unit replaced; new agent_id; lineage_id = parent's; fork branch
    attribution = {block_hash: trace block, step_identifier, empirical_evidence_link: result_hash of failing test output}
```

### 5.6 Sandbox and tools (design §14): `sandbox/`
- **Container:** image `apex-sandbox`, non-root, with these flags:
  - `--network=none`, `--cap-drop=ALL`, `--security-opt no-new-privileges`, `--security-opt seccomp=docker/seccomp.json`
  - `--read-only` with a tmpfs `/tmp`
  - `--memory 1g --pids-limit 256 --cpus 1` (config)
- The workspace is a per-run copy at `/work`, with `/work/tests` mounted read-only.
- **Tools** run via `docker exec` with per-tool timeouts:
  - `read_file(path)`: path must resolve inside `/work`; output capped at 64 KB.
  - `run_tests()`: the task's `test_command` on public tests; output truncated (head + tail, 16 KB).
  - `write_patch(diff)`:
    - Unified diff, checked with `git apply --check`.
    - Rejected if any path is outside `task.editable_paths` or matches `denied_paths` at any depth: `tests/**`, `**/conftest.py`, `**/pytest.ini`, `**/setup.cfg`, `**/tox.ini`, `**/pyproject.toml`, `**/sitecustomize.py`, `**/usercustomize.py`, `**/*.pth`. Pytest collects nested `conftest.py` files. This list implements design §14 (C-77) and is deliberately stricter than the files named there.
    - Also rejected: rename, copy, symlink, mode-change and binary hunks. Only plain text edits to regular files are allowed.
- **Violations:** a container killed by seccomp or the OOM killer, a timeout, or an escape attempt that is detected sets the L0 `sandbox_violation` flag.

### 5.7 Escalation (design §11, Phase 2)
`escalation/entropy.py` wraps llm-node calls with n-sample disagreement and a per-node rolling MAD baseline. `deadlock.py` keeps a wait-for graph across workers. `spark.py` hands the failing context to the Meta Muse Spark role. Nothing in the MVP imports this package.

## 6. Specs

### 6.1 Run config (`apex.example.yaml`)
```yaml
run:        {seed: 1234, g_max: 10}
population: {P: 8, mu: 4}                 # λ = P − μ is derived (refills use P − survivors)
batch:      {K: 10}
ucb1:       {c: 1.4142}
l1_weights: {pass_rate: 0.7, tokens: 0.2, latency: 0.1}
limits:     {token_budget: 50000, timeout_s: 300, memory: 1g, pids: 256, cpus: 1.0}
budget:     {tokens_total: 20000000, holdout_reserve: 2000000, max_concurrent_sandboxes: 8}
mutation:   {scopes: [graph_config, prompt_axiom], max_attempts: 3, max_patch_ops: 5}
models:                                   # roles → adapters; IDs are your choice (JC-12)
  subagent: {adapter: openai_compat, base_url: "<set>", model_id: "<set>"}
  mutation: {adapter: anthropic, model_id: "<set>"}
paths:      {corpus: corpus/, holdout: "${APEX_HOLDOUT_DIR}", heads_file: "${APEX_HEADS_FILE}", runs: runs/}
gates:      {version: 1}
```
The config is validated by `config.RunConfig`. Its hash (JCS of the parsed model) goes into Genesis. Secrets (API keys) come only from environment variables and are never in the config or the ledger.

### 6.2 Task format (`corpus/public/<id>/task.yaml`)
```yaml
id: off_by_one_007
distribution: off_by_one
prompt: "window_sum() returns totals that miss the last element…"
editable_paths: ["src/**/*.py"]
test_command: "pytest -q tests"
```
Timeout and token caps come from `limits` only, not per task, because L1 normalizes against them (design §10).

### 6.3 Key interfaces
```python
class ModelClient(Protocol):
    def complete(self, role: str, messages: list[Message]) -> Completion: ...  # text, usage, model_id (checked vs pin)
class Ledger:  # ledger/writer.py
    def genesis(self, records: GenesisRecords) -> Block: ...
    def fork(self, parent_tip: str, agent_id: str) -> str: ...
    def append(self, kind: BlockKind, branch_id: str, transitions: list[StateTransition]) -> Block: ...
    def publish_heads(self, generation: int) -> None: ...
class SandboxSession(Protocol):  # sandbox/pool.py; a context manager
    def exec(self, tool: str, args: dict) -> ToolResult: ...
    def diff(self) -> str: ...
class Engine:  # evaluation/engine.py
    def evaluate_all(self, pop: list[Agent], batch: Batch) -> tuple[GenerationRuns, list[HiddenRef]]: ...  # no hidden values
```

### 6.4 Storage
- **`ledger.sqlite`:**
  - `blocks(block_hash PK, branch_id, kind, height, lamport_clock, parent_hash, body JSON)` and `tips(branch_id PK, block_hash)`.
  - An `agents(agent_id PK, lineage_id, parent_agent_id, generation, state_machine_version, status)` index, derived from the ledger and rebuildable by `apex verify --reindex`.
- **Blobs:** `blobs/<aa>/<sha256>` (first two hex characters as the directory), the same under `blobs-holdout/`. Each blob is the JCS bytes of its record.

### 6.5 Errors and budget enforcement
- **Model API errors:** 3 retries with exponential backoff. If they keep failing, the task run is marked `infra_error` and retried once in a fresh container. If it still fails, the generation is aborted (atomic, §5.2). Infrastructure faults never count as an agent's L0 failure.
- **Run-log states:** `aborted` (a generation) and `infra_error` (a task run) are recorded in the `generation_event` transitions. They are not Subagent Instance statuses (design §16), and no design schema changes are needed. This is a code-level rule (JC-18).
- **Agent faults** (unparsable output, an unknown label) become the `error` transition outcome. They become L0 failures only through the timeout or token cap.
- **Budget:**
  - `budget.reserve(token_budget)` runs before each task run and `release(actual)` after it.
  - `can_start_generation()` requires headroom above `holdout_reserve` of 1.5 × the largest generation cost seen so far. Before generation 0 it requires P × K × token_budget. A generation that still runs out is aborted (§5.2), and the reserve stays untouched (JC-18).
  - Each mutation call reserves `max_tokens` of its request and releases the actual usage.

### 6.6 Testing strategy
- **Unit:**
  - JCS round-trip and I-JSON rejection (duplicate keys, NaN, 2^53+1).
  - Block hashing.
  - Tamper tests: edit one block → `verify` fails; rewrite and rehash everything → heads mismatch.
  - UCB1 math (unvisited first, credit timing).
  - L1 and tie-break.
  - Patch application, one-unit validation and graph validation.
  - Budget reservation.
- **Integration (`-m docker`):**
  - Network is blocked.
  - write_patch rejects tests/, a root and a nested `src/conftest.py`, rename/symlink hunks and paths outside editable_paths.
  - A timeout and an OOM each trigger an L0 violation.
  - Hidden tests are absent from the agent container.
- **End-to-end:** `tests/e2e/test_smoke.py` runs 2 generations with P=4, K=2, on a 4-task fake corpus, with the replay model client. It asserts that `apex verify` passes and the report lists survivors with intervals.
