# Judgement calls

Each entry is a point where a human decision would be needed, or much better, during the unattended run. It lists the options I would have asked about and the option I took. **Nothing here is final.** Reply with `JC-NN: <option>` to settle one. If your answer differs from the option taken, the related C-IDs in `CHANGES.md` are amended.

Status: **OPEN** = awaiting your answer.

---

### JC-01 · Phase 4 · Ledger naming: "Merkle-DAG" · related: C-27, C-32
- **Context:** with no merging (D-04), every block has one parent, so the ledger is a hash-linked tree. The Phase 4 reviewer called "Merkle DAG" a misnomer. In IPFS and Git, "Merkle DAG" means any hash-linked structure, and a tree is a DAG. The term appears in about 6 places (§2 ×2, §4, §5, §8, §17).
- **Options:**
  1. **Keep "Merkle-DAG"** with the definition sentence in §8 (C-27). *(taken)*
  2. Rename to "hash-linked tree" everywhere. This is precise for the MVP, but the term has to change again if merging is ever added.
  3. Keep "Merkle-DAG" in the vision text (§1, §2) and say "hash-linked tree (MVP)" in §8 and §17.
- **Status:** OPEN

### JC-02 · Phase 5 · MVP sandbox network architecture · related: C-38, §6, §14, §15
- **Context:** §14 (original) says containers have zero egress except an authenticated local API proxy with allowlists. The Phase 5 review found C-38's "no network access" contradicted this. I made C-38 consistent with §14 ("no network access other than the allowlisting proxy"). The real question is architectural:
  - In the MVP, the subagent's state machine is *data* (graph config + prompt axioms), because code_ast is cut (D-08b).
  - So a trusted interpreter in the orchestrator could make the model calls, and only tool execution (read_file / run_tests / write_patch on the task repo) would need to run in a container, with networking fully disabled.
- **Options:**
  1. **Host-side interpreter, containers with `--network=none`, proxy deferred to Phase 2** (no MVP tool needs egress; the agent's patches still run under test in the network-less container). *(Recommended: the simplest and strongest isolation for a 10-day sprint, and no proxy to build. Needs design changes to §6 "Isolation Level" and §14, proposed in Phase 9 as PENDING C-IDs.)*
  2. Interpreter inside each container, model calls through the authenticated local proxy on an internal Docker network (as §14 is written). It matches the current text but costs roughly a day of proxy and network work.
  3. Hybrid: interpreter on the host in the MVP, but keep the §14 text as the target architecture and add a note.
- **Taken so far:** C-38 wording follows the current §14 (option 2's text). CODE_STRUCTURE.md (Phase 8/9) will be written for **option 1** and flagged, because it removes a whole component.
- **Status:** OPEN

### JC-03 · Phase 5 · Entropy-trigger defaults (Phase 2 feature) · related: C-33
- **Context:** the trigger needed concrete numbers. All of them are guesses until calibrated.
- **Options:**
  1. **n = 5 samples, window = last 50 executions of the node, MAD floor = 0.1 nats, threshold z > 3.5** (the standard modified-z cut-off). *(taken)*
  2. A larger sample (n = 10) for a finer signal, at about 2× the sampling cost on sampled steps.
  3. Leave all values unset and only describe the method, deciding at Phase 2 implementation time.
- **Status:** OPEN (low urgency: Phase 2)

### JC-04 · Phase 5 · Canary tasks: MVP or Phase 2 · related: C-37, C-42
- **Context:** canaries (fixed tasks with known scores, run each generation) detect silent model swaps. They cost extra task runs every generation and were not in your MVP scope decisions.
- **Options:**
  1. **Phase 2.** The MVP relies on model-ID pinning and checking only. *(taken; added to the roadmap via C-42)*
  2. MVP with 2 canary tasks per generation (+20 task runs per engine run, about 2.5% more task runs).
- **Status:** OPEN

### JC-05 · Phase 5 · Budget defaults · related: C-41, C-11 (L1 denominators)
- **Context:** L1 normalizes cost and latency against token_budget and timeout, so these values shape selection, not just cost. The total cap decides how far a run gets.
- **Options:**
  1. **token_budget = 50k tokens per task run, timeout = 300 s, tokens_total = 20 M, holdout_reserve = 2 M, max_concurrent_sandboxes = 8.** *(taken)*
  2. Tighter: 25k / 120 s / 10 M. Cheaper, and pushes selection harder toward lean agents, but may cut off correct but slow fixes.
  3. Set them after a pilot. Run generation 0 once, and set token_budget/timeout to roughly the 90th percentile of the seed agents' usage.
- **Note:** the dollar cost of 20 M tokens depends on the models chosen (Open Point "Model Availability"), so it isn't stated.
- **Status:** OPEN

### JC-06 · Phase 6 · Mutation patch formats · related: C-44, C-39
- **Context:** the patch payload needed a concrete format per mutation unit. This choice fixes what the mutation model must output, and therefore its prompt.
- **Options:**
  1. **graph_config → RFC 6902 JSON Patch; prompt_axiom → `axiom_edit` list of {op: add|replace|remove, index, text}** (supports add/modify/remove, per your amendment). *(taken)*
  2. A full replacement of the mutated unit (the model returns the whole new graph or axiom list). Simpler to generate, but it hides what changed, and "one edit" can't be enforced.
  3. A unified text diff for both. Familiar to models, but graph patches lose schema-level validation before apply.
- **Status:** OPEN

### JC-07 · Phase 6 · Version label of the revised doc · related: C-53
- **Options:**
  1. **"1.2.0 (draft; changes pending approval)"**. *(taken)*
  2. "2.0.0", given the scope of the changes (new loop, MVP scope, ledger rules).
  3. Keep 1.1.0 until you approve.
- **Status:** OPEN (low stakes)

### JC-08 · Phase 6 · Shape of the Graph Config (subagent topology) · related: C-57, §7 Open Point, §18 "Topology Representation"
- **Context:** the MVP mutates only graph_config and prompt_axiom (D-08b), so the topology must be pure data. The schema decides what mutation can express. §7/§18 list topology representation as open.
- **Options:**
  1. **Explicit node graph:** nodes of kind llm / tool / check / terminal; labeled transitions ("ok", "error", "tests_failed"); llm nodes reference axioms by index; a max_steps cap. *(taken)*
  2. A linear pipeline: an ordered list of steps with retry counts. Much smaller mutation space and easier to validate, but no branching on test outcomes.
  3. A ReAct-style single loop: one llm node choosing among tools until "done". Mutation then acts almost only on the prompt axioms, which weakens the "topology evolution" claim.
- **Also open within option 1:** whether `check` nodes may evaluate arbitrary expressions or only a fixed set of predicates (e.g. `tests_passed`, `patch_applied`). The schema currently leaves this to transition labels.
- **Status:** OPEN

### JC-09 · Phase 7 · Vision text vs MVP claims (§1, §3, §4, §19) · related: C-69
- **Context:** your original Summary, Goals, Principles and One-Line Definition describe the full system. They promise "verified" Agent Specs, behavioral distance constraints, "absolute auditability" and "bounded drift envelopes", none of which the MVP delivers. This is your framing, so I didn't rewrite it.
- **Options:**
  1. **Keep the vision text and add a scope note** pointing to §17 Phase 1 (C-69). *(taken)*
  2. Rewrite §1/§19 for the MVP ("…a hackathon MVP that evolves bug-fixing agents and reports hidden-holdout results…"), and move the vision into a separate "Long-term vision" paragraph.
  3. Leave as-is with no note.
- **Status:** OPEN

### JC-10 · Phase 7 · Generation 0 with zero L0 passes · related: C-72
- **Options:**
  1. **Stop the run and report the seeds as failing.** *(taken: broken seeds indicate a setup error, and evolving from nothing wastes budget)*
  2. Re-seed: generate P new seeds by mutating the baseline, up to N attempts.
  3. Relax L0 for generation 0 only. Not recommended: it breaks "hard gates are never traded off" (§4).
- **Status:** OPEN (low stakes)

### JC-11 · Phase 8 · Ledger storage · related: CODE_STRUCTURE §2, §3 `ledger/`
- **Options:**
  1. **SQLite file per run + content-addressed blob directory.** *(taken: transactional appends, easy tip and branch queries, one file to copy)*
  2. Append-only JSONL file per branch + blob directory. Simplest to inspect with a text editor, but tips and verification need full scans, and partial writes need care.
  3. An embedded KV store (LMDB/RocksDB). Faster at scale, but an extra native dependency for no MVP benefit.
- **Status:** OPEN

### JC-12 · Phase 8 · Model providers for the MVP roles · related: CODE_STRUCTURE §2, design §18 "Model Availability"
- **Context:** the design names Meta Muse Spark/Code, but access is unconfirmed. The MVP needs two roles: the **subagent** model (many calls, so cost matters) and the **mutation** model (Meta Muse Code role, about 40 calls per run).
- **Options:**
  1. **Provider-agnostic adapters (OpenAI-compatible + Anthropic), model IDs set per role in config; no default chosen in the doc.** *(taken)*
  2. Commit now to one provider for both roles, simplifying the code to one adapter.
  3. Different providers per role: a cheap fast model for subagents, a strongest-available model for mutation.
- **Note:** you need to pick concrete model IDs before the implementation plan's cost estimate.
- **Status:** OPEN

### JC-13 · Phase 8 · Operator Console form in the MVP · related: design §5, CODE_STRUCTURE `cli.py`, `report.py`
- **Options:**
  1. **CLI (`apex run/verify/report`) + a Markdown run report.** *(taken: the cheapest; the report holds the published heads and results)*
  2. CLI + a small local web dashboard (live generation progress, lineage chart). Better for a hackathon demo, costs about 1 day.
  3. CLI + an HTML report rendered at the end of the run (static charts). Middle ground for the demo.
- **Status:** OPEN

### JC-14 · Phase 8 · Source of truth for the §16 schemas · related: CODE_STRUCTURE `schemas/`
- **Options:**
  1. **pydantic models are the source; JSON Schema is exported from them and checked against design §16 in a test.** *(taken)*
  2. JSON Schema files (copied from §16) are the source; code validates with `jsonschema` and uses plain dicts. Matches the doc exactly, but there are no typed models.
  3. Generate pydantic models from JSON Schema files (datamodel-codegen). Keeps the doc as the source, but adds a codegen step.
- **Status:** OPEN

### JC-15 · Phase 8 · Where branch heads are published (tamper anchor) · related: design §8 C-27, CODE_STRUCTURE `ledger/writer.py`
- **Context:** heads must live outside the ledger so a full rewrite is detectable. Anything on the same machine protects against accidents and agent misbehaviour, not against the machine owner.
- **Options:**
  1. **Console + run report + `$APEX_HEADS_FILE` outside `runs/` (default `~/.apex/heads/<run_id>.jsonl`).** *(taken: zero infrastructure)*
  2. Also commit each generation's heads to a git remote (or post them to a chat channel). This gives real external anchoring, but needs credentials and network on the host.
  3. Console and report only (no file). The simplest; verification then relies on the human keeping the console output.
- **Status:** OPEN

### JC-16 · Phase 8 · Where the hidden holdout lives · related: design §9.1, CODE_STRUCTURE `corpus/`, `evaluation/holdout.py`
- **Context:** if hidden tests sit in the repo and the repo is pushed (common at hackathons), the holdout is public.
- **Options:**
  1. **Outside the repo at `$APEX_HOLDOUT_DIR` (default `~/.apex/holdout/`), never committed; only its manifest hash enters Genesis.** *(taken)*
  2. In a separate private repository or storage bucket, fetched by the evaluator at run start. Shareable within the team without exposure, but needs credentials.
  3. Encrypted in the repo, with the key only on the evaluation host. Convenient, but the key management is easy to get wrong.
- **Status:** OPEN

### JC-17 · Phase 9 · What counts as "one edit" in a child · related: design §10 Mutation (C-83), D-02 user amendment, CODE_STRUCTURE §5.5, §6.1
- **Context:** the user defined a child as the parent with one in-place edit (add, modify or remove). A JSON Patch or axiom edit can contain several operations, so "one edit" needs a mechanical bound.
- **Options:**
  1. **One proposal per child, capped at `max_patch_ops: 5` operations, all within one unit (one graph config or one axiom).** *(taken)* This allows coherent edits such as rewiring a node plus its edge, but bounds drift.
  2. Exactly one patch operation per child. This is the most literal reading, but many useful graph edits (add a node *and* connect it) become impossible in one step.
  3. No op cap; one unit per child. Simpler, but a single "edit" could rewrite a whole axiom set.
- **Status:** OPEN

### JC-18 · Phase 9 · When a generation may start, given the budget · related: design §10 Stopping/Budget, CODE_STRUCTURE §5.2, §6.5
- **Context:** design §10 says the run stops "when the token budget is spent". CODE_STRUCTURE §5.2 adds a code-level rule that generations are atomic (no partial generation enters selection), so the code needs a rule for whether to start one more generation. Atomicity is not in design.md. If you want it there, it would be a new C-ID.
- **Options:**
  1. **Start if the headroom above holdout_reserve is ≥ 1.5 × the largest generation cost seen so far (worst case P × K × token_budget before generation 0); abort a generation that still runs out.** *(taken)* This wastes little budget and rarely aborts.
  2. Require worst-case headroom (P × K × token_budget = 4 M) for every generation. It never aborts, but it can leave about 20% of the budget unused.
  3. Start whenever any budget remains, and accept frequent aborted final generations. This uses the most budget, but the last generation is often wasted.
- **Status:** OPEN

### JC-19 · Phase 9 · What happens when a mutation keeps failing validation · related: design §10 Mutation (C-78), CODE_STRUCTURE §5.5
- **Options:**
  1. **3 attempts with the error fed back, then one redraw of the parent by UCB1, then leave the slot empty for this generation.** *(taken)* Cost is bounded, and the population is short by one only in rare cases.
  2. Keep redrawing parents until P members exist. The population is always full, but cost is unbounded if the mutation model is broken.
  3. After 3 failed attempts, stop the run with an error. This is the clearest signal, but one bad proposal kills a whole run.
- **Status:** OPEN

---
## Retrospective: calls embedded in Phases 3–5 (logged in Phase 10, action 1b)
Phases 3–5 ran without a human in the loop. The calls below were made inside C-01..C-43 and are not covered by D-01..D-08 or JC-01..JC-05.

### JC-20 · retro Phase 3 · Generation-0 seeding · related: C-14, design §10 "Generation 0", CODE_STRUCTURE `evolution/seeding.py`
- **Context:** the design allows either option; CODE_STRUCTURE assumes option 1.
- **Options:**
  1. **One hand-written baseline plus P − 1 single mutations of it.** *(taken in CODE_STRUCTURE)* Least authoring work, but low initial diversity.
  2. P hand-written seed topologies. Most diversity, but 8 graphs to write and debug.
  3. Mixed: 2–3 hand-written seeds, the rest mutations of them.
- **Status:** OPEN

### JC-21 · retro Phase 3 · UCB1 details beyond D-05 · related: C-14, design §10 steps 4 and UCB1
- **Context:** D-05 fixed arm, visit, reward and c. C-14 added three rules: the parent within a lineage is its best-ranked survivor; never-visited lineages are picked first; a lineage with no survivors can no longer be picked (it goes extinct).
- **Options:**
  1. **As above.** *(taken)* Simple and greedy within a lineage.
  2. Sample the parent among a lineage's survivors in proportion to L1. More exploration inside a lineage.
  3. Let extinct lineages be revived from their last survivor. Counters monoculture, but adds state and complexity.
- **Status:** OPEN

### JC-22 · retro Phase 3 · Hidden tests every generation · related: C-05, C-12, C-13, design §2 Hidden Score, §9 L4
- **Options:**
  1. **Run each batch task's hidden tests every generation (extra container per task run, no model tokens).** *(taken)* This makes L4 divergence observable during the run.
  2. Hidden evaluation only at the end, on held-out tasks. Cheaper, but no divergence curve for the demo.
  3. Every k generations. A compromise.
- **Status:** OPEN

### JC-23 · retro Phase 3 · Rubric window default · related: C-18, design §12
- **Options:**
  1. **Default N = 50 generations; the MVP run (G_max = 10) is a single window.** *(taken)* The concept stays, and it is unused in the MVP.
  2. Drop N from the MVP config entirely (window = run). Less surface.
  3. A small N (e.g. 5) to exercise governance in the demo. This needs recalibration, which is Phase 2.
- **Status:** OPEN

### JC-24 · retro Phase 3 · Monoculture risk in the MVP · related: C-08, C-19, design §4, §15 "Monoculture Collapse"
- **Options:**
  1. **Accept the risk; rely on UCB1 exploration only.** *(taken)* The population may converge on one lineage within 10 generations.
  2. A cheap guard: at most 2 of the μ = 4 survivors per lineage. A few lines of code, and some diversity kept.
  3. A novelty bonus from tool-call histogram distance (an early L3). More work, and a new tunable.
- **Status:** OPEN

### JC-25 · retro Phase 4 · What "deterministic" means · related: C-28, design §7
- **Options:**
  1. **Determinism = replay from logged model outputs; re-executing against a live model is not claimed to reproduce.** *(taken)* Honest, and testable via the replay client.
  2. Also send temperature 0 and a provider seed where supported, for best-effort re-execution. Cheap to add, but provider-dependent.
  3. Claim reproducible re-execution. Not achievable with hosted models.
- **Status:** OPEN

### JC-26 · retro Phase 4 · Ledger write concurrency · related: C-25, design §8 Ordering
- **Options:**
  1. **The orchestrator is the single writer; workers hand over transitions.** *(taken)* Trivially consistent Lamport clocks.
  2. Workers append their own branches inside SQLite transactions with a shared clock row. More parallel, but the write rate is far too low to need it.
- **Status:** OPEN (low stakes)

### JC-27 · retro Phase 5 · No Agent Spec freezing in the MVP · related: C-36, design §13
- **Context:** with all n tasks passing, the exact one-sided 95% lower bound is 0.05^(1/n). Reaching 0.95 needs n ≥ 59 held-out tasks *per distribution*. The MVP has about 10 held-out tasks in total.
- **Options:**
  1. **Freeze nothing in the MVP; report the held-out rates with Clopper–Pearson intervals.** *(taken)* Statistically honest.
  2. Freeze on the point estimate ≥ p_min. Demo-friendly, but it contradicts the design's own threshold.
  3. Grow the held-out set to about 60 tasks per distribution (about 120 tasks). Freezing becomes meaningful, but corpus authoring grows a lot.
- **Status:** OPEN

### JC-28 · retro Phase 5 · Which distribution the KL drift check compares (Phase 2) · related: C-34, design §10
- **Options:**
  1. **Tool-call distribution, add-one smoothed.** *(taken)* Works with any model API.
  2. Distribution of transition outcomes (graph labels). Captures routing changes as well.
  3. Token-level output distributions. Needs logprobs, which not every provider exposes.
- **Status:** OPEN (Phase 2)

### JC-29 · retro Phase 5 · Prompt-injection defense depth · related: C-38, design §15, CODE_STRUCTURE §5.3
- **Context:** in the MVP the repos are the team's own corpus, so injected content is unlikely. The risk grows when external repos are used.
- **Options:**
  1. **Delimit tool output as data, and keep tools scoped (no network, editable paths only).** *(taken)* Containment comes from the sandbox, not from detection.
  2. Also screen tool output with a classifier or LLM check. Adds cost and false positives.
  3. Escape or strip instruction-like text from tool output. Brittle, and it can damage code content.
- **Status:** OPEN

### JC-30 · retro Phase 3 · When UCB1 rewards are credited · related: C-14, design §10 UCB1, CODE_STRUCTURE §5.2
- **Options:**
  1. **A child's reward is credited when it is evaluated, in the next generation; parent picks in generation g use only rewards credited so far.** *(taken)* This follows the loop order (children are created after evaluation).
  2. Evaluate children right away (an extra evaluation pass per generation) and credit at once. Fresher rewards, but about 1.5× the evaluation cost.
  3. Use a proxy reward at creation time (e.g. the parent's L1). Cheap, but it is not the child's own evidence.
- **Status:** OPEN

### JC-31 · retro Phase 3 · Which trace guides the mutation · related: C-14, design §10 Mutation, CODE_STRUCTURE §5.5
- **Context:** the design says "failing public-test traces" (plural). The code uses one run.
- **Options:**
  1. **The parent's worst public run of this generation (lowest pass_rate); if all passed, its most expensive run. The attribution cites that one block.** *(taken)* The prompt stays small and attribution is unambiguous.
  2. Up to 3 failing runs, within a prompt token cap. More signal, larger prompts, and multiple citations.
  3. Rotate through failing runs across generations. More diverse, but more state.
- **Status:** OPEN

### JC-32 · retro Phase 5 · Defense against causal overfitting · related: C-35, design §15 "Causal Overfitting"
- **Context:** the defense is that a child is re-evaluated on a fresh K = 10 batch. The design itself calls that filter noisy.
- **Options:**
  1. **A fresh batch each generation is the only defense in the MVP.** *(taken)* No extra cost.
  2. Also re-run the motivating failing task for the child and log whether it now passes. Cheap, but it checks only the targeted failure.
  3. Replicate each child's evaluation on 2 batches. Halves the noise and doubles the cost.
- **Status:** OPEN

---
## Prototype judgement calls (2026-10-31, /bulldog prototype run)

### JC-33 · Prototype · Sandbox without Docker · related: design §14, CODE_STRUCTURE §5.6
- **Context:** Docker is not installed and the freeze forbids installing anything outside APEX. *(2026-11-02: Docker is now installed on this host; see JC-41.)*
- **Options:**
  1. **Subprocess in a temp-dir copy with timeout, `resource` rlimits, scrubbed env, `unshare -rn` when it works unprivileged.** *(taken)* This is not a security boundary. It is acceptable because the fake model only emits reference patches or no-op patches.
  2. Install rootless Docker and follow §14. Real isolation, but it needs system setup by the user.
  3. Use `bwrap`/`firejail` if present. Better isolation, but an extra host dependency.
- **Status:** OPEN

### JC-34 · Prototype · Fake model behaviour · related: design §9.1, CODE_STRUCTURE §5.3
- **Options:**
  1. **Oracle gated by skill keywords in the prompt axioms (`boundar` → off_by_one, `type` → type_error). Without the keyword, success has a low seeded probability, which rises on a retry that sees failing test output.** *(taken)* This makes selection pressure visible without a real model.
  2. A rule-based code fixer (pattern rewrites). More "honest", but much more code, and brittle.
  3. Purely random outcomes. This exercises the plumbing only and gives no evolution signal.
- **Note (Phase 3 review):** the oracle covers held-out tasks too, so a held-out "success" means *the evolved skill axioms transfer to an unseen task of the same family*. The hidden tests themselves are never shown to any model. A real model (llm_service.py) removes the oracle entirely.
- **Status:** OPEN

### JC-35 · Prototype · Stdlib-only substitutes · related: CODE_STRUCTURE §2
- **Options:**
  1. **A JCS subset (no floats; scores stored as integer ppm), `unittest`, JSON configs, and JSON Patch with add/remove/replace only.** *(taken)* Nothing to install.
  2. Install uv + pydantic/PyYAML/pytest/rfc8785 in a `.venv` inside APEX. This matches CODE_STRUCTURE, but it needs network access and a pip bootstrap.
- **Status:** OPEN

### JC-36 · Prototype · Holdout and heads location · related: JC-15, JC-16
- **Context:** this **overrides the taken options of JC-15 and JC-16** (`~/.apex/heads`, `~/.apex/holdout`) for the prototype only. It is the one named exception to JC-38.
- **Options:**
  1. **`prototype/holdout/` in the repo and `runs/<id>/heads.jsonl`.** *(taken)* The freeze covers APEX only. Isolation holds by convention: only `evaluation.py` reads the holdout.
  2. `~/.apex/holdout` and `~/.apex/heads` as in CODE_STRUCTURE. Needs /unfreeze.
- **Status:** OPEN

### JC-37 · Prototype · Smaller defaults · related: design §10
- **Options:**
  1. **P=4, μ=2, K=3, G_max=8; 8 public + 4 held-out tasks; budget and attribution as minimal stubs.** *(taken)* A run takes about 12 s. (G_max was 5 and held-out tasks ~2 in the plan. In 4 probe runs, G_max=5 evolved one skill per run and G_max=8 evolved both. 4 held-out tasks give the intervals more trials.)
  2. The design defaults (P=8, μ=4, K=10, G_max=10, ~40 tasks). Slower, and the corpus is too large to hand-write now.
- **Status:** OPEN

### JC-38 · Prototype · Open JCs · related: JC-01..JC-32
- **Options:**
  1. **The prototype follows each open JC's taken option, except JC-15/JC-16 (overridden by JC-36). For JC-02, which has no taken option yet, it follows option 1, the one CODE_STRUCTURE.md is written for: host-side interpreter, model calls from the host.** *(taken)*
  2. Wait for the morning review before coding.
- **Status:** OPEN

### JC-39 · v1.0 · Real-model adapter · related: CODE_STRUCTURE §2, JC-35
- **Context:** CODE_STRUCTURE §2 plans an `httpx`-based `openai_compat` client. pip is blocked on this host (PEP 668), and Meta serves its models through an OpenAI-style **Responses API**.
- **Options:**
  1. **`product/apex/llm_service.py` with stdlib `urllib`: POST `{base_url}/responses` with `model`, `instructions`, `input`, `max_output_tokens`, `store: false`; text from `output[].content[].output_text`, usage from `input_tokens` / `output_tokens`. HTTP 3xx, 400, 401, 403, 404 and 422 are not retried; redirects are refused so the key is never re-sent; the key is scrubbed from every error text.** *(taken)* Nothing to install.
  2. The `openai` SDK or `httpx` in a venv. Matches CODE_STRUCTURE, but adds a dependency and a bootstrap step.
- **Status:** OPEN

### JC-40 · v1.0 · Models and endpoint · related: design §6, JC-39
- **Options:**
  1. **Muse Spark (`muse-spark-1.3`) for the subagent role and a Muse Code model for mutation, both at `https://api.meta.ai/v1` (`configs/meta.json`). The key comes only from `MODEL_API_KEY`. The Muse Code ID is still a placeholder until `run.py models` lists it.** *(taken)*
  2. One model for both roles. Simpler, but loses the code-specialised model for mutation.
- **Status:** OPEN

### JC-41 · v1.0 · Real model on the subprocess sandbox · related: JC-33, design §14
- **Context:** JC-33's risk is now real: a real model writes the patches that run. On this host `unshare -rn` (no network) and `prlimit` both work (`run.py corpus-check` prints them).
- **Options:**
  1. **Keep the JC-33 subprocess sandbox for v1.0. Tasks come only from our own corpus, and the agent can edit only `src/*.py`.** *(taken)* No new moving parts during the hackathon.
  2. Docker containers with `--network=none` (Docker is now installed). Closes most of JC-33, but is a new subsystem to build and test.
- **Status:** OPEN

### JC-42 · v1.0 · Loading `.env` · related: JC-39
- **Options:**
  1. **`run.py` and `tools/live_checks.py` load `product/.env` (gitignored) only when run as commands, and never override a variable already set. Tests never load it, so the offline suite can't reach the network even with a real key on disk.** *(taken)*
  2. Require `export MODEL_API_KEY=…` in the shell. Simpler, but easy to forget, and keys end up in shell history.
- **Status:** OPEN

### JC-43 · v1.0 · Corpus size, tiers and labels · related: JC-37, design §9.1
- **Options:**
  1. **30 public + 10 held-out tasks (15 + 5 per family), each tagged `plain` / `symptom` / `indirect` by hand before any probe data. `te_latest_version` is labelled type_error although it raises no TypeError (a type mix-up gives a wrong value), so the fake model treats its trace as off-by-one. Known overlaps (`ho_te_label` ~ `te_greeting`, `ho_te_next_port` ~ `te_latest_version`) are logged in `LOGIC.md`.** *(taken)* The live probe retunes tiers and prompts (`1_11_test_plan.md` step 3).
  2. Wait for probe data before writing tasks. Blocks v1.0 on the live key.
- **Status:** OPEN

### JC-44 · v1.0 · Probe and cost bound · related: design §9.1, design §10
- **Options:**
  1. **`run.py probe` runs the baseline once on every public task and never runs held-out tasks, so a repeatable probe can't leak held-out feedback. `run.py estimate` gives a worst-case token bound (history re-sent each call, mutation retries replayed); `configs/meta.json` is sized to it (tokens_total 9.4M, reserve 1.35M) as a ceiling, to be lowered after the probe.** *(taken)*
  2. Size the budget from a guess of real use. Cheaper ceiling, but a generation that runs over it partway through is discarded.
- **Status:** OPEN

### JC-45 · v1.0 · Smoke-only build, tests after · related: JC-38
- **Options:**
  1. **Build v1.0 with smoke checks only (suite stays green, corpus-check, each command runs once); every deeper test, all live checks and the whole-code review run afterwards from `1_11_test_plan.md`.** *(taken)* The user's choice for the hackathon day (2026-11-01), a one-off.
  2. Test-first for every new behaviour, as the working rules say by default.
- **Status:** OPEN
