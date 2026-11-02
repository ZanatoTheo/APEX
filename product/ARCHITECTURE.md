# APEX v1.0 — architecture map (`product/`)

What each part of `product/` does and where it lives, drawn like the design §5 diagram (`../design.md`). Map 0 is the
whole system; Maps 1–10 zoom into one component each and list **every** constant, class, method and function in it;
Maps 11–14 cover the stored data, the commands, the tests and the known gaps.

How to read a map:
- A **box** is a component, a file, or a group of related things in one file.
- A **leaf** is one line: `├─ name    file:line    what it does`. `.name()` is a method of the class above it;
  `name() (inner)` is a function defined inside the one above it.
- A **dashed box** (`┄`) is in design §5 but not built in `product/`.
- Paths are relative to `product/`. Line numbers match the working tree of 2026-11-02 (not committed yet; repo HEAD
  `696abbc`). If a number is off, search the file for the name.
- This map says **what** things do. **How** they work is in the code, `../LOGIC.md` (traces) and `README.md` (usage);
  **why** is in `../JUDGEMENT_CALLS.md` (JC-N).

## Map 0 — the system (design §5, as built)

The design §5 diagram, box for box, with the files that build each component. Dashed boxes are in the design but not in `product/`. Arrows say what passes between components. Every component writes records (blobs) to the ledger; the Orchestrator also writes all its blocks.

```
                                        ┌──────────────────────────────────┐              ┌──────────────────────────┐
                                        │         Operator Console         │              │  Support (used by all)   │
                                        │     run.py · apex/report.py      │              │      apex/config.py      │
                                        │  apex/stats.py · apex/costs.py   │              │     apex/envfile.py      │
                                        │       tools/live_checks.py       │              │ configs/ · seeds/ · .env │
                                        └─────────────────┬────────────────┘              └──────────────────────────┘
                                                          │
                                                          │ run / probe
                                                          ▼
┌────────────────────────┐              ┌──────────────────────────────────┐              ┌──────────────────────────┐
│      Task Ingress      │              │        Swarm Orchestrator        │              │      Meta Muse Code      │
│     apex/corpus.py     │   K tasks    │        apex/evolution.py         │   prompt     │     role "mutation"      │
│  tools/make_corpus.py  ├─────────────►│   (run loop · selection · UCB1   │◄────────────►│     apex/models.py ·     │
│   corpus/ · holdout/   │  per gen.    │           · mutation)            │ 1-unit edit  │ llm_service · fake_model │
└────────────────────────┘              └─────────────────┬────────────────┘              └──────────────────────────┘
                                                          │
                                                          │ each agent × task
                                                          ▼
┌────────────────────────┐              ┌──────────────────────────────────┐              ┌┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┐
│   Decision Ledger +    │              │        Evaluation Engine         │              ┆   Agent Spec Registry    ┆
│ Causal Attribution Log │   results    │        apex/evaluation.py        │   frozen     ┆       [not built]        ┆
│     apex/ledger.py     │◄─────────────┤   (public / hidden / held-out)   ├╌╌╌╌╌╌╌╌╌╌╌╌╌►┆                          ┆
│   apex/canonical.py    │   (blobs)    │                                  │    specs     ┆                          ┆
└────────────────────────┘              └─────────────────┬────────────────┘              └┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┘
                                                          │
                                                          │ run_agent
                                                          ▼
┌┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┐              ┌──────────────────────────────────┐              ┌──────────────────────────┐
┆       SAM 3.1 +        ┆              │          Subagents A..N          │              │     Meta Muse Spark      │
┆     Signal Watcher     ┆   signals    │ apex/agent.py · apex/prompts.py  │   prompt     │     role "subagent"      │
┆      [not built]       ├╌╌╌╌╌╌╌╌╌╌╌╌╌►│       seeds/baseline.json        │◄────────────►│     apex/models.py ·     │
┆                        ┆              │                                  │  1 action    │ llm_service · fake_model │
└┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┘              └─────────────────┬────────────────┘              └──────────────────────────┘
                                                          │
                                                          │ read_file · write_patch · run_tests
                                                          ▼
                                        ┌──────────────────────────────────┐              ┌┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┐
                                        │           Sandbox Pool           │              ┆      Muse Spark as       ┆
                                        │         apex/sandbox.py          │              ┆     causal guidance      ┆
                                        │        apex/testrunner.py        │              ┆       [not built]        ┆
                                        │    (also used by Evaluation)     │              ┆                          ┆
                                        └──────────────────────────────────┘              └┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┘
```

| Design §5 component | What it is in v1.0 | Files | Map |
|---|---|---|---|
| Operator Console | the command line and the run report; no rubric governance | `run.py`, `apex/report.py`, `apex/stats.py`, `apex/costs.py`, `tools/live_checks.py` | 1 |
| Task Ingress | the task corpus: loading, hashing, sampling, and the generator that writes it | `apex/corpus.py`, `tools/make_corpus.py`, `corpus/`, `holdout/`, `oracle/` | 2 |
| Swarm Orchestrator | the evolution loop: generations, selection, UCB1 parent choice | `apex/evolution.py` | 3 |
| Subagents | agents as data (graph + axioms) and the interpreter that runs them | `apex/agent.py`, `apex/prompts.py`, `seeds/baseline.json` | 4 |
| Meta Muse Spark / Muse Code | model access by role: `subagent` (Muse Spark) and `mutation` (Muse Code), real or fake | `apex/models.py`, `apex/llm_service.py`, `apex/fake_model.py` | 5 |
| (Muse Code's job) | turning a model proposal into one valid edit of one agent | `apex/evolution.py`, `apex/prompts.py` | 6 |
| Sandbox Pool | temporary task copies, the three tools, and the test process (subprocess, not Docker) | `apex/sandbox.py`, `apex/testrunner.py` | 7 |
| Decision Ledger + Causal Attribution Log | the hash-linked record of a run, its blob stores, and its verifier | `apex/ledger.py`, `apex/canonical.py` | 8 |
| Evaluation Engine | scoring task runs on public tests, hidden tests and held-out tasks | `apex/evaluation.py` | 9 |
| (not in §5) Support | settings, `.env`, the seed agent | `apex/config.py`, `apex/envfile.py`, `configs/`, `seeds/` | 10 |
| SAM 3.1, Signal Watcher, Agent Spec Registry, Muse Spark causal guidance | not built (design Phase 2–3) | — | — |

## Map 1 — Operator Console

What the operator types and reads: the CLI, the report, run statistics, the cost estimate, the live-check steps.

```
                                     ┌───────────────────────────────────────────┐
                                     │              OPERATOR CONSOLE             │
                                     │  run.py · apex/report.py · apex/stats.py  │
                                     │    apex/costs.py · tools/live_checks.py   │
                                     └─────────────────────┬─────────────────────┘
                                                           │
           ┌───────────────────────┬───────────────────────┼───────────────────────┬───────────────────────┐
           ▼                       ▼                       ▼                       ▼                       ▼
┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐
│        CLI         │  │     run report     │  │   run statistics   │  │     cost bound     │  │    live checks     │
│       run.py       │  │     report.py      │  │      stats.py      │  │      costs.py      │  │   live_checks.py   │
└────────────────────┘  └────────────────────┘  └────────────────────┘  └────────────────────┘  └────────────────────┘

▼ CLI · run.py
├─ ROOT                run.py:11                the product/ folder; base of the default paths
├─ WORK_ROOT           run.py:17                temp folder (.tmp/work) for corpus-check workspaces
├─ GENESIS_ACTIONS     run.py:18                the six records every genesis block must hold; checked by verify
├─ cmd_run()           run.py:21                `run`: evolves agents into runs/<id>/, verifies the ledger, writes
│                                               report.md
├─ _execute()          run.py:36                shared by run and probe: runs the loop, verifies, writes report.md,
│                                               prints the outcome; frees the run id after a start-up failure
├─ cmd_probe()         run.py:62                `probe`: one agent once on every public task, then a per-task table;
│                                               never runs held-out tasks
├─ cmd_verify()        run.py:104               `verify`: prints OK or the list of ledger problems
├─ cmd_report()        run.py:115               `report`: rebuilds report.md for a finished run
├─ cmd_corpus_check()  run.py:124               `corpus-check`: shows each task's bug fails and its reference fix
│                                               passes public and hidden tests; shows sandbox isolation status
├─ cmd_models()        run.py:152               `models`: lists the model IDs the endpoint offers and whether the
│                                               pinned IDs are among them
├─ cmd_estimate()      run.py:173               `estimate`: prints the worst-case token use of a config
├─ cmd_stats()         run.py:187               `stats`: prints statistics of a run from its public record
└─ main()              run.py:219               reads the command line and calls the matching cmd_*

▼ run report · report.py
├─ _pct()              apex/report.py:10        formats a ppm value as a percent
├─ _skills()           apex/report.py:14        names an agent's skills (boundary, types, verify-loop) for the report
├─ build()             apex/report.py:22        the text of report.md: generations, final survivors, held-out rates
│                                               with 95 % intervals, published heads, verify problems
└─ write()             apex/report.py:83        writes report.md into the run folder

▼ run statistics · stats.py   — reads the public record only
├─ StatsError          apex/stats.py:15         the ledger is not in the shape the engine writes
├─ _blocks()           apex/stats.py:19         all blocks of one kind, read-only
├─ task_rows()         apex/stats.py:29         one row per task run: outcome, steps, parse errors, tokens, public
│                                               tests, L0 failures
├─ run_summary()       apex/stats.py:49         run totals: passes, outcomes, tokens per generation, mutation
│                                               proposals and acceptance
├─ run_tiers()         apex/stats.py:77         task id → difficulty tier, or '?' if the task changed since the run
├─ _pct()              apex/stats.py:94         formats a fraction as a percent
├─ format_rows()       apex/stats.py:98         the per-task table as text
└─ format_summary()    apex/stats.py:114        the run totals as text

▼ cost bound · costs.py
├─ PROMPT_TOKENS_EST   apex/costs.py:7          assumed prompt size of one model call
├─ estimate()          apex/costs.py:10         worst-case token use of a run, from the config and the held-out task
│                                               count; no model call
└─ format_estimate()   apex/costs.py:51         that estimate as text, with whether the budget fits

▼ live checks · live_checks.py
├─ ROOT                tools/live_checks.py:21  the product/ folder; the steps run from there
├─ STEPS               tools/live_checks.py:26  the six steps, in test-plan order
├─ NEEDS_KEY           tools/live_checks.py:27  the steps that call the real API
├─ PLACEHOLDERS        tools/live_checks.py:28  key values that count as no key (empty, 'banana')
├─ key_problem()       tools/live_checks.py:31  says what is wrong with MODEL_API_KEY, or None
├─ plan()              tools/live_checks.py:37  the commands (and extra environment) one step runs
└─ main()              tools/live_checks.py:57  runs one step's commands; refuses key steps without a real key
```

## Map 2 — Task Ingress

Where tasks come from: the loader, the generator, the folders it writes, and the 40 tasks.

```
                                      ┌─────────────────────────────────────────┐
                                      │               TASK INGRESS              │
                                      │  apex/corpus.py · tools/make_corpus.py  │
                                      │       corpus/ · holdout/ · oracle/      │
                                      └────────────────────┬────────────────────┘
                                                           │
           ┌───────────────────────┬───────────────────────┼───────────────────────┬───────────────────────┐
           ▼                       ▼                       ▼                       ▼                       ▼
┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐
│    task loader     │  │  corpus generator  │  │      folders       │  │  30 public tasks   │  │ 10 held-out tasks  │
│     corpus.py      │  │   make_corpus.py   │  │  corpus/ holdout/  │  │   corpus/public/   │  │   holdout/tasks/   │
└────────────────────┘  └────────────────────┘  └────────────────────┘  └────────────────────┘  └────────────────────┘

▼ task loader · corpus.py   — never opens holdout/
├─ TASK_KEYS             apex/corpus.py:12         keys every task.json must have
├─ OPTIONAL_KEYS         apex/corpus.py:13         keys a task.json may have (difficulty)
├─ DIFFICULTIES          apex/corpus.py:18         the tiers: plain, symptom, indirect
├─ CorpusError           apex/corpus.py:21         a task folder or task.json is missing or malformed
├─ Task                  apex/corpus.py:26         one task: id, distribution (bug family), prompt, editable_paths,
│  │                                               test_command, root folder, difficulty
│  ├─ .repo_dir          apex/corpus.py:36         the task's repo/ folder (the code to fix)
│  ├─ .tests_dir         apex/corpus.py:40         the task's public tests/ folder
│  └─ .editable_files()  apex/corpus.py:43         the repo files the agent may edit
├─ load_task()           apex/corpus.py:48         one Task from a task folder
├─ load_tasks()          apex/corpus.py:73         every Task in a folder
├─ load_public()         apex/corpus.py:80         the public tasks (corpus/public/)
├─ dir_hashes()          apex/corpus.py:84         path → sha256 of every file under a folder
├─ manifest()            apex/corpus.py:91         the public task manifest recorded in genesis
└─ sample()              apex/corpus.py:96         one generation's batch of K tasks

▼ corpus generator · make_corpus.py
├─ ROOT                  tools/make_corpus.py:22   the product/ folder it writes into
├─ TEST_COMMAND          tools/make_corpus.py:23   the test command written into every task.json
├─ T()                   tools/make_corpus.py:26   one task's source data: id, family, held-out or not, module,
│                                                  function, prompt, buggy and fixed code, public and hidden test
│                                                  cases, tier
├─ TASKS                 tools/make_corpus.py:31   the 40 tasks' source data
├─ test_file()           tools/make_corpus.py:866  the text of one unittest file
├─ src()                 tools/make_corpus.py:874  a code snippet without its indentation
├─ write()               tools/make_corpus.py:878  writes one file, creating its folders
└─ main()                tools/make_corpus.py:883  rebuilds corpus/public/, holdout/ and oracle/ from TASKS

▼ folders · corpus/ holdout/
├─ task.json             corpus/public/<id>/       id, distribution, prompt, editable_paths, test_command, difficulty
├─ repo/src/<m>.py       corpus/public/<id>/       the buggy module the agent edits
├─ tests/                corpus/public/<id>/       3 public tests (the agent sees and runs them)
├─ hidden_tests/<id>/    holdout/                  2 hidden tests per public task (evaluator only)
├─ tasks/<id>/           holdout/                  the 10 held-out tasks, each with task.json, repo/, tests/,
│                                                  hidden_tests/
├─ <id>.diff             oracle/                   reference fix per task (fake model and corpus-check only)
└─ index.json            oracle/                   task id → bug family (the fake model's skill check)

▼ 30 public tasks · corpus/public/   — family · tier
├─ obo_count_in_range    src/ranges.py             off_by_one · plain
├─ obo_count_increases   src/trend.py              off_by_one · indirect
├─ obo_countdown         src/countdown.py          off_by_one · symptom
├─ obo_first_half        src/halves.py             off_by_one · symptom
├─ obo_in_bounds         src/bounds.py             off_by_one · symptom
├─ obo_inclusive_range   src/steps.py              off_by_one · plain
├─ obo_last_n            src/tail.py               off_by_one · plain
├─ obo_last_words        src/words.py              off_by_one · indirect
├─ obo_line_number       src/textpos.py            off_by_one · indirect
├─ obo_middle            src/middle.py             off_by_one · symptom
├─ obo_pad_left          src/pad.py                off_by_one · plain
├─ obo_page_count        src/paging.py             off_by_one · plain
├─ obo_page_items        src/pager.py              off_by_one · indirect
├─ obo_up_to             src/upto.py               off_by_one · plain
├─ obo_window_sum        src/window.py             off_by_one · plain
├─ te_add_minutes        src/clock.py              type_error · symptom
├─ te_count_above_mean   src/meanline.py           type_error · indirect
├─ te_digit_count        src/digits.py             type_error · plain
├─ te_full_name          src/names.py              type_error · symptom
├─ te_greeting           src/greet.py              type_error · plain
├─ te_join_ids           src/ids.py                type_error · plain
├─ te_latest_version     src/versions.py           type_error · indirect
├─ te_longest_name       src/cleaning.py           type_error · indirect
├─ te_mean_csv           src/stats.py              type_error · plain
├─ te_merge_tags         src/tags.py               type_error · symptom
├─ te_minutes            src/timeconv.py           type_error · plain
├─ te_over_limit         src/limits.py             type_error · symptom
├─ te_shout              src/shout.py              type_error · plain
├─ te_total_price        src/prices.py             type_error · plain
└─ te_url                src/urls.py               type_error · indirect

▼ 10 held-out tasks · holdout/tasks/   — family · tier
├─ ho_obo_bar            src/bar.py                off_by_one · symptom
├─ ho_obo_chunk          src/chunks.py             off_by_one · plain
├─ ho_obo_every_nth      src/every.py              off_by_one · plain
├─ ho_obo_last_field     src/fields.py             off_by_one · indirect
├─ ho_obo_nth_from_end   src/nth.py                off_by_one · plain
├─ ho_te_count_unique    src/rows.py               type_error · plain
├─ ho_te_elapsed         src/elapsed.py            type_error · indirect
├─ ho_te_format_all      src/formatting.py         type_error · symptom
├─ ho_te_label           src/labels.py             type_error · plain
└─ ho_te_next_port       src/ports.py              type_error · plain
```

## Map 3 — Swarm Orchestrator

The evolution loop that drives a run: generations, selection and the choice of parents.

```
                                               ┌──────────────────────┐
                                               │  SWARM ORCHESTRATOR  │
                                               │  apex/evolution.py   │
                                               └───────────┬──────────┘
                                                           │
                                           ┌───────────────┴───────────────┐
                                           ▼                               ▼
                            ┌────────────────────────────┐  ┌────────────────────────────┐
                            │          the run           │  │       parent choice        │
                            │        evolution.py        │  │        evolution.py        │
                            └────────────────────────────┘  └────────────────────────────┘

▼ the run · evolution.py
├─ run()                   apex/evolution.py:240  one whole run into a run folder; returns the summary; heldout=False
│                                                 skips the held-out stage (probe)
├─ _run()                  apex/evolution.py:251  the run itself: genesis, generation 0, every generation (batch, task
│  │                                              runs, selection, children, ledger records), held-out stage,
│  │                                              summary.json
│  └─ new_id() (inner)     apex/evolution.py:275  the next agent id, g<generation>-a<number>
└─ _evaluate_population()  apex/evolution.py:227  every agent on every task of the batch, in parallel; returns public
                                                  results and hidden hashes per agent

▼ parent choice · evolution.py
└─ UCB1                    apex/evolution.py:113  picks which lineages get children, balancing past reward and trying
   │                                              less-used lineages
   ├─ .__init__()          apex/evolution.py:117  starts with no visits and no reward
   ├─ .credit()            apex/evolution.py:122  records one child's reward for its lineage
   ├─ .score()             apex/evolution.py:126  a lineage's current UCB1 value
   └─ .pick()              apex/evolution.py:134  the lineages for the next k children
```

## Map 4 — Subagents

What an agent is (graph + axioms), the interpreter that runs it, and the prompts it sees.

```
                                         ┌───────────────────────────────────┐
                                         │           SUBAGENTS A..N          │
                                         │  apex/agent.py · apex/prompts.py  │
                                         │        seeds/baseline.json        │
                                         └─────────────────┬─────────────────┘
                                                           │
              ┌─────────────────────────────┬──────────────┴──────────────┬─────────────────────────────┐
              ▼                             ▼                             ▼                             ▼
┌──────────────────────────┐  ┌──────────────────────────┐  ┌──────────────────────────┐  ┌──────────────────────────┐
│       agent rules        │  │       agent + run        │  │      agent prompts       │  │      baseline agent      │
│         agent.py         │  │         agent.py         │  │        prompts.py        │  │      baseline.json       │
└──────────────────────────┘  └──────────────────────────┘  └──────────────────────────┘  └──────────────────────────┘

▼ agent rules · agent.py
├─ TOOL_OUTCOMES              apex/agent.py:12     each tool's outcome labels (read_file ok|error, write_patch
│                                                  applied|rejected, run_tests pass|fail|timeout)
├─ PREDICATES                 apex/agent.py:14     the check-node predicates (has_patch)
├─ PREDICATE_OUTCOMES         apex/agent.py:15     each predicate's outcome labels
├─ MAX_STEPS_CAP              apex/agent.py:16     the highest max_steps a graph may set (50)
├─ GraphError                 apex/agent.py:19     a graph or axiom list is invalid
├─ validate_axioms()          apex/agent.py:23     rejects an invalid axiom list
└─ validate_graph()           apex/agent.py:31     rejects an invalid graph

▼ agent + run · agent.py
├─ Agent                      apex/agent.py:92     one agent: agent_id, lineage_id, parent_agent_id, generation,
│  │                                               graph, axioms, branch_id, status
│  ├─ .state_machine_version  apex/agent.py:103    short hash naming this graph + axioms
│  └─ .record()               apex/agent.py:106    the agent as a ledger record
├─ RunResult                  apex/agent.py:114    one task run: outcome, steps, tokens, latency, final patch,
│                                                  transitions, violations, infra error, last test output hash
├─ KEEP_RECENT                apex/agent.py:128    how many recent messages stay in full in the history
├─ OLD_OUTPUT_CHARS           apex/agent.py:129    how long older tool outputs may stay
├─ _compact()                 apex/agent.py:132    a shortened copy of the message history
└─ run_agent()                apex/agent.py:143    runs one agent on one task in a workspace; returns a RunResult and
   │                                               records every step as a blob
   └─ record() (inner)        apex/agent.py:153    adds one step to the run's transition list

▼ agent prompts · prompts.py
├─ AXIOMS_HEADER              apex/prompts.py:9    heading of the axioms section of the system prompt
├─ ACTIONS_HEADER             apex/prompts.py:10   heading of the actions section of the system prompt
├─ TOOL_DOCS                  apex/prompts.py:12   args and one-line help per tool, shown to the model
├─ ParseError                 apex/prompts.py:23   a model reply has no usable JSON action or proposal
├─ describe_outcome()         apex/prompts.py:29   one menu line for an action the model may choose
├─ subagent_system()          apex/prompts.py:39   the system prompt for one llm node: axioms + action menu
├─ task_message()             apex/prompts.py:60   the task message: prompt, editable files, test command
├─ tool_output()              apex/prompts.py:70   a tool result wrapped in <tool_output> tags, made safe
├─ _json_candidates()         apex/prompts.py:76   possible JSON objects inside a reply
├─ extract_json_object()      apex/prompts.py:90   the first JSON object in a reply (with a given key)
└─ parse_action()             apex/prompts.py:106  the action label and args from a subagent reply

▼ baseline agent · baseline.json
├─ plan                       seeds/baseline.json  llm node: chooses read_file, write_patch or give_up
├─ read                       seeds/baseline.json  tool node read_file; back to plan
├─ patch                      seeds/baseline.json  tool node write_patch; applied → done, rejected → plan
├─ done                       seeds/baseline.json  terminal node
└─ axioms                     seeds/baseline.json  3 starting principles (read first, smallest change, never edit
                                                   tests)
```

## Map 5 — Meta Muse Spark / Muse Code (model access)

Where the code reaches a model: one client for both roles, the real Meta adapter, and the offline fake.

```
                            ┌─────────────────────────────────────────────────────────────┐
                            │                         MODEL ACCESS                        │
                            │    role subagent = Muse Spark · role mutation = Muse Code   │
                            │  apex/models.py · apex/llm_service.py · apex/fake_model.py  │
                            └──────────────────────────────┬──────────────────────────────┘
                                                           │
                           ┌───────────────────────────────┼───────────────────────────────┐
                           ▼                               ▼                               ▼
            ┌────────────────────────────┐  ┌────────────────────────────┐  ┌────────────────────────────┐
            │      client + budget       │  │        Meta adapter        │  │       offline model        │
            │         models.py          │  │       llm_service.py       │  │       fake_model.py        │
            └────────────────────────────┘  └────────────────────────────┘  └────────────────────────────┘

▼ client + budget · models.py
├─ ROLES                   apex/models.py:27        the two roles: subagent, mutation
├─ ModelError              apex/models.py:30        a model call failed (infrastructure, never the agent's fault)
├─ BudgetExceeded          apex/models.py:34        a call would go over the run's token budget
├─ LLMServiceMissing       apex/models.py:38        the real service can't start (missing file or unset model ID)
├─ Completion              apex/models.py:43        one model reply: text, model_id, token counts, record hash
│  └─ .tokens              apex/models.py:51        input + output tokens
├─ Budget                  apex/models.py:55        the run-wide token cap, with a reserve kept for the held-out stage
│  ├─ .__init__()          apex/models.py:58        sets the cap and the reserve
│  ├─ .available           apex/models.py:67        tokens still free right now
│  ├─ .reserve()           apex/models.py:71        holds a call's worst case before it starts
│  └─ .settle()            apex/models.py:79        swaps the hold for the real usage
├─ load_service()          apex/models.py:85        the service the config asks for: FakeModel or LLMService
├─ _check_response()       apex/models.py:105       rejects a reply that doesn't match the contract
└─ ModelClient             apex/models.py:117       the one way to call a model: pin check, retries, budget, every
   │                                                call recorded
   ├─ .__init__()          apex/models.py:120       binds a service, config, blob store and budget
   └─ .complete()          apex/models.py:127       one model call for a role; returns a Completion

▼ Meta adapter · llm_service.py
├─ API_KEY_ENV             apex/llm_service.py:20   the key's environment variable: MODEL_API_KEY
├─ NON_RETRYABLE           apex/llm_service.py:21   HTTP codes not worth retrying
├─ _ERROR_BODY_LIMIT       apex/llm_service.py:22   how much of an error reply is read
├─ _MAX_BODY               apex/llm_service.py:23   largest reply accepted
├─ _CHUNK                  apex/llm_service.py:24   read size for reply bodies
├─ LLMServiceError         apex/llm_service.py:27   a failed call, marked retryable or not
│  └─ .__init__()          apex/llm_service.py:30   sets the message and retryable flag
├─ _NoRedirect             apex/llm_service.py:35   refuses HTTP redirects so the key never leaves base_url
│  └─ .redirect_request()  apex/llm_service.py:38   returns no new request
└─ LLMService              apex/llm_service.py:42   Meta's Responses API (api.meta.ai/v1) over stdlib HTTP
   ├─ .__init__()          apex/llm_service.py:43   reads the key and the endpoint settings
   ├─ .complete()          apex/llm_service.py:55   one model call; returns text, model_id, usage
   ├─ .list_models()       apex/llm_service.py:58   the model IDs the key can use
   ├─ ._request_body()     apex/llm_service.py:67   the Responses API request for a call
   ├─ ._request()          apex/llm_service.py:78   one HTTP request; returns the JSON reply
   ├─ ._read_body()        apex/llm_service.py:107  a reply body, within the deadline and size cap
   ├─ ._error_message()    apex/llm_service.py:122  a short message from an HTTP error reply
   ├─ ._clean()            apex/llm_service.py:140  a text with the key removed
   └─ ._parse()            apex/llm_service.py:147  the contract dict from a Responses API reply

▼ offline model · fake_model.py   — deterministic stand-in (JC-34)
├─ SKILL_KEYWORDS          apex/fake_model.py:19    the word per bug family the fake looks for in the axioms
├─ SKILL_AXIOMS            apex/fake_model.py:20    the axiom it proposes per bug family
├─ NOISE_AXIOMS            apex/fake_model.py:26    general axioms it sometimes proposes
├─ P_SKILLED               apex/fake_model.py:31    chance of the right fix with the right axiom
├─ P_UNSKILLED             apex/fake_model.py:31    chance of the right fix without it
├─ P_RETRY_AFTER_FAIL      apex/fake_model.py:31    chance of the right fix after failing tests were seen
├─ MAX_PATCH_ATTEMPTS      apex/fake_model.py:32    patches it tries per task run
├─ TOOL_OUTPUT             apex/fake_model.py:33    pattern that finds tool results in a prompt
└─ FakeModel               apex/fake_model.py:36    plays both roles without a network
   ├─ .__init__()          apex/fake_model.py:37    loads the seed and the oracle index
   ├─ .complete()          apex/fake_model.py:43    one reply for a role, with estimated usage
   ├─ ._rng()              apex/fake_model.py:49    a random generator fixed by seed and inputs
   ├─ ._wrap()             apex/fake_model.py:54    a JSON reply in one of several text styles
   ├─ ._subagent()         apex/fake_model.py:64    the subagent reply: read, patch, test or stop
   │  └─ act() (inner)     apex/fake_model.py:83    the reply for one chosen action
   ├─ ._mutation()         apex/fake_model.py:109   the mutation reply: a graph or axiom edit, sometimes invalid on
   │                                                purpose
   ├─ ._graph_edit()       apex/fake_model.py:129   a graph edit (verify step or step cap)
   └─ ._axiom_edit()       apex/fake_model.py:149   an axiom edit suited to the trace
      └─ add() (inner)     apex/fake_model.py:155   an add, or a replace when the list is full
```

## Map 6 — Mutation (Muse Code's job inside the orchestrator)

What makes a child: one model proposal, turned into one valid edit of the parent's graph or axioms.

```
                                       ┌───────────────────────────────────────┐
                                       │                MUTATION               │
                                       │  apex/evolution.py · apex/prompts.py  │
                                       └───────────────────┬───────────────────┘
                                                           │
                           ┌───────────────────────────────┼───────────────────────────────┐
                           ▼                               ▼                               ▼
            ┌────────────────────────────┐  ┌────────────────────────────┐  ┌────────────────────────────┐
            │         edit units         │  │       making a child       │  │      mutation prompts      │
            │        evolution.py        │  │        evolution.py        │  │         prompts.py         │
            └────────────────────────────┘  └────────────────────────────┘  └────────────────────────────┘

▼ edit units · evolution.py
├─ PatchError           apex/evolution.py:21   a proposed edit can't be applied
├─ _pointer()           apex/evolution.py:27   a JSON pointer split into its parts
├─ _index()             apex/evolution.py:33   a list index from a pointer part
├─ _walk()              apex/evolution.py:39   the part of a document a pointer leads to
├─ apply_json_patch()   apex/evolution.py:50   a graph with JSON Patch add/remove/replace applied (new copy)
└─ apply_axiom_edit()   apex/evolution.py:84   an axiom list with add/replace/remove applied (new copy)

▼ making a child · evolution.py
├─ pick_trace()         apex/evolution.py:147  the parent's task run the mutation should learn from (its worst)
├─ trace_excerpt()      apex/evolution.py:154  a short text of that run for the prompt, from public blobs only
└─ make_child()         apex/evolution.py:169  one child with one edited unit, or None; plus the proposal record (with
                                               its causal attribution)

▼ mutation prompts · prompts.py
├─ MUTATION_SYSTEM      apex/prompts.py:120    the mutation model's system prompt: agent format and reply format
├─ mutation_messages()  apex/prompts.py:135    the messages for one proposal, with earlier rejected tries
└─ parse_mutation()     apex/prompts.py:156    format, operations and rationale from a mutation reply
```

## Map 7 — Sandbox Pool

Where task code runs: a temporary copy of the task, the three agent tools, and the test process. A subprocess with limits, not Docker, and not a security boundary (JC-33).

```
                                      ┌────────────────────────────────────────┐
                                      │              SANDBOX POOL              │
                                      │  apex/sandbox.py · apex/testrunner.py  │
                                      └────────────────────┬───────────────────┘
                                                           │
           ┌───────────────────────┬───────────────────────┼───────────────────────┬───────────────────────┐
           ▼                       ▼                       ▼                       ▼                       ▼
┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐
│  limits + results  │  │    patch policy    │  │    test process    │  │     workspace      │  │    test runner     │
│     sandbox.py     │  │     sandbox.py     │  │     sandbox.py     │  │     sandbox.py     │  │   testrunner.py    │
└────────────────────┘  └────────────────────┘  └────────────────────┘  └────────────────────┘  └────────────────────┘

▼ limits + results · sandbox.py
├─ RUNNER                     apex/sandbox.py:23     path of testrunner.py
├─ DENIED_NAMES               apex/sandbox.py:25     file names a patch may never touch (test config)
├─ FORBIDDEN_DIFF_LINES       apex/sandbox.py:27     diff lines that mean more than a text edit
├─ READ_CAP                   apex/sandbox.py:30     most bytes read_file returns
├─ TEST_OUTPUT_CAP            apex/sandbox.py:31     most characters of test output kept
├─ Limits                     apex/sandbox.py:35     timeout, memory and file-size caps of a test run
├─ TestRun                    apex/sandbox.py:42     one test run: passed, total, output, timed out, killed
│  └─ .pass_ppm               apex/sandbox.py:50     passed / total in ppm
└─ ToolResult                 apex/sandbox.py:55     one tool call: status label, output text, data

▼ patch policy · sandbox.py
├─ is_denied()                apex/sandbox.py:63     whether a path is a test or test-config file
├─ _header_path()             apex/sandbox.py:68     the file path from a diff header, if safe
└─ patch_problems()           apex/sandbox.py:84     the files a diff touches and every policy problem

▼ test process · sandbox.py
├─ _network_prefix()          apex/sandbox.py:119    the no-network command prefix, if this host allows it
├─ network_isolated()         apex/sandbox.py:127    whether tests run without network
├─ limits_enforced()          apex/sandbox.py:131    whether prlimit caps are available
├─ _limit_prefix()            apex/sandbox.py:135    the prlimit command prefix
├─ _env()                     apex/sandbox.py:142    the scrubbed environment for task processes
├─ _truncate()                apex/sandbox.py:148    long text cut to its head and tail
├─ _RAN                       apex/sandbox.py:155    pattern for unittest's 'Ran N tests' line
├─ _FAILED                    apex/sandbox.py:156    pattern for unittest's 'FAILED (...)' line
├─ parse_unittest()           apex/sandbox.py:159    passed/total from unittest text (tests only)
├─ _parse_result()            apex/sandbox.py:175    passed/total from the runner's trusted result line
├─ _kill_group()              apex/sandbox.py:194    kills a test process and its children
├─ run_test_command()         apex/sandbox.py:201    one test run in a folder; returns a TestRun
└─ _git_env()                 apex/sandbox.py:233    environment for git apply inside a workspace

▼ workspace · sandbox.py
└─ Workspace                  apex/sandbox.py:240    a temporary writable copy of one task, tests read-only
   ├─ .__init__()             apex/sandbox.py:243    creates the copy and snapshots it
   ├─ .for_task()             apex/sandbox.py:261    a workspace for a Task (public or other tests)
   ├─ .__enter__()            apex/sandbox.py:264    use with `with`
   ├─ .__exit__()             apex/sandbox.py:267    deletes the copy at the end of `with`
   ├─ .close()                apex/sandbox.py:270    deletes the copy
   ├─ ._set_tests_writable()  apex/sandbox.py:275    locks or unlocks the tests folder
   ├─ ._snapshot()            apex/sandbox.py:288    contents of every non-test file
   ├─ .tests_hash()           apex/sandbox.py:293    hash of the tests folder
   ├─ .tests_intact()         apex/sandbox.py:298    whether the tests are unchanged
   ├─ .exec()                 apex/sandbox.py:302    runs a tool by name
   ├─ .read_file()            apex/sandbox.py:312    tool read_file: one file's text (ok | error)
   ├─ .run_tests()            apex/sandbox.py:325    tool run_tests: test output (pass | fail | timeout)
   ├─ .write_patch()          apex/sandbox.py:337    tool write_patch: applies a diff (applied | rejected)
   └─ .diff()                 apex/sandbox.py:350    the final patch: everything changed since the start

▼ test runner · testrunner.py   — runs as its own process
└─ main()                     apex/testrunner.py:14  runs the tests in a workspace and prints one trusted result line
```

## Map 8 — Decision Ledger + Causal Attribution Log

The verifiable record of a run: hash-linked blocks, content-addressed blobs, published heads, the verifier, and the canonical JSON they all hash.

```
                                    ┌────────────────────────────────────────────┐
                                    │  DECISION LEDGER + CAUSAL ATTRIBUTION LOG  │
                                    │     apex/ledger.py · apex/canonical.py     │
                                    └──────────────────────┬─────────────────────┘
                                                           │
           ┌───────────────────────┬───────────────────────┼───────────────────────┬───────────────────────┐
           ▼                       ▼                       ▼                       ▼                       ▼
┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐
│    ledger rules    │  │      writing       │  │     verifying      │  │   canonical JSON   │  │  attribution log   │
│     ledger.py      │  │     ledger.py      │  │     ledger.py      │  │    canonical.py    │  │       (stub)       │
└────────────────────┘  └────────────────────┘  └────────────────────┘  └────────────────────┘  └────────────────────┘

▼ ledger rules · ledger.py
├─ ROOT                      apex/ledger.py:14     name of the root branch
├─ GENESIS_PARENT            apex/ledger.py:15     parent hash of the genesis block (all zeros)
├─ ROOT_KINDS                apex/ledger.py:16     block kinds that live on the root branch
├─ KINDS                     apex/ledger.py:17     all block kinds
├─ BODY_KEYS                 apex/ledger.py:18     the fields of a block
├─ HEX64                     apex/ledger.py:19     pattern of a sha256 hash
├─ SCHEMA                    apex/ledger.py:21     the SQLite tables: blocks, tips
├─ LedgerError               apex/ledger.py:29     a write would break the ledger rules
└─ utc_now()                 apex/ledger.py:33     the block timestamp

▼ writing · ledger.py
├─ BlobStore                 apex/ledger.py:37     a folder of records named by their hash
│  ├─ .__init__()            apex/ledger.py:40     opens (or creates) the folder
│  ├─ ._path()               apex/ledger.py:45     the file for a hash
│  ├─ .put()                 apex/ledger.py:48     stores a record; returns its hash
│  ├─ .get()                 apex/ledger.py:59     the record for a hash
│  ├─ .has()                 apex/ledger.py:62     whether a hash is stored
│  └─ .problems()            apex/ledger.py:65     stored files whose content doesn't match their name
└─ Ledger                    apex/ledger.py:75     one run's ledger: the only writer of blocks
   ├─ .__init__()            apex/ledger.py:76     opens ledger.sqlite, blobs/, blobs-holdout/, heads.jsonl
   ├─ .close()               apex/ledger.py:87     closes the database
   ├─ .get_block()           apex/ledger.py:91     one block by hash
   ├─ .blocks()              apex/ledger.py:97     all blocks in write order
   ├─ .tip()                 apex/ledger.py:101    a branch's current last block
   ├─ .tips()                apex/ledger.py:107    every branch's current last block
   ├─ ._insert()             apex/ledger.py:111    stores one block and moves its branch tip
   ├─ ._check_transitions()  apex/ledger.py:121    rejects records that point at no blob
   ├─ .genesis()             apex/ledger.py:130    writes the first block
   ├─ .fork()                apex/ledger.py:138    opens a new branch for an agent; returns its id
   ├─ .append()              apex/ledger.py:147    writes one block on a branch
   └─ .publish_heads()       apex/ledger.py:159    appends every branch tip to heads.jsonl

▼ verifying · ledger.py
├─ verify()                  apex/ledger.py:169    every problem in a run's ledger, blobs and heads (empty = OK);
│                                                  never writes
├─ _body_problem()           apex/ledger.py:182    what is wrong with one block's fields, if anything
├─ _verify()                 apex/ledger.py:198    the checks behind verify
├─ _is_ancestor()            apex/ledger.py:305    whether one block is on the path to another
└─ _check_heads()            apex/ledger.py:315    problems between heads.jsonl and the ledger

▼ canonical JSON · canonical.py
├─ MAX_SAFE_INT              apex/canonical.py:10  largest integer allowed
├─ CanonicalError            apex/canonical.py:13  a value can't be canonical JSON (float, bad key, ...)
├─ _str()                    apex/canonical.py:17  one string in canonical form
├─ _encode()                 apex/canonical.py:26  one value in canonical form
├─ dumps()                   apex/canonical.py:52  canonical JSON bytes of a value (what gets hashed)
├─ _no_duplicates()          apex/canonical.py:56  rejects duplicate keys while parsing
├─ _reject_constant()        apex/canonical.py:65  rejects NaN and Infinity while parsing
├─ _reject_float()           apex/canonical.py:69  rejects floats while parsing
├─ loads()                   apex/canonical.py:73  parses JSON under the same rules
├─ sha256_hex()              apex/canonical.py:88  sha256 of bytes, as hex
└─ hash_obj()                apex/canonical.py:92  sha256 of a value's canonical JSON

▼ attribution log · (stub)
└─ attribution               mutation_proposal     for each child: the ledger block and result that motivated it;
                                                   written by make_child (Map 6) into blobs/
```

## Map 9 — Evaluation Engine

What scores task runs: L0 gates, the L1 score, hidden tests, the held-out stage, and the numbers for the report. The only module that reads holdout/.

```
                                               ┌──────────────────────┐
                                               │  EVALUATION ENGINE   │
                                               │  apex/evaluation.py  │
                                               └───────────┬──────────┘
                                                           │
           ┌───────────────────────┬───────────────────────┼───────────────────────┬───────────────────────┐
           ▼                       ▼                       ▼                       ▼                       ▼
┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐
│   gates + errors   │  │   holdout reader   │  │       scores       │  │     task runs      │  │ held-out + report  │
│   evaluation.py    │  │   evaluation.py    │  │   evaluation.py    │  │   evaluation.py    │  │   evaluation.py    │
└────────────────────┘  └────────────────────┘  └────────────────────┘  └────────────────────┘  └────────────────────┘

▼ gates + errors · evaluation.py
├─ PPM                         apex/evaluation.py:18   1,000,000 = 100 %
├─ GATES                       apex/evaluation.py:20   the L0 gate list (version 1), recorded in genesis
├─ EvaluationError             apex/evaluation.py:30   a task has no hidden tests
├─ InfraError                  apex/evaluation.py:34   a task run failed for infrastructure reasons; aborts the
│                                                      generation
└─ _l0()                       apex/evaluation.py:113  the L0 gates one task run failed

▼ holdout reader · evaluation.py
├─ hidden_tests_dir()          apex/evaluation.py:40   a public task's hidden tests folder
├─ heldout_tasks()             apex/evaluation.py:48   the held-out tasks
├─ heldout_hidden_tests_dir()  apex/evaluation.py:52   a held-out task's hidden tests folder
└─ holdout_manifest_hash()     apex/evaluation.py:59   one hash of the whole holdout/ folder (for genesis)

▼ scores · evaluation.py
├─ clamp_ppm()                 apex/evaluation.py:66   a ppm value kept within 0..100 %
├─ l1_components()             apex/evaluation.py:70   the three L1 terms: pass rate, tokens, latency
├─ l1_ppm()                    apex/evaluation.py:76   the weighted L1 score
├─ TaskPublic                  apex/evaluation.py:83   one task run's public result (no hidden data)
│  └─ .pass_ppm                apex/evaluation.py:93   its public pass rate
└─ PublicResult                apex/evaluation.py:98   one agent's public result for a generation — all selection sees
   └─ .pass_ppm                apex/evaluation.py:109  its batch pass rate

▼ task runs · evaluation.py
├─ evaluate_task()             apex/evaluation.py:129  one agent on one task: its public result and the hash of its
│                                                      hidden result
├─ aggregate()                 apex/evaluation.py:163  one agent's PublicResult over a batch
├─ fitness_record()            apex/evaluation.py:178  the public fitness record (hidden fields empty)
└─ write_hidden_fitness()      apex/evaluation.py:185  the evaluator-only fitness record; returns its hash only

▼ held-out + report · evaluation.py
├─ _binom_cdf()                apex/evaluation.py:198  binomial probability helper
├─ clopper_pearson()           apex/evaluation.py:202  95 % interval for k successes out of n
│  └─ solve() (inner)          apex/evaluation.py:207  one end of the interval
├─ holdout_report()            apex/evaluation.py:220  hidden and held-out numbers for report.md
└─ evaluate_heldout()          apex/evaluation.py:243  the final survivors once on every held-out task
```

## Map 10 — Support (settings, secrets, seed)

Not a design §5 box: what every component reads to start.

```
                              ┌────────────────────────────────────────────────────────┐
                              │                        SUPPORT                         │
                              │  apex/config.py · apex/envfile.py · configs/ · seeds/  │
                              └────────────────────────────┬───────────────────────────┘
                                                           │
                           ┌───────────────────────────────┼───────────────────────────────┐
                           ▼                               ▼                               ▼
            ┌────────────────────────────┐  ┌────────────────────────────┐  ┌────────────────────────────┐
            │         run config         │  │        .env reader         │  │           files            │
            │         config.py          │  │         envfile.py         │  │      configs/ seeds/       │
            └────────────────────────────┘  └────────────────────────────┘  └────────────────────────────┘

▼ run config · config.py
├─ PROTO_ROOT        apex/config.py:13   the product/ folder; base of relative paths
├─ DEFAULTS          apex/config.py:15   every setting with its default (run, population, batch, ucb1, l1_weights_ppm,
│                                        limits, budget, mutation, models, paths, gates)
├─ ConfigError       apex/config.py:40   a config file or override is invalid
├─ _BASE_URL         apex/config.py:44   allowed model endpoints (https, or local http for tests)
├─ _merge()          apex/config.py:47   a config with overrides applied
├─ validate()        apex/config.py:63   rejects an invalid config
├─ load()            apex/config.py:87   the run config: defaults + JSON file + overrides
├─ resolve_path()    apex/config.py:103  a configured path as an absolute path
└─ config_hash()     apex/config.py:108  hash of a config (no caller yet)

▼ .env reader · envfile.py
├─ _LINE             apex/envfile.py:15  pattern of one KEY=VALUE line
├─ read()            apex/envfile.py:18  the variables in a .env file
└─ load()            apex/envfile.py:41  sets .env variables the shell hasn't set; returns their names

▼ files · configs/ seeds/
├─ meta.json         configs/            the real-model config: Muse Spark + Muse Code, bigger budget
├─ llm.example.json  configs/            template for a real-model config
├─ baseline.json     seeds/              the seed agent (Map 4)
├─ .env.example      ./                  template for .env
├─ .env              ./                  MODEL_API_KEY; read by run.py and live_checks.py only
└─ __init__.py       apex/               empty; makes apex a package
```

## Map 11 — Data: what a run stores, and where

Everything `run` and `probe` write under `runs/<id>/`. `blobs-holdout/` is evaluator-only. For records, the middle column is the block that points to them.

```
                                                 ┌──────────────────┐
                                                 │    RUN FOLDER    │
                                                 │  runs/<run-id>/  │
                                                 └─────────┬────────┘
                                                           │
              ┌─────────────────────────────┬──────────────┴──────────────┬─────────────────────────────┐
              ▼                             ▼                             ▼                             ▼
┌──────────────────────────┐  ┌──────────────────────────┐  ┌──────────────────────────┐  ┌──────────────────────────┐
│          files           │  │          blocks          │  │      public records      │  │      evaluator-only      │
│        runs/<id>/        │  │      ledger.sqlite       │  │          blobs/          │  │      blobs-holdout/      │
└──────────────────────────┘  └──────────────────────────┘  └──────────────────────────┘  └──────────────────────────┘

▼ files · runs/<id>/
├─ ledger.sqlite      runs/<id>/        the blocks (table blocks) and each branch's last block (table tips)
├─ blobs/             runs/<id>/        public records, named by hash
├─ blobs-holdout/     runs/<id>/        evaluator-only records, named by hash
├─ heads.jsonl        runs/<id>/        every branch tip, once per generation and at the end
├─ summary.json       runs/<id>/        run summary: stop reason, per-generation results, survivors, tokens
├─ report.md          runs/<id>/        the operator report
└─ work/              runs/<id>/        temporary workspaces; removed at the end

▼ blocks · ledger.sqlite
├─ genesis            branch root       the start: config, gates, task and holdout manifests, seed, seed agent
├─ agent_run          agent branch      one agent on one task: every step, the end, the public check
├─ generation_event   branch root       one generation's batch, fitness, selection, proposals and agents; or
│                                       'aborted'; or the final survivors
└─ gate_version       branch root       allowed but never written

▼ public records · blobs/
├─ config             genesis           the whole run config
├─ gate_definition    genesis           the L0 gate list
├─ public_manifest    genesis           hash of every public task file
├─ holdout_manifest   genesis           one hash of holdout/
├─ rng_seed           genesis           the run seed
├─ seed_agent         genesis           the baseline graph + axioms
├─ llm:<node>         agent_run         one model call: role, messages sent, reply
├─ tool:<tool>        agent_run         one tool call: args, status, output
├─ check:<node>       agent_run         one predicate result
├─ end                agent_run         the run's outcome, patch, steps, tokens, latency
├─ eval:public        agent_run         public test result, L0 failures, test output
├─ batch              generation_event  the generation's task ids
├─ fitness            generation_event  one agent's public fitness record
├─ selection          generation_event  ranking, survivors, statuses, UCB1 state
├─ mutation_proposal  generation_event  one proposal: scope, edit, rationale, model calls, errors, accepted,
│                                       attribution
├─ agent              generation_event  one agent record (graph + axioms + status)
├─ aborted            generation_event  why a generation was aborted
└─ final_survivors    generation_event  the agents that went to the held-out stage

▼ evaluator-only · blobs-holdout/
├─ hidden_ref         generation_event  one task run's hidden test result
├─ hidden_fitness     generation_event  one agent's fitness with hidden score and divergence
├─ heldout_run        generation_event  one survivor on one held-out task: success + trace
└─ held-out calls     (no action)       the model calls and tool results of held-out runs
```

## Map 12 — Commands

What each command does and what it writes. Details of the code behind each are in Map 1.

```
                                 ┌──────────────────────────────────────────────────┐
                                 │                     COMMANDS                     │
                                 │  python3 run.py <cmd> · python3 tools/<tool>.py  │
                                 └─────────────────────────┬────────────────────────┘
                                                           │
                           ┌───────────────────────────────┼───────────────────────────────┐
                           ▼                               ▼                               ▼
            ┌────────────────────────────┐  ┌────────────────────────────┐  ┌────────────────────────────┐
            │           run.py           │  │       live_checks.py       │  │       make_corpus.py       │
            │       no key needed*       │  │       steps in order       │  │           no key           │
            └────────────────────────────┘  └────────────────────────────┘  └────────────────────────────┘

▼ run.py · no key needed*   — *run/probe need a key with provider llm
├─ run           runs/<id>/                evolves agents, verifies the ledger, writes report.md
├─ probe         runs/probe-<t>/           one agent once on all public tasks; per-task table
├─ verify        (prints)                  OK, or the ledger problems
├─ report        report.md                 rebuilds the report of a finished run
├─ stats         (prints)                  run statistics; --tasks adds one row per task run
├─ estimate      (prints)                  worst-case token use of a config
├─ corpus-check  (prints)                  every task: bug fails, reference fix passes
└─ models        (prints)                  model IDs the endpoint offers (needs the key)

▼ live_checks.py · steps in order
├─ models        key                       the model IDs to pin in configs/meta.json
├─ contract      key                       4 real calls against the service contract
├─ probe         key                       the baseline with the real model on all public tasks
├─ estimate      no key                    the cost bound of configs/meta.json
├─ run           key                       the first real run, then verify
└─ stats         no key                    statistics of that run

▼ make_corpus.py · no key
└─ (no args)     corpus/ holdout/ oracle/  rebuilds the whole corpus from TASKS
```

## Map 13 — Tests

147 offline tests: `python3 -m unittest discover -s tests` from `product/`. Each leaf is a test class.

```
                                          ┌────────────────────────────────┐
                                          │             TESTS              │
                                          │  tests/ · 147 tests · offline  │
                                          └────────────────┬───────────────┘
                                                           │
              ┌─────────────────────────────┬──────────────┴──────────────┬─────────────────────────────┐
              ▼                             ▼                             ▼                             ▼
┌──────────────────────────┐  ┌──────────────────────────┐  ┌──────────────────────────┐  ┌──────────────────────────┐
│           core           │  │         records          │  │          models          │  │      sandbox + CLI       │
│     agent evolution      │  │  canonical ledger stats  │  │ llm_contract llm_service │  │  sandbox smoke env live  │
└──────────────────────────┘  └──────────────────────────┘  └──────────────────────────┘  └──────────────────────────┘

▼ core · agent evolution
├─ test_agent.py              9 tests
│  ├─ GraphValidationTest     tests/test_agent.py:19          graph and axiom validation
│  └─ RuntimeTest             tests/test_agent.py:51          run_agent: fixes, recorded steps, max_steps, error
│                                                             retries, token budget
└─ test_evolution.py          15 tests
   ├─ JsonPatchTest           tests/test_evolution.py:18      graph edits and their errors
   ├─ AxiomEditTest           tests/test_evolution.py:39      axiom edits and bounds
   ├─ UCB1Test                tests/test_evolution.py:51      parent choice
   ├─ BudgetTest              tests/test_evolution.py:78      in-flight calls can't eat the holdout reserve
   ├─ ScoringTest             tests/test_evolution.py:91      L1, Clopper–Pearson, no hidden field in PublicResult
   ├─ IsolationTest           tests/test_evolution.py:111     only evaluation.py reads holdout/
   └─ LoopTest                tests/test_evolution.py:127     small full runs: verify, citations, L0 stop, same seed
                                                              same start

▼ records · canonical ledger stats
├─ test_canonical.py          10 tests
│  ├─ DumpsTest               tests/test_canonical.py:7       canonical output and rejected values
│  ├─ LoadsTest               tests/test_canonical.py:32      parsing round trip and rejected input
│  └─ HashTest                tests/test_canonical.py:54      hash ignores key order
├─ test_ledger.py             17 tests
│  ├─ LedgerTestBase          tests/test_ledger.py:10         shared setup: a small ledger
│  ├─ LedgerBuildTest         tests/test_ledger.py:37         genesis, fork and append rules
│  └─ VerifyTest              tests/test_ledger.py:85         verify catches every kind of tampering
└─ test_stats.py              8 tests
   └─ StatsTest               tests/test_stats.py:17          stats rows, totals, read-only, no holdout reads,
                                                              formatting

▼ models · llm_contract llm_service
├─ test_llm_contract.py       16 tests
│  ├─ ContractMixin           tests/test_llm_contract.py:31   the contract checks shared by fake and real service
│  ├─ FakeContractTest        tests/test_llm_contract.py:67   the contract against FakeModel
│  ├─ LLMServiceContractTest  tests/test_llm_contract.py:78   the contract against the real API (skipped without
│  │                                                          APEX_LLM_CONFIG)
│  ├─ ClientRulesTest         tests/test_llm_contract.py:85   ModelClient: pin, retries, errors, budget
│  └─ ParseTest               tests/test_llm_contract.py:145  reading actions from replies; safe tool output
└─ test_llm_service.py        26 tests
   ├─ _QuietServer            tests/test_llm_service.py:29    the local stub HTTP server
   ├─ StubAPI                 tests/test_llm_service.py:36    scripted replies of the stub /responses and /models
   ├─ _StubCase               tests/test_llm_service.py:104   shared setup for stub tests
   ├─ LLMServiceTest          tests/test_llm_service.py:135   request shape, reply mapping, errors, key safety
   ├─ ListModelsTest          tests/test_llm_service.py:303   model listing
   └─ ConfigKeysTest          tests/test_llm_service.py:326   base_url and timeout settings

▼ sandbox + CLI · sandbox smoke env live
├─ test_sandbox.py            18 tests
│  ├─ PatchPolicyTest         tests/test_sandbox.py:18        what a patch may and may not touch
│  ├─ WorkspaceTest           tests/test_sandbox.py:59        tools, read-only tests, violations, timeout
│  └─ ParseTest               tests/test_sandbox.py:138       unittest text parsing, truncation
├─ test_smoke.py              13 tests
│  ├─ SmokeTest               tests/test_smoke.py:29          run, report, verify and tamper through run.py
│  ├─ ProbeTest               tests/test_smoke.py:79          probe end to end
│  └─ ModelsCommandTest       tests/test_smoke.py:128         models command; main never reads .env
├─ test_envfile.py            9 tests
│  └─ EnvFileTest             tests/test_envfile.py:11        .env parsing and the shell-wins rule
└─ test_live_checks.py        6 tests
   └─ LiveChecksTest          tests/test_live_checks.py:14    key check and the commands of each step
```

## Map 14 — Known gaps

Things a dev should know before relying on a part.

```
                                                   ┌──────────────┐
                                                   │  KNOWN GAPS  │
                                                   └───────┬──────┘
                                                           │
                           ┌───────────────────────────────┼───────────────────────────────┐
                           ▼                               ▼                               ▼
            ┌────────────────────────────┐  ┌────────────────────────────┐  ┌────────────────────────────┐
            │           unused           │  │           limits           │  │         open items         │
            │      or recorded only      │  │          of v1.0           │  │     before a real run      │
            └────────────────────────────┘  └────────────────────────────┘  └────────────────────────────┘

▼ unused · or recorded only
├─ config_hash()     apex/config.py:108    no caller; genesis stores the whole config instead
├─ parse_unittest()  apex/sandbox.py:159   used by tests only
├─ RunResult         apex/agent.py:114     its test_output_hash and violations are filled but never read
└─ gate_version      ledger.py             a block kind that is allowed but never written

▼ limits · of v1.0
├─ sandbox           sandbox.py            not a security boundary: only run our own corpus (JC-33)
├─ re-running        evolution.py          a run is not reproduced by re-running; read its ledger (clock in scores and
│                                          timestamps)
├─ token accounting  models.py             known gaps R11–R13 in ../LOGIC.md
└─ holdout + heads   holdout/ heads.jsonl  live inside the repo; keep a heads copy elsewhere (JC-36)

▼ open items · before a real run
├─ Muse Code ID      configs/meta.json     still a placeholder; a run with this config stops at start
├─ _skills()         apex/report.py:14     only recognises the fake model's axiom texts
└─ tiers             task.json             set by hand before any real-model data (JC-43)
```

---

Generated from the code on 2026-11-02: every `file:line` above was read from the source, and every definition in
`run.py`, `apex/` and `tools/` (and every test class) appears in a map.
