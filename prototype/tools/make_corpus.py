"""Build the prototype task corpus (design §9.1): 8 public tasks, their hidden tests, and 4 held-out tasks.

Writes, relative to the prototype directory:
  corpus/public/<id>/{task.json, repo/src/<module>.py, tests/test_<module>.py}
  holdout/hidden_tests/<id>/test_<module>_hidden.py
  holdout/tasks/<id>/{task.json, repo/..., tests/..., hidden_tests/...}
  oracle/<id>.diff        reference fix, read only by the fake model and `run.py corpus-check`
  oracle/index.json       task id → distribution, for the fake model's skill check

Run from the prototype directory:  python3 tools/make_corpus.py
"""
import difflib
import json
import shutil
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEST_COMMAND = ["python3", "-m", "unittest", "discover", "-s", "tests", "-p", "test*.py"]


def T(id, distribution, heldout, module, func, prompt, buggy, fixed, tests, hidden):
    return dict(id=id, distribution=distribution, heldout=heldout, module=module, func=func, prompt=prompt,
                buggy=buggy, fixed=fixed, tests=tests, hidden=hidden)


TASKS = [
    # ---- off_by_one: public -------------------------------------------------------------------------------
    T("obo_window_sum", "off_by_one", False, "window", "window_sum",
      "window_sum() drops the last window: window_sum([1, 2, 3, 4], 2) returns [3, 5] instead of [3, 5, 7].",
      '''
      def window_sum(xs, k):
          """Return the sum of every contiguous window of length k."""
          return [sum(xs[i:i + k]) for i in range(len(xs) - k)]
      ''',
      '''
      def window_sum(xs, k):
          """Return the sum of every contiguous window of length k."""
          return [sum(xs[i:i + k]) for i in range(len(xs) - k + 1)]
      ''',
      [("test_basic", "window_sum([1, 2, 3, 4], 2)", "[3, 5, 7]"),
       ("test_whole_list", "window_sum([5, 5], 2)", "[10]"),
       ("test_k_too_big", "window_sum([1], 2)", "[]")],
      [("test_k_one", "window_sum([4, 0, 2], 1)", "[4, 0, 2]"),
       ("test_longer", "window_sum([1, 1, 1, 1, 1], 3)", "[3, 3, 3]")]),
    T("obo_last_n", "off_by_one", False, "tail", "last_n",
      "last_n() returns one item too few: last_n([1, 2, 3, 4], 2) returns [4] instead of [3, 4].",
      '''
      def last_n(xs, n):
          """Return the last n items of xs (all of xs if n >= len(xs))."""
          if n <= 0:
              return []
          return xs[max(len(xs) - n + 1, 0):]
      ''',
      '''
      def last_n(xs, n):
          """Return the last n items of xs (all of xs if n >= len(xs))."""
          if n <= 0:
              return []
          return xs[max(len(xs) - n, 0):]
      ''',
      [("test_two", "last_n([1, 2, 3, 4], 2)", "[3, 4]"),
       ("test_more_than_len", "last_n([1, 2], 5)", "[1, 2]"),
       ("test_zero", "last_n([1, 2, 3], 0)", "[]")],
      [("test_exact_len", "last_n([7, 8, 9], 3)", "[7, 8, 9]"),
       ("test_one", "last_n(list(range(10)), 1)", "[9]")]),
    T("obo_count_in_range", "off_by_one", False, "ranges", "count_in_range",
      "count_in_range() should treat both bounds as inclusive, but count_in_range([10], 10, 10) returns 0.",
      '''
      def count_in_range(xs, lo, hi):
          """Count the items x with lo <= x <= hi (both bounds inclusive)."""
          return sum(1 for x in xs if lo <= x < hi)
      ''',
      '''
      def count_in_range(xs, lo, hi):
          """Count the items x with lo <= x <= hi (both bounds inclusive)."""
          return sum(1 for x in xs if lo <= x <= hi)
      ''',
      [("test_middle", "count_in_range([1, 2, 3, 4, 5], 2, 4)", "3"),
       ("test_empty", "count_in_range([], 0, 10)", "0"),
       ("test_single_point", "count_in_range([10], 10, 10)", "1")],
      [("test_both_ends", "count_in_range([0, 5, 10], 0, 10)", "3"),
       ("test_none", "count_in_range([3, 3, 3], 1, 2)", "0")]),
    T("obo_page_count", "off_by_one", False, "paging", "page_count",
      "page_count() loses the final partial page: page_count(11, 5) returns 2 instead of 3.",
      '''
      def page_count(total_items, per_page):
          """Number of pages needed to show total_items items, per_page items per page."""
          return total_items // per_page
      ''',
      '''
      def page_count(total_items, per_page):
          """Number of pages needed to show total_items items, per_page items per page."""
          return (total_items + per_page - 1) // per_page
      ''',
      [("test_exact", "page_count(10, 5)", "2"),
       ("test_partial", "page_count(11, 5)", "3"),
       ("test_zero", "page_count(0, 5)", "0")],
      [("test_one_item", "page_count(1, 10)", "1"),
       ("test_partial_tens", "page_count(21, 10)", "3")]),
    # ---- type_error: public -------------------------------------------------------------------------------
    T("te_greeting", "type_error", False, "greet", "greeting",
      "greeting('Ana', 30) raises TypeError: can only concatenate str (not \"int\") to str.",
      '''
      def greeting(name, age):
          """Return 'Hi <name>, you are <age>' for a name (str) and an age (int)."""
          return "Hi " + name + ", you are " + age
      ''',
      '''
      def greeting(name, age):
          """Return 'Hi <name>, you are <age>' for a name (str) and an age (int)."""
          return "Hi " + name + ", you are " + str(age)
      ''',
      [("test_int_age", "greeting('Ana', 30)", "'Hi Ana, you are 30'"),
       ("test_small_age", "greeting('Bo', 7)", "'Hi Bo, you are 7'"),
       ("test_str_age", "greeting('Cy', '5')", "'Hi Cy, you are 5'")],
      [("test_empty_name", "greeting('', 0)", "'Hi , you are 0'"),
       ("test_big_age", "greeting('Zoe', 101)", "'Hi Zoe, you are 101'")]),
    T("te_total_price", "type_error", False, "prices", "total_price",
      "total_price([('a', '3'), ('b', '4')]) raises TypeError: unsupported operand type(s) for +: 'int' and 'str'.",
      '''
      def total_price(rows):
          """Sum the prices in (name, price) rows read from a CSV, where price is a string such as '12'."""
          return sum(price for _, price in rows)
      ''',
      '''
      def total_price(rows):
          """Sum the prices in (name, price) rows read from a CSV, where price is a string such as '12'."""
          return sum(int(price) for _, price in rows)
      ''',
      [("test_two_rows", "total_price([('a', '3'), ('b', '4')])", "7"),
       ("test_empty", "total_price([])", "0"),
       ("test_one_row", "total_price([('x', '10')])", "10")],
      [("test_zeros", "total_price([('a', '0'), ('b', '0')])", "0"),
       ("test_three", "total_price([('p', '100'), ('q', '1'), ('r', '2')])", "103")]),
    T("te_join_ids", "type_error", False, "ids", "join_ids",
      "join_ids([1, 2]) raises TypeError: sequence item 0: expected str instance, int found.",
      '''
      def join_ids(ids):
          """Join integer ids into a comma-separated string, e.g. [1, 2] -> '1,2'."""
          return ",".join(ids)
      ''',
      '''
      def join_ids(ids):
          """Join integer ids into a comma-separated string, e.g. [1, 2] -> '1,2'."""
          return ",".join(str(i) for i in ids)
      ''',
      [("test_two", "join_ids([1, 2])", "'1,2'"),
       ("test_empty", "join_ids([])", "''"),
       ("test_one", "join_ids([42])", "'42'")],
      [("test_three", "join_ids([0, 10, 200])", "'0,10,200'"),
       ("test_repeat", "join_ids([7, 7])", "'7,7'")]),
    T("te_mean_csv", "type_error", False, "stats", "mean_of_csv",
      "mean_of_csv('1,2,3') raises TypeError: unsupported operand type(s) for +: 'int' and 'str'.",
      '''
      def mean_of_csv(line):
          """Return the floor of the mean of a comma-separated line of integers, e.g. '1,2,3' -> 2."""
          parts = line.split(",")
          return sum(parts) // len(parts)
      ''',
      '''
      def mean_of_csv(line):
          """Return the floor of the mean of a comma-separated line of integers, e.g. '1,2,3' -> 2."""
          parts = [int(p) for p in line.split(",")]
          return sum(parts) // len(parts)
      ''',
      [("test_three", "mean_of_csv('1,2,3')", "2"),
       ("test_single", "mean_of_csv('10')", "10"),
       ("test_pair", "mean_of_csv('4,4')", "4")],
      [("test_floor", "mean_of_csv('0,0,1')", "0"),
       ("test_odd_pair", "mean_of_csv('5,6')", "5")]),
    # ---- held-out tasks (one run by the final survivors only) ---------------------------------------------
    T("ho_obo_chunk", "off_by_one", True, "chunks", "chunk",
      "chunk() drops the last piece: chunk([1, 2, 3, 4, 5], 2) returns [[1, 2], [3, 4]] instead of [[1, 2], [3, 4], [5]].",
      '''
      def chunk(xs, n):
          """Split xs into consecutive pieces of length n (the last piece may be shorter)."""
          return [xs[i:i + n] for i in range(0, len(xs) - 1, n)]
      ''',
      '''
      def chunk(xs, n):
          """Split xs into consecutive pieces of length n (the last piece may be shorter)."""
          return [xs[i:i + n] for i in range(0, len(xs), n)]
      ''',
      [("test_even", "chunk([1, 2, 3, 4], 2)", "[[1, 2], [3, 4]]"),
       ("test_odd", "chunk([1, 2, 3, 4, 5], 2)", "[[1, 2], [3, 4], [5]]"),
       ("test_short", "chunk([1], 3)", "[[1]]")],
      [("test_empty", "chunk([], 2)", "[]"),
       ("test_singles", "chunk([1, 2, 3], 1)", "[[1], [2], [3]]")]),
    T("ho_obo_nth_from_end", "off_by_one", True, "nth", "nth_from_end",
      "nth_from_end([1, 2, 3], 1) should return the last item (3) but returns 2.",
      '''
      def nth_from_end(xs, n):
          """Return the n-th item counting from the end, 1-based (n=1 is the last item)."""
          return xs[len(xs) - n - 1]
      ''',
      '''
      def nth_from_end(xs, n):
          """Return the n-th item counting from the end, 1-based (n=1 is the last item)."""
          return xs[len(xs) - n]
      ''',
      [("test_last", "nth_from_end([1, 2, 3], 1)", "3"),
       ("test_first", "nth_from_end([1, 2, 3], 3)", "1"),
       ("test_pair", "nth_from_end([5, 6], 2)", "5")],
      [("test_letters", "nth_from_end(['a', 'b'], 1)", "'b'"),
       ("test_single", "nth_from_end([9], 1)", "9")]),
    T("ho_te_label", "type_error", True, "labels", "label",
      "label('item', 3) raises TypeError: can only concatenate str (not \"int\") to str.",
      '''
      def label(prefix, n):
          """Return '<prefix>-<n>' for a string prefix and an integer n."""
          return prefix + "-" + n
      ''',
      '''
      def label(prefix, n):
          """Return '<prefix>-<n>' for a string prefix and an integer n."""
          return prefix + "-" + str(n)
      ''',
      [("test_int", "label('item', 3)", "'item-3'"),
       ("test_str", "label('x', 'y')", "'x-y'"),
       ("test_zero", "label('a', 0)", "'a-0'")],
      [("test_empty_prefix", "label('', 5)", "'-5'"),
       ("test_two_digits", "label('v', 10)", "'v-10'")]),
    T("ho_te_next_port", "type_error", True, "ports", "next_free_port",
      "next_free_port('80,443') raises TypeError: can only concatenate str (not \"int\") to str.",
      '''
      def next_free_port(spec):
          """Return one more than the largest port in a comma-separated spec, e.g. '80,443' -> 444."""
          ports = spec.split(",")
          return max(ports) + 1
      ''',
      '''
      def next_free_port(spec):
          """Return one more than the largest port in a comma-separated spec, e.g. '80,443' -> 444."""
          ports = [int(p) for p in spec.split(",")]
          return max(ports) + 1
      ''',
      [("test_two", "next_free_port('80,443')", "444"),
       ("test_one", "next_free_port('8080')", "8081"),
       ("test_small", "next_free_port('1,2')", "3")],
      [("test_unordered", "next_free_port('443,80')", "444"),
       ("test_numeric_max", "next_free_port('9,10')", "11")]),
]


def test_file(module, func, cases, cls):
    lines = ["import unittest", "", f"from src.{module} import {func}", "", "",
             f"class {cls}(unittest.TestCase):"]
    for name, call, expected in cases:
        lines += [f"    def {name}(self):", f"        self.assertEqual({call}, {expected})", ""]
    return "\n".join(lines).rstrip() + "\n"


def src(text):
    return textwrap.dedent(text).lstrip("\n")


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main():
    for sub in ("corpus/public", "holdout/hidden_tests", "holdout/tasks", "oracle"):
        shutil.rmtree(ROOT / sub, ignore_errors=True)
        (ROOT / sub).mkdir(parents=True)
    for t in TASKS:
        rel = f"src/{t['module']}.py"
        cls = "Test" + "".join(w.title() for w in t["func"].split("_"))
        base = ROOT / ("holdout/tasks" if t["heldout"] else "corpus/public") / t["id"]
        meta = {"id": t["id"], "distribution": t["distribution"], "prompt": t["prompt"],
                "editable_paths": ["src/*.py"], "test_command": TEST_COMMAND}
        write(base / "task.json", json.dumps(meta, indent=2) + "\n")
        write(base / "repo" / rel, src(t["buggy"]))
        write(base / "tests" / f"test_{t['module']}.py", test_file(t["module"], t["func"], t["tests"], cls))
        hidden_dir = base / "hidden_tests" if t["heldout"] else ROOT / "holdout/hidden_tests" / t["id"]
        write(hidden_dir / f"test_{t['module']}_hidden.py",
              test_file(t["module"], t["func"], t["hidden"], cls + "Hidden"))
        diff = difflib.unified_diff(src(t["buggy"]).splitlines(keepends=True), src(t["fixed"]).splitlines(keepends=True),
                                    fromfile=f"a/{rel}", tofile=f"b/{rel}")
        write(ROOT / "oracle" / f"{t['id']}.diff", "".join(diff))
    index = {t["id"]: t["distribution"] for t in TASKS}
    write(ROOT / "oracle" / "index.json", json.dumps(index, indent=2, sort_keys=True) + "\n")
    print(f"wrote {sum(not t['heldout'] for t in TASKS)} public and {sum(t['heldout'] for t in TASKS)} held-out tasks")


if __name__ == "__main__":
    main()
