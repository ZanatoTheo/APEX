# APEX logic notes

Written **before** the code (user rule, 2026-11-02): the logic of each change, a trace of every test case, and how
each defined thing is used in the product. Kept out of task repos (the model reads those). One section per phase,
plus an issue log at the end (stage that caught each issue: L = writing the logic, C = checks, R = reviewer).

## Shared map: the life of one task in the product
Checked against the code on 2026-11-02 (`product/`).

1. **`T(...)` entry** in `tools/make_corpus.py`. `main()` writes:
   - `task.json`: id, distribution, prompt, editable_paths `["src/*.py"]`, test_command, difficulty;
   - `repo/src/<module>.py`: the buggy code, the only file the agent may edit;
   - `tests/test_<module>.py`: the public tests;
   - the hidden test file:
     - public task → `holdout/hidden_tests/<id>/test_<module>_hidden.py`;
     - held-out task → `holdout/tasks/<id>/hidden_tests/`;
   - `oracle/<id>.diff`: the reference fix (difflib of buggy → fixed);
   - `oracle/index.json`: `id → distribution`.
2. **Public task in a run.**
   - `corpus.load_public` (evolution.py:258) puts it in the pool. Genesis stores its file hashes
     (`public_manifest`, evolution.py:268–269).
   - Each generation, `corpus.sample(public, K, rng)` (evolution.py:299) draws **one** batch of K tasks, shared by
     every agent in that generation (jobs = population × batch, evolution.py:228).
   - The agent's first user message is `prompts.task_message(task)` (agent.py:175): id, prompt, editable files,
     editable patterns, test command. The agent never sees the tier, the hidden tests or the oracle.
   - `evaluation.evaluate_task`:
     - **eval:public** runs `tests/` on the agent's patch. Passed/total goes into a blob, which feeds public L1,
       then selection and mutation.
     - The same patch then runs on the hidden tests (evaluation.py:153). That result is stored only in
       `holdout_blobs`; the ledger gets its hash (`hidden_ref`, `hidden_fitness`).
3. **Held-out task.** Never sampled. `evaluation.heldout_tasks` (defined at evaluation.py:48, called at
   evaluation.py:248) runs it once, for the final
   survivors only, after the last generation. `run.py probe` skips it (`heldout=False`).
4. **Fake model only.**
   - `oracle/index.json` gives the task's distribution. If the agent's axioms contain a word starting with "type"
     (`SKILL_KEYWORDS`), it applies `oracle/<id>.diff` with p = 0.9; otherwise 0.1, or 0.4 after a fail
     (fake_model.py:94–97).
   - Mutation: when "TypeError" is in the failing trace, it adds the type_error axiom; otherwise the off_by_one
     axiom (fake_model.py:151).
5. **Operator tools.**
   - `run.py corpus-check` (run.py:123): buggy fails ≥ 1 public test; the oracle diff applies and passes all public
     and hidden tests.
   - `run.py probe`: shows the tier column (run.py:96) from `Task.difficulty`.

## Phase 5: type_error 4 + 2 → 15 + 5

Rule checks for every task:
- (a) buggy fails ≥ 1 public test;
- (b) fixed passes every public and hidden test;
- (c) no hidden call repeats a public call;
- (d) the prompt fits the tier (plain = error and right output; symptom = symptom only; indirect = the bug is in
  a helper);
- (e) not a near copy of another task's shape, checked against the failure-mode table below, not from memory
  (added after review: the memory-based check was wrong twice);
- (f) the prompt doesn't name the cause for symptom / indirect tasks (added after review; see R3).

Placement: new public tasks go after `te_mean_csv`, held-out after `ho_te_next_port`. Every module name is new.
Each trace below reads: call → expected · buggy result.

### 1. te_shout: public, plain, `shout.py`
- **Spec:** `shout(word, times)` returns the word in upper case, repeated `times` times, joined by single spaces.
  `times` is an int or a numeric string.
- **Code:**
  - Buggy: `return " ".join([word.upper()] * times)`. A list times a str raises TypeError.
  - Fixed: `return " ".join([word.upper()] * int(times))`.
- **Prompt:** "shout('hi', '3') raises TypeError: can't multiply sequence by non-int of type 'str'; it should return 'HI HI HI'."
- **Public tests:**
  - `test_str_times`: `shout('hi', '3')` → `'HI HI HI'` · TypeError. Shows the bug.
  - `test_int_times`: `shout('a', 2)` → `'A A'` · passes. The fix must keep int input working.
  - `test_one`: `shout('ok', '1')` → `'OK'` · TypeError.
- **Hidden tests:**
  - `test_zero`: `shout('x', '0')` → `''`. Zero repeats gives the empty string.
  - `test_int_three`: `shout('go', 3)` → `'GO GO GO'`.
- **Checks:** (a) 2 of 3 public fail; (b) traced; (c) ok; (d) states the error and the right output; (e) list × str
  is a shape no other task uses.
- **Use:**
  - **Files:** `corpus/public/te_shout/{task.json (plain), repo/src/shout.py, tests/test_shout.py}`;
    `holdout/hidden_tests/te_shout/test_shout_hidden.py`; `oracle/te_shout.diff`;
    `index.json["te_shout"] = "type_error"`.
  - **Agent:** `shout()` is the only function in the repo, and the agent edits it.
  - **Tests:** public tests score it in sampled generations; hidden tests score the same patch out of sight.
  - **Fake model:** the TypeError trace makes mutation push the type_error axiom.
  - **Probe:** tier `plain`.
  - **Scope:** `shout`, `word`, `times` exist only inside the task repo; nothing in `apex/` imports them.

### 2. te_digit_count: public, plain, `digits.py`
- **Spec:** `digit_count(n)` returns the number of decimal digits in a non-negative int.
- **Code:**
  - Buggy: `return len(n)`. TypeError: object of type 'int' has no len().
  - Fixed: `return len(str(n))`.
- **Prompt:** "digit_count(123) raises TypeError: object of type 'int' has no len(); it should return 3."
- **Public tests:**
  - `test_three`: `digit_count(123)` → `3` · TypeError.
  - `test_zero`: `digit_count(0)` → `1` · TypeError. Zero has one digit.
  - `test_five`: `digit_count(99999)` → `5` · TypeError.
- **Hidden tests:**
  - `test_ten`: `digit_count(10)` → `2`. A power-of-ten boundary.
  - `test_single`: `digit_count(7)` → `1`.
- **Checks:** (a) 3/3 fail; (b) ok; (c) ok; (d) ok; (e) `len(int)` is not used elsewhere.
- **Use:** the shared map only.

### 3. te_minutes: public, plain, `timeconv.py`
- **Spec:** `minutes(seconds)` takes `seconds` as a string such as `'125'` and returns the whole minutes (rounded
  down).
- **Code:**
  - Buggy: `return seconds // 60`. TypeError: unsupported operand type(s) for //: 'str' and 'int'.
  - Fixed: `return int(seconds) // 60`.
- **Prompt:** "minutes('125') raises TypeError: unsupported operand type(s) for //: 'str' and 'int'; it should return 2."
- **Public tests:**
  - `test_two`: `minutes('125')` → `2` · TypeError.
  - `test_under_one`: `minutes('59')` → `0` · TypeError. Rounds down.
  - `test_ten`: `minutes('600')` → `10` · TypeError.
- **Hidden tests:**
  - `test_zero`: `minutes('0')` → `0`.
  - `test_just_over`: `minutes('61')` → `1`.
- **Checks:** (a) 3/3; (b) ok; (c) ok; (d) ok; (e) str // int is new. It replaced a planned `percent()` (see
  issue L2).
- **Use:** the shared map only.

### 4. te_add_minutes: public, symptom, `clock.py`
- **Spec:** `add_minutes(clock, minutes)` adds `minutes` to `clock` (`'HH:MM'`) and returns `'HH:MM'`, wrapping at
  24 h.
- **Code:**
  - Buggy:
    - `h, m = clock.split(":")`
    - `total = (h * 60 + m + minutes) % 1440`. Here `h * 60` repeats the string, `+ m` concatenates, and
      `+ minutes` (an int) raises TypeError.
    - `return f"{total // 60:02d}:{total % 60:02d}"`
  - Fixed: `total = (int(h) * 60 + int(m) + minutes) % 1440`.
- **Prompt:** "add_minutes() crashes for every input."
- **Public tests:**
  - `test_next_hour`: `add_minutes('09:30', 45)` → `'10:15'` · TypeError. 540 + 30 + 45 = 615 = 10 h 15.
  - `test_midnight_wrap`: `add_minutes('23:50', 20)` → `'00:10'` · TypeError. 1450 mod 1440 = 10.
  - `test_zero`: `add_minutes('00:00', 0)` → `'00:00'` · TypeError.
- **Hidden tests:**
  - `test_full_hour`: `add_minutes('12:00', 60)` → `'13:00'`. 780 minutes.
  - `test_full_day`: `add_minutes('01:05', 1440)` → `'01:05'`. 1505 mod 1440 = 65.
- **Checks:** (a) 3/3; (b) traced; (c) ok; (d) symptom only; (e) a time-parsing shape, new.
- **Use:** the shared map only. The symptom prompt hides the error type, but the failing test output shows the
  TypeError, so the fake mutation still picks the type_error axiom.

### 5. te_full_name: public, symptom, `names.py`
- **Spec:** `full_name(first, middle, last)` returns the parts joined by spaces. `middle` may be None or `''`; it is
  skipped then.
- **Code:**
  - Buggy: `return " ".join([first, middle, last])`. TypeError: sequence item 1: expected str instance, NoneType
    found.
  - Fixed: `return " ".join(p for p in (first, middle, last) if p)`.
- **Prompt:** "full_name() crashes for people without a middle name."
- **Public tests:**
  - `test_no_middle`: `full_name('Ana', None, 'Lee')` → `'Ana Lee'` · TypeError.
  - `test_with_middle`: `full_name('Bo', 'C', 'Du')` → `'Bo C Du'` · passes. A real middle name must stay.
  - `test_short_names`: `full_name('X', None, 'Y')` → `'X Y'` · TypeError.
- **Hidden tests:**
  - `test_empty_middle`: `full_name('Mo', '', 'Ra')` → `'Mo Ra'`. A fix that only checks `is None` gives a double
    space and fails.
  - `test_other_middle`: `full_name('Jo', 'Q', 'Lu')` → `'Jo Q Lu'`.
- **Checks:** (a) 2/3; (b) ok; (c) ok; (d) ok; (e) None in join is new (`join_ids` is about ints, not None).
- **Use:** the shared map only.

### 6. te_over_limit: public, symptom, `limits.py`
- **Spec:** `over_limit(values, limit)` takes int values and `limit` as a numeric string from config, and returns
  the values strictly greater than the limit, in order.
- **Code:**
  - Buggy: `return [v for v in values if v > limit]`. TypeError: '>' not supported between 'int' and 'str'.
  - Fixed: `return [v for v in values if v > int(limit)]`.
- **Prompt:** "over_limit() crashes when the limit comes from the config file."
- **Public tests:**
  - `test_basic`: `over_limit([1, 5, 10], '4')` → `[5, 10]` · TypeError.
  - `test_empty`: `over_limit([], '0')` → `[]` · passes (no comparison is made).
  - `test_equal`: `over_limit([3, 3], '3')` → `[]` · TypeError. The comparison is strict.
- **Hidden tests:**
  - `test_negative`: `over_limit([-1, 0, 1], '0')` → `[1]`.
  - `test_big`: `over_limit([100], '99')` → `[100]`. A fix that compares as text gets this wrong (`'100' < '99'`).
- **Checks:** (a) 2/3; (b) ok; (c) ok; (d) ok; (e) an int/str comparison, new.
- **Use:** the shared map only.

### 7. te_merge_tags: public, symptom, `tags.py`
- **Spec:** `merge_tags(a, b)` takes `a` and `b` as sets or lists of tags, and returns every tag once, sorted.
- **Code:**
  - Buggy: `return sorted(a + b)`. TypeError for set + set and set + list.
  - Fixed: `return sorted(set(a) | set(b))`.
- **Prompt:** "merge_tags() crashes for some callers."
- **Public tests:**
  - `test_sets`: `merge_tags({'b', 'a'}, {'c'})` → `['a', 'b', 'c']` · TypeError.
  - `test_lists`: `merge_tags(['x'], ['y'])` → `['x', 'y']` · passes.
  - `test_mixed`: `merge_tags({'a'}, ['a'])` → `['a']` · TypeError.
- **Hidden tests:**
  - `test_empty`: `merge_tags(set(), set())` → `[]`.
  - `test_duplicates`: `merge_tags(['b', 'a'], ['a'])` → `['a', 'b']`. A fix that only converts sets keeps the
    duplicate (`['a', 'a', 'b']`) and fails.
- **Checks:** (a) 2/3; (b) ok; (c) ok; (d) ok; (e) a container-type mix, new.
- **Use:** the shared map only.

### 8. te_count_above_mean: public, indirect, `meanline.py`
- **Spec:**
  - `_ints(line)` returns the ints of a comma-separated line, as a list.
  - `count_above_mean(line)` counts the values strictly above their mean.
- **Code:**
  - Buggy `_ints`: `return map(int, line.split(","))`.
  - Caller: `xs = _ints(line); mean = sum(xs) / len(xs); return sum(x > mean for x in xs)`. `sum` uses up the map,
    then `len(map)` raises TypeError.
  - Fixed: `return list(map(int, line.split(",")))`.
- **Prompt:** "count_above_mean('1,2,3') raises TypeError: object of type 'map' has no len()."
- **Public tests:**
  - `test_three`: `count_above_mean('1,2,3')` → `1` (mean 2) · TypeError.
  - `test_equal`: `count_above_mean('5,5')` → `0` (equal is not above) · TypeError.
  - `test_outlier`: `count_above_mean('1,1,1,9')` → `1` (mean 3) · TypeError.
- **Hidden tests:**
  - `test_single`: `count_above_mean('10')` → `0`.
  - `test_negative`: `count_above_mean('-2,0,2,4')` → `2` (mean 1).
- **Checks:** (a) 3/3; (b) traced; (c) ok; (d) the bug is in `_ints` and the prompt names the caller; (e) map vs
  list, new.
- **Use:** the shared map, plus: `_ints` is called only by `count_above_mean`, and only inside the task repo. The
  agent has to read `meanline.py` to find it.

### 9. te_url: public, indirect, `urls.py`
- **Spec:**
  - `_query(params)` returns `k=v` pairs sorted by key, joined by `&`.
  - `url(path, params)` returns `path`, plus `?` and the query when `params` is not empty.
- **Code:**
  - Buggy `_query`: `return "&".join(k + "=" + v for k, v in sorted(params.items()))`. str + int raises TypeError.
  - Fixed: `return "&".join(f"{k}={v}" for k, v in sorted(params.items()))`.
  - Caller: `return path + ("?" + _query(params) if params else "")`.
- **Prompt:** "url() crashes when a parameter value is a number."
- **Public tests:**
  - `test_int_value`: `url('/a', {'page': 2})` → `'/a?page=2'` · TypeError.
  - `test_no_params`: `url('/b', {})` → `'/b'` · passes.
  - `test_sorted_mixed`: `url('/c', {'q': 'x', 'n': 1})` → `'/c?n=1&q=x'` · TypeError (the sorted order hits n=1
    first).
- **Hidden tests:**
  - `test_str_only`: `url('/d', {'z': 'y'})` → `'/d?z=y'`.
  - `test_zero_value`: `url('/e', {'a': 0, 'b': 10})` → `'/e?a=0&b=10'`. A 0 value must print.
- **Checks:** (a) 2/3; (b) ok; (c) ok; (d) the bug is in `_query`, and the prompt is a symptom; (e) str + int like
  `te_greeting`, but in a helper inside a generator. Accepted, since the indirect tier is the point.
- **Use:** the shared map, plus: `_query` is called only by `url`.

### 10. te_latest_version: public, indirect, `versions.py`
- **Spec:**
  - `_key(v)` returns the version's parts as ints, for comparing.
  - `latest(versions)` returns the highest version string.
- **Code:**
  - Buggy `_key`: `return v.split(".")`. Parts are compared as text, so `'9' > '10'`.
  - Fixed: `return [int(p) for p in v.split(".")]`.
  - Caller: `return max(versions, key=_key)`.
- **Prompt:** "latest(['1.9', '1.10']) returns '1.9'."
- **Public tests:**
  - `test_minor_ten`: `latest(['1.9', '1.10'])` → `'1.10'` · gives `'1.9'`.
  - `test_major`: `latest(['2.0', '1.5'])` → `'2.0'` · passes.
  - `test_patch_ten`: `latest(['0.2.10', '0.2.9'])` → `'0.2.10'` · gives `'0.2.9'`.
- **Hidden tests:**
  - `test_single`: `latest(['3'])` → `'3'`.
  - `test_major_ten`: `latest(['10.0', '9.9'])` → `'10.0'`.
- **Checks:** (a) 2/3; (b) ok; (c) ok; (d) the bug is in `_key`; (e) the only public type_error task with no
  exception. It replaced a planned `newest()` (L1). But held-out `ho_te_next_port` has the same root cause
  (numbers compared as text): R2, logged.
- **Use:** the shared map, plus:
  - `_key` is called only by `max`, inside `latest`.
  - The failing trace has no "TypeError", so the **fake** mutation pushes the off_by_one axiom for this task
    (fake_model.py:151). This affects the fake model only. Note it for the test plan and JC-43.

### 11. te_longest_name: public, indirect, `cleaning.py`
- **Spec:**
  - `_clean(name)` returns the name without surrounding spaces.
  - `longest_name(names)` returns the length of the longest cleaned name.
- **Code:**
  - Buggy `_clean`: `name.strip()` with no `return`, so it returns None. The caller's `len(None)` raises TypeError.
  - Fixed: `return name.strip()`.
  - Caller: `return max(len(_clean(n)) for n in names)`.
- **Prompt:** "longest_name() raises TypeError: object of type 'NoneType' has no len()."
- **Public tests:**
  - `test_padded`: `longest_name([' ab ', 'c'])` → `2` · TypeError.
  - `test_single`: `longest_name(['abc'])` → `3` · TypeError.
  - `test_spaces`: `longest_name(['  x  ', 'yy'])` → `2` · TypeError.
- **Hidden tests:**
  - `test_empty_name`: `longest_name(['', 'a'])` → `1`.
  - `test_inner_space`: `longest_name([' long name '])` → `9`.
- **Checks:** (a) 3/3; (b) ok; (c) ok; (d) ok; (e) a missing return, new.
- **Use:** the shared map, plus: `_clean` is called only by `longest_name`.

### 12. ho_te_count_unique: held-out, plain, `rows.py` (replaced ho_te_checksum after review, R1)
- **Spec:** `count_unique(rows)` returns how many distinct rows there are. Each row is a list, and order inside a row
  matters.
- **Code:**
  - Buggy: `return len(set(rows))`. TypeError: unhashable type: 'list'.
  - Fixed: `return len(set(tuple(r) for r in rows))`.
- **Prompt:** "count_unique([[1, 2], [1, 2], [3]]) raises TypeError: unhashable type: 'list'; it should return 2."
- **Public tests:**
  - `test_dupes`: `count_unique([[1, 2], [1, 2], [3]])` → `2` · TypeError.
  - `test_empty`: `count_unique([])` → `0` · passes.
  - `test_distinct`: `count_unique([[1], [2]])` → `2` · TypeError.
- **Hidden tests:**
  - `test_one_row`: `count_unique([[0, 0]])` → `1`.
  - `test_order_matters`: `count_unique([[1, 2], [2, 1]])` → `2`. A frozenset or sorted fix gives 1.
- **Checks:** (a) 2/3 (corpus-check: buggy 1/3); (b) ok; (c) ok; (d) ok; (e) "unhashable" appears once in the table;
  (f) n/a (plain).
- **Use:** the shared map, held-out path.

### 13. ho_te_format_all: held-out, symptom, `formatting.py` (replaced ho_te_add_tag after review, R4)
- **Spec:** `format_all(values, template)` fills a `str.format` template (e.g. `'<{}>'`) with each value and
  returns the list of results.
- **Code:**
  - Buggy: `return [template(v) for v in values]`. TypeError: 'str' object is not callable.
  - Fixed: `return [template.format(v) for v in values]`.
- **Prompt:** "format_all() crashes whenever it is given values."
- **Public tests:**
  - `test_brackets`: `format_all(['a', 'b'], '<{}>')` → `['<a>', '<b>']` · TypeError.
  - `test_empty`: `format_all([], '{}')` → `[]` · passes.
  - `test_number`: `format_all([1], 'n={}')` → `['n=1']` · TypeError.
- **Hidden tests:**
  - `test_padded`: `format_all([7], '{:03d}')` → `['007']`. A format spec must work.
  - `test_no_placeholder`: `format_all(['x', 'y'], 'same')` → `['same', 'same']`.
- **Checks:** (a) 2/3 (corpus-check: buggy 1/3); (b) ok; (c) ok; (d) ok; (e) "not callable" appears once in the
  table; (f) the prompt names no type and no cause.
- **Use:** the shared map, held-out path.

### 14. ho_te_elapsed: held-out, indirect, `elapsed.py`
- **Spec:**
  - `_to_int(s)` parses a numeric string with spaces around it.
  - `elapsed(start, end)` returns `end − start`.
- **Code:**
  - Buggy `_to_int`: `return s.strip()`. The caller's str − str raises TypeError.
  - Fixed: `return int(s.strip())`.
  - Caller: `return _to_int(end) - _to_int(start)`.
- **Prompt:** "elapsed(' 10', '25 ') raises TypeError: unsupported operand type(s) for -: 'str' and 'str'."
- **Public tests:**
  - `test_padded`: `elapsed(' 10', '25 ')` → `15` · TypeError.
  - `test_zero`: `elapsed('0', '0')` → `0` · TypeError.
  - `test_small`: `elapsed('5', '7')` → `2` · TypeError.
- **Hidden tests:**
  - `test_same`: `elapsed('100', '100')` → `0`.
  - `test_both_padded`: `elapsed(' 1 ', ' 31 ')` → `30`.
- **Checks:** (a) 3/3; (b) ok; (c) ok; (d) ok; (e) a helper that forgets to convert. The nearest public task is
  `te_longest_name` (missing return), but this one has a different cause and operator.
- **Use:** the shared map, held-out path. `_to_int` is called only by `elapsed`.

## Agent dynamics: how an agent works a task
Claims marked ✔ were checked against the code or a run on 2026-11-02; ~ marks an expectation about the real model.

### Baseline (seeds/baseline.json) ✔
- **Graph:** `plan` (llm) → `read` (read_file) → `plan` … → `patch` (write_patch). `applied` → **done**;
  `rejected` → `plan`. `give_up` → done. `max_steps` 12. There is **no `run_tests` node**, so the agent never sees
  whether its patch works.
- **Axioms:** "Read the source file named in the task before changing anything." · "Make the smallest change that
  fixes the reported problem." · "Never edit tests; fix the code under test."
- **Each llm step's input** (agent.py:170–175):
  - the system prompt `prompts.subagent_system`: the axioms, plus the allowed outcomes for this node, each with its
    JSON args;
  - the user message `prompts.task_message`: id, prompt, editable files, patterns, test command;
  - the history: earlier replies, plus tool output inside `<tool_output>` tags, older outputs shortened.
- **Reply:** one JSON object `{"outcome", "args"}`. A bad reply → `error` → the same step again (it costs a step).
- **Limits per task run:** `max_steps`, `limits.token_budget` (checked before each llm call, so a run can overshoot
  by one call), `limits.timeout_s`.
- **Example, `te_full_name`** ~:
  1. plan → `read_file src/names.py`;
  2. (maybe `read_file tests/test_names.py`);
  3. plan → `write_patch` with a unified diff. Context lines must match exactly, or the diff is rejected and the
     agent goes back to plan;
  4. applied → done.
  That's 3–4 model calls.
- **After the run** (out of the agent's sight) ✔:
  - `eval:public` runs `tests/` and scores public L1 (selection);
  - the hidden tests run the same patch (holdout_blobs only).
  - A narrow fix (`if middle is None`) scores 3/3 public but 1/2 hidden. Axiom 2 pushes toward narrow fixes.

### Evolved survivor (fake demo `runs/demo-1234`, `g7-a017`) ✔
- **Graph change:** `patch.applied` → `verify` (run_tests). `pass` → done; `fail` → `plan`; `timeout` → done.
  `max_steps` 12 → 8.
- **Axioms added:** "When an operation mixes value types, convert explicitly with str() or int() where the values
  are used." · "Check loop and slice boundaries for off-by-one errors: compare range ends and indexes with the
  counts the docstring promises."
- **Example, `te_full_name`** ~:
  1. plan → read;
  2. plan → patch. The new axiom may suggest `str(middle)`, which gives `'Ana None Lee'`;
  3. applied → verify: fail, and the test output goes into the history;
  4. plan → patch with `if p`;
  5. verify: pass → done.
- **Step count:** 2 (read) + 3 (patch, verify) + 3 (one retry) = 8 = `max_steps`. So this graph allows exactly
  **one** retry.
- **Caveat:** in the fake run, the axiom texts are fixed (`fake_model.SKILL_AXIOMS`) and the graph edits are drawn
  at random. With the real model, the mutation model writes its own edits from a failing trace. It's still one
  JSON-patch or axiom edit per child, kept if it passes L0 and makes the survivors by public L1.
- **Risk:** an axiom learned on one task can mislead on another (`str()` on `te_full_name`). The verify loop
  catches it. The hidden and held-out scores show whether the gains hold up.

## Phase 6: cost estimate (`costs.estimate`, `run.py estimate`) and configs/meta.json sizing

### What the run spends: the loop's structure ✔ (evolution.py:280–355, models.py:56–82, 127–133, agent.py:161)
- **Calls:** every model call reserves `hold = max_tokens + prompt chars // 4` and is charged its real input + output
  tokens.
- **Caps:**
  - main phase: `tokens_total − holdout_reserve`;
  - held-out phase: `tokens_total` (the reserve, plus whatever the main phase left).
- **Seeding** (before generation 0): P − 1 `make_child` calls. Each makes up to `mutation.max_attempts` mutation
  calls.
- **Generation g** (0 … g_max − 1):
  - **Gate:** `need = P·K·token_budget` when g = 0, else `largest_cost·3 // 2`. If `available < need`, the run stops
    with "budget: …".
  - **Evaluation:** the population is ≤ P agents (survivors + children), each run on K tasks, so ≤ P·K task runs.
  - **Children** (not in the last generation): P − |survivors| lineages, each `make_child` once, plus one redraw if
    the first fails. Worst case: |survivors| = 1, so (P − 1)·2·max_attempts mutation calls.
  - `largest_cost = max(largest_cost, spent this generation)`. That includes the children.
- **Held-out:** each final survivor (≤ μ) runs once on every held-out task.

### Worst-case numbers (every call hits its cap): revised after review (R9, R10)
- `PROMPT_TOKENS_EST = 4000` ~: the input of one call **apart from replayed history**. That covers the system
  prompt, the task, the newest tool output, or a mutation's part + trace. The seed's system prompt plus the task
  message is ~1 456 chars, about 364 tokens ✔ (review).
- `subagent_call = subagent.max_tokens + PROMPT_TOKENS_EST`
- **`run_cap = 2 · token_budget + subagent_call`.** Proof sketch ✔ (agent.py:161, 175, 182; `_compact` never shortens
  assistant turns):
  - the run checks `tokens ≥ token_budget` before each call, so before the last call `spent_prev < token_budget`;
  - the last call's input = base (≤ PROMPT_TOKENS_EST) + history;
  - everything in that history except the newest tool output was already the input or output of the previous call,
    so history ≤ spent_prev < token_budget;
  - so last call ≤ token_budget + PROMPT_TOKENS_EST + max_tokens, and run ≤ 2·token_budget + subagent_call.
  - The old `token_budget + subagent_call` was not a bound. The reviewer built a run of 41 684 tokens against 36 000.
- **Mutation** ✔ (evolution.py:181–185, prompts.py:150–152): each retry replays every rejected reply. Attempt k
  costs PROMPT_TOKENS_EST + k·max_tokens:
  - `make_child = A·PROMPT_TOKENS_EST + mutation.max_tokens · A(A+1)/2`, where A = `max_attempts`;
  - `mutation_call` (shown in the output) = the first attempt = max_tokens + PROMPT_TOKENS_EST.
- **Unchanged:**
  - `seeding = (P − 1) · make_child`;
  - `eval_gen = P · K · run_cap`; `children_gen = (P − 1) · 2 · make_child` ✔ (review agrees);
  - `cost(g) = eval_gen + (children_gen if g < g_max − 1 else 0)`;
  - the gate simulation, `main_worst`, `main_cap_needed`, `heldout_worst = μ · n_heldout · run_cap`,
    `tokens_total_needed`. All as before.
- **Not counted** (engine accounting, logged as R11–R13, outside the estimate):
  - an HTTP attempt that fails is charged 0 by the engine, though the provider may still bill it (models.py:134, 155;
    up to `retries + 1` HTTP calls per logical call);
  - the runtime `hold` uses chars // 4, which code and JSON can exceed;
  - going over the cap in the middle of a generation raises BudgetExceeded → infra_error → **the whole generation
    is discarded** ("generation g aborted", evolution.py:305). The held-out stage has no gate.

### Hand traces (revised; compared against `run.py estimate` output after coding)
**configs/meta.json** (P 4, μ 2, K 3, g_max 8, token_budget 30 000, max_tokens 2000/2000, A = 3, n_heldout 10):
- **Per-unit costs:**
  - subagent_call 6000; run_cap = 60 000 + 6000 = **66 000**;
  - make_child = 3·4000 + 2000·6 = **24 000**; seeding = 3·24 000 = **72 000**;
  - eval_gen = 12·66 000 = **792 000**; children_gen = 6·24 000 = **144 000**;
  - cost **936 000** (last generation 792 000).
- **Main phase:**
  - main_worst = 72 000 + 7·936 000 + 792 000 = **7 416 000**;
  - cap_needed at g7 = 72 000 + 6 552 000 + 1 404 000 = **8 028 000** (g0 needs only 72 000 + 360 000).
- **Held-out:** heldout_worst = 2·10·66 000 = **1 320 000**.
- **tokens_total_needed = 9 348 000.**
- **Gate with the phase 6 sizing** (5 400 000, reserve 750 000, cap 4 650 000):
  - g0: 4 578 000 ≥ 360 000 → 1 008 000;
  - g1: 3 642 000 ≥ 1 404 000 → 1 944 000;
  - g2: 2 706 000 ≥ 1 404 000 → 2 880 000;
  - g3: 1 770 000 ≥ 1 404 000 → 3 816 000;
  - g4: 834 000 < 1 404 000 → **generations_fit = 4**.
- **New sizing:** holdout_reserve **1 350 000**, tokens_total **9 400 000** (main cap 8 050 000 ≥ 8 028 000).
  - This is a **ceiling**, and a pessimistic one: every reply would have to hit max_tokens on every step. It is not
    a spend. The fake demo spends ~165–190k.
  - Lower it after the live probe (test plan step 4). A lower cap stops the run with "budget: …" at a generation
    boundary. But if a generation runs past the cap partway through, that generation is discarded (R13).

**Default config** (fake; token_budget 20 000, tokens_total 2 000 000, reserve 200 000):
- **Per-unit costs:**
  - run_cap **46 000**; make_child 24 000; seeding 72 000;
  - eval_gen 12·46 000 = **552 000**; children_gen 144 000;
  - cost **696 000** (last 552 000).
- **Main phase:**
  - main_worst = 72 000 + 7·696 000 + 552 000 = **5 496 000**;
  - cap_needed at g7 = 72 000 + 4 872 000 + 1 044 000 = **5 988 000**.
- **Held-out:** heldout_worst = 2·10·46 000 = **920 000**. tokens_total_needed **6 908 000**.
- **Gate with cap 1 800 000:**
  - g0: 1 728 000 ≥ 240 000 → 768 000;
  - g1: 1 032 000 < 1 044 000 → **generations_fit = 1**.
- The fake model's real spend is far below this, so the default config is left alone (a fake-only config).

### Use in the product
- `apex/costs.py` (new module; the plan said `stats.py`, see C1): `PROMPT_TOKENS_EST`, `estimate`, `format_estimate`.
  - **Why not stats.py:** stats.py may only read the public record. Its output can reach a mutation prompt, and a
    guard test (`test_stats.test_never_reads_the_holdout`) forbids the word "holdout" in it. The estimate needs
    `holdout_reserve` and the held-out count.
- `costs.estimate(cfg, n_heldout) -> dict`:
  - called only by `run.py estimate`;
  - reads only the config and a task count. `run.py` gets the count through `evaluation.heldout_tasks`, which
    validates each held-out `task.json`, the same path `corpus-check` uses; no hidden test is opened (R20);
  - makes no model call and reads no key.
- `costs.format_estimate(d) -> str`: printed by `run.py estimate` only. It says "worst case: every call hits its
  cap; real runs cost less".
- `PROMPT_TOKENS_EST`: used only by `estimate`. It is separate from the runtime `hold` (chars // 4), which charges
  real prompts.
- `run.py estimate [--config]`:
  - loads the config with `config.load`;
  - counts held-out tasks with `len(evaluation.heldout_tasks(...))`. This loads and validates each held-out
    `task.json` (corpus.py:48–70) but never opens a hidden test (R14);
  - exit 2 on a ConfigError or CorpusError (✔ a missing file → exit 2).
- `configs/meta.json` `budget.tokens_total` 9 400 000 / `holdout_reserve` 1 350 000 (revised, R9–R10): read by `evolution.Budget` at run
  start (genesis records the config).
- **Hand traces vs output:** first version ✔ matched exactly; the revised traces are checked again below.

## Phase 7: `run.py stats RUN_DIR [--tasks]`

### Logic of `cmd_stats(args)`: revised after review (R15–R18)
1. **Is it a run?** `ledger.sqlite` must be a file under `RUN_DIR`. If not, print "<dir> is not a run directory
   (no ledger.sqlite)" to stderr and exit **2** ✔ (also when a file is given as the run dir).
2. **Read and format inside one `try`.**
   - `rows`, `summary`, the tier map and the formatted text are all built inside the `try`, and the output is printed
     only after it succeeds. So damage shows up as exit **1** with no partial output.
   - **Caught:** `StatsError`, `sqlite3.DatabaseError`, `OSError`, `KeyError`, `TypeError`, `ValueError`. Edited blob
     fields (`steps: null`, `outcome: 5`) raise TypeError inside the formatting (R15). Stats never checks blob
     hashes; `verify` does.
3. **`summary.json`.**
   - `run_summary` now treats an unreadable `summary.json` like a missing one (no per-generation token line), so a
     sound ledger with a corrupt `summary.json` still gets its statistics (R18).
   - The header says "unfinished run (no summary.json)", "summary.json unreadable (<error>)", or
     `stop: … · tokens spent: …`.
4. **Tiers (`--tasks`)** come from `stats.run_tiers(run_dir, tasks)`:
   - read the run's genesis `public_manifest` blob, which holds the sha256 of every file in each task as recorded at
     genesis;
   - for each current public task: if its `task.json` hash equals the recorded one, the tier is the current
     `difficulty`; otherwise `?`;
   - a task that is not in the current corpus also shows `?`.
   This shows the tier the run actually used, or `?` when it can't be known. Old runs made before phase 4 (no
   `difficulty` field) show `?` everywhere (R17).
   - The corpus load is inside step 2's `try` scope for its own errors: `CorpusError` or `TypeError` (e.g. a
     `task.json` that is `null`) → no tier column, and a note line (R16).
5. **Summary**, then the line "held-out results: see report.md (stats reads the public record only)".
6. **Empty run** → zeros and "–", exit 0 ✔.
- **Known, not fixed** (R19): for a crashed run, the totals include task runs of the generation that never wrote its
  `generation_event`; the per-generation token line leaves them out. The header says "unfinished".

### Traces
- `runs/demo-1234 --tasks` → header with stop "g_max reached"; one row per agent × task across 8 generations; the
  summary; exit 0.
- `runs/nope` → exit 2 (step 1).
- a copy of a run with one **`end` or `eval:public`** blob deleted → `FileNotFoundError` → exit 1 (step 2) ✔.
  Deleting any other blob (an agent record, an llm call) doesn't affect stats → exit 0 ✔ (C2).
- ✔ all traces run on 2026-11-02: demo-1234 (96 task runs, 8 generations) exit 0; runs/nope exit 2; text in
  ledger.sqlite → `DatabaseError` exit 1.
- a copy with `ledger.sqlite` replaced by text → `sqlite3.DatabaseError` → exit 1.

### Use in the product
- `cmd_stats`: the `run.py stats` command only. An operator tool, run after a run (test plan steps 6–7).
- **Reads:** the public record; the corpus `task.json` files for tiers; `summary.json` for the header.
- **Never reads:** `blobs-holdout/`, `holdout/` or the key.
- **Shares** `stats.task_rows`, `stats.run_summary` and `stats.format_*` with `run.py probe`.
- **Adds `stats.run_tiers`** (reads the genesis `public_manifest` blob from `blobs/`: the public record), so the
  guard test (no "holdout" in stats.py) still holds.

## Phase 8: docs and judgement calls

### Logic: docs are claims, each with a source
Every factual line in the new docs must come from a command run on 2026-11-02 (✔ cmd) or from a named file. Nothing is
written from memory.

**`product/README.md`** (rewritten for v1.0):
1. **What it is:** v1.0 = the prototype loop, plus a real Meta model, a 30 + 10 corpus with tiers, and probe / estimate
   / stats. Sources: 1_11_plan.md, PLAN_LOG.md.
2. **Setup:**
   - Python 3.12+, stdlib only, plus `git`;
   - `cp .env.example .env`, then fill `MODEL_API_KEY`;
   - `run.py` loads `.env` only when run as a command. Source: run.py `__main__` ✔.
3. **Commands without a key** (each run once in the phase 8 checks): corpus-check · run --seed · verify · report ·
   stats [--tasks] · estimate [--config] · probe · unittest.
4. **Commands with the key:** models · probe/run `--config configs/meta.json` · `tools/live_checks.py` steps. The order
   comes from `../1_11_test_plan.md`.
5. **What happens in a run:** kept from the prototype README. The sampling sentence is corrected to "one batch of K per
   generation, shared by all agents" (LOGIC R5).
6. **How an agent works a task:** a short version of the agent-dynamics section above, with a link to LOGIC.md.
7. **Corpus:** 30 public + 10 held-out (15 + 5 per family); tiers plain / symptom / indirect; corpus-check ✔ 40 OK.
8. **Costs:** `run.py estimate` gives a worst-case bound. meta.json is sized to it (9.4M ceiling). Lower it after the
   probe. Engine accounting gaps: R11–R13.
9. **Layout:** add costs.py, stats.py, envfile.py, llm_service.py, tools/live_checks.py, configs/meta.json,
   .env.example. Source: `ls` ✔.
10. **Verifying and the tamper demo:** kept, with "prototype" changed to v1.0.
11. **Deviations:** JC-33..JC-45, one line each.
    - The "this host doesn't [support unshare]" line is in the frozen prototype README, not in JC-33, so it stays
      there. JC-33's own stale line is "Docker is not installed"; it gets a dated note pointing to JC-41 (R23).
12. **llm_service.py:** it is written now. Describe its contract (Responses API, key handling, retryable errors) and
    point to `tests/test_llm_service.py` and the contract test.

**`idea.md`**, "Prototype status" section → "Status":
- v1.0 lives in `product/`; `prototype/` stays frozen;
- the corpus is 30 + 10; the real model goes through `apex/llm_service.py`;
- live checks are pending (test plan);
- the link `ideas_unhinges.md` → `ideas_unhinged.md`. The file on disk is `ideas_unhinged.md` ✔ (`ls`), so the old
  link was broken.

**`JUDGEMENT_CALLS.md`** (now ends at JC-38, 38 entries ✔). Add JC-39..JC-45, in the existing format (`### JC-NN · v1.0 ·
title · related:`, options with the taken one in bold, `Status: OPEN`):

| JC | Title | Taken option | Source |
|----|-------|--------------|--------|
| 39 | Real-model adapter | stdlib `urllib`, POST `/responses` (OpenAI-style Responses API), no SDK; non-retryable 3xx/400/401/403/404/422; redirects refused | llm_service.py, PLAN_LOG |
| 40 | Models and endpoint | Muse Spark `muse-spark-1.3` (subagent) and a Muse Code model (mutation, ID pending) at `https://api.meta.ai/v1`; key only in `MODEL_API_KEY` | configs/meta.json, user 2026-11-01 |
| 41 | Real model on the subprocess sandbox | keep the JC-33 subprocess sandbox (`unshare -rn` + prlimit work on this host); tasks are our own corpus | corpus-check output ✔ |
| 42 | `.env` loading | `run.py` and `tools/live_checks.py` load `product/.env` only when run as commands; tests never do | run.py, live_checks.py |
| 43 | Corpus tiers and labels | 30 + 10, tiers set by hand before probe data; `te_latest_version` labelled type_error with no TypeError; held-out overlaps logged | LOGIC R2, R6, R8 |
| 44 | Probe and cost bound | the probe skips held-out tasks (§9.1); meta.json budget = the pessimistic `estimate` bound (9.4M), to be lowered after the probe | evolution.py `heldout`, costs.py |
| 45 | Smoke-only build | build v1.0 with smoke checks; deeper tests run after the build from `1_11_test_plan.md` (one-off, user) | PLAN_LOG 2026-11-01 |

**Check:** `grep -c "^### JC-" JUDGEMENT_CALLS.md` → 45.

### Code change found in review: `tools/live_checks.py` loads `.env` only as a command (R22)
- **Before:** `envfile.load(ROOT / ".env")` ran inside `main()`. Tests that call `main()` stayed offline only because
  each one mocked `envfile.load`.
- **After:** `main()` reads only `os.environ`. `.env` is loaded in `if __name__ == "__main__":` before `main()`,
  exactly like `run.py:275`.
- **Trace:**
  - a test calls `main(["models"])` with `MODEL_API_KEY=""` in its environment → key refusal, exit 2, and `.env` is
    never read;
  - the command `python3 tools/live_checks.py estimate` → `.env` loaded, then the step runs.
  The existing mocks still patch a function that is now unused in tests, which is harmless.

### Use in the product
- **Docs only:** no code changes. The README commands are run once as the check.
- **LOGIC.md** is linked from the README ("How an agent works a task"), so a reader can find the traces.

## type_error failure-mode table (for check e)
| Task | Set | What fails |
|------|-----|-----------|
| te_greeting | public | str + int (concatenation) |
| te_url | public | str + int (concatenation, in a helper) |
| ho_te_label | held-out | str + int (concatenation): **twin of te_greeting** (older task, R8) |
| te_total_price | public | `sum()` over str |
| te_mean_csv | public | `sum()` over str |
| ho_te_next_port | held-out | `max()` over str (compared as text), then str + int: **overlaps te_latest_version** (R2) |
| te_latest_version | public | numbers compared as text (no exception) |
| te_join_ids | public | `join` of ints |
| te_full_name | public | `join` with None |
| te_shout | public | list × str |
| te_digit_count | public | `len(int)` |
| te_minutes | public | str // int |
| te_add_minutes | public | str × int, then str + int |
| te_over_limit | public | int > str |
| te_merge_tags | public | set + set, set + list |
| te_count_above_mean | public | `len(map)` (helper) |
| te_longest_name | public | `len(None)` (helper missing `return`) |
| ho_te_count_unique | held-out | unhashable list in a set |
| ho_te_format_all | held-out | calling a str |
| ho_te_elapsed | held-out | str − str (helper) |

## Issue log
| # | Phase | Stage | Issue | Action |
|---|-------|-------|-------|--------|
| L1 | 5 | L | Planned `newest(['9', '10'])` had the same shape as `te_latest_version` (numbers compared as text) | Swapped for `te_minutes` |
| L2 | 5 | L | Planned `percent('1', '4')` was too close to `te_minutes` (unconverted numeric string, then `//`) | Swapped for `te_full_name` |
| L3 | 5 | L | Phase 4 review: held-out tasks close to public ones | Checked held-out 12–14 against every public shape (check e) |
| L4 | 5 | L | `te_latest_version` has no TypeError, so the fake mutation picks the off_by_one axiom | Kept (fake model only); note for the test plan |

| R1 | 5 | R | `ho_te_checksum` fails like `te_total_price` / `te_mean_csv` (`sum()` over str); LOGIC.md said "no public twin" (**LOGIC wrong**) | Replaced by `ho_te_count_unique` |
| R2 | 5 | R | `te_latest_version` has the same root cause as held-out `ho_te_next_port` (text compare); L1 missed it (**LOGIC incomplete**) | Logged; retune in test plan step 3 |
| R3 | 5 | R | Prompts hint at the cause: indirect `te_count_above_mean`, `te_longest_name`, `ho_te_elapsed` name the type; symptom `te_full_name`, `te_over_limit` name the trigger. Check (d) never looked for hints (**LOGIC check missing**) | Check (f) added; tiers retuned after the live probe |
| R4 | 5 | R | `ho_te_add_tag` fails like `te_merge_tags` (`+` between mismatched containers); LOGIC.md said "different operator" (**LOGIC wrong**) | Replaced by `ho_te_format_all` |
| R5 | 5 | R | Shared map: "K tasks for every agent" (one shared batch per generation); `heldout_tasks` cited at its call site (**LOGIC wording wrong**) | Fixed here |
| R6 | 5 | R | `te_latest_version` labelled type_error with no TypeError; affects only the fake model (LOGIC L4 right) | Judgment call → JC in phase 8 |
| R7 | 5 | R | `te_url` is the third str + int task (LOGIC right, accepted) | None |
| R8 | 5 | table | Older held-out `ho_te_label` is a twin of `te_greeting` (found while building the failure-mode table) | Logged; retune in test plan step 3 |

Phase 5 time: the logic write-up for 14 tasks was ~2 min of wall time (17:54 → 17:56), plus the redo of 2 tasks
and this log after review. Corpus-check, the suite and the fake run passed on the first try; the buggy pass counts
matched every trace.
| C1 | 6 | C | `estimate` was put in `stats.py`, which must never name the held-out store (guard test); the logic's "Use" section missed the existing rule (**LOGIC incomplete**) | Moved to new `apex/costs.py`; the guard test is unchanged |
| R9 | 6 | R | `run_cap = token_budget + one call` is not a bound: every call re-sends earlier replies (built example: 41 684 > 36 000) (**LOGIC wrong**) | `run_cap = 2·token_budget + subagent_call`, with a proof |
| R10 | 6 | R | Mutation retries replay rejected replies, so make_child grows (**LOGIC silent**); meta "reaches g_max" was false | `make_child = A·est + max·A(A+1)/2`; meta.json resized |
| R11 | 6 | R | An HTTP attempt that fails but is still billed is charged 0 (models.py:134, 155); up to retries+1 HTTP calls per logical call (**LOGIC silent**) | Logged (engine; the real bill can exceed `spent`) |
| R12 | 6 | R | `hold` = chars // 4 can underestimate code/JSON tokens, so spent can pass the main cap a little (**LOGIC silent**) | Logged |
| R13 | 6 | R | Going over the cap partway through a generation → BudgetExceeded → the generation is discarded; no gate before held-out (**LOGIC silent**) | Logged; test plan step 5 |
| R14 | 6 | R | "only counts directories" was wrong (load_task reads each held-out task.json); the base-prompt size was over-stated (**LOGIC wrong, minor**) | Fixed wording |
| C2 | 7 | C | The trace said "one blob deleted → exit 1", but stats reads only `end` / `eval:public` blobs; a random deleted blob gave exit 0 (**LOGIC trace wrong**, code right) | Trace corrected and re-run with an `end` blob |
| R15 | 7 | R | Formatting ran outside the `try`: edited blob fields (`steps: null`) crashed with a traceback; "catches exactly these" was wrong for that path (**LOGIC wrong**) | All reading and formatting in one `try`; print only after it succeeds |
| R16 | 7 | R | The tier load caught only CorpusError; a `null` task.json raised TypeError (**LOGIC silent**) | Catch TypeError too, no tier column, note line |
| R17 | 7 | R | Tiers came from the current corpus even for older runs, so they could be wrong after a retune (**LOGIC silent**) | `stats.run_tiers`: a tier is shown only when task.json matches the run's genesis manifest |
| R18 | 7 | R | A corrupt summary.json failed the whole command via `run_summary` (**LOGIC silent**) | `run_summary` treats it as missing |
| R19 | 7 | R | A crashed run's totals include the unfinished generation's task runs (**LOGIC silent**) | Logged |
| R20 | 6 | R | `estimate` "reads only the config and a task count" hid that the count validates each held-out task.json (**LOGIC wrong**) | Wording fixed; code kept (same path as corpus-check) |
| R21 | 8 | R | README listed `live_checks.py estimate` / `stats` under "With the key"; neither needs it (NEEDS_KEY) (**LOGIC silent**) | Split the list |
| R22 | 8 | R | live_checks.py loaded `.env` inside `main()`; tests were offline only because of mocks (**LOGIC silent**) | Load moved under `__main__` |
| R23 | 8 | R | JC-33 still says Docker is not installed; the plan aimed its fix at the wrong line (**LOGIC wrong**) | Dated note in JC-33 |
| R24 | 8 | R | Test plan §8 named `stats.estimate` (now `costs.estimate`) (**LOGIC silent**) | Renamed |
| R25 | 8 | R | README used "robust" and "operator commands" (user's plain-language rule) (**LOGIC silent**: no wording check) | Reworded |
| R26 | 8 | R | README said block timestamps are used for tie-breaks; the sort key is (−L1, tokens, tip block hash) (**LOGIC silent**, text was "kept") | Reworded |
| R27 | 8 | R | idea.md cited JC-44 for `stats`, which no JC covers (**LOGIC silent**) | Reworded |

