"""Build the task corpus (design §9.1): public tasks, their hidden tests, and held-out tasks.

Each task has a difficulty tier (apex/corpus.py DIFFICULTIES), written to task.json for the operator's tables only:
plain (the prompt states the wrong and the right output), symptom (only the symptom), indirect (the bug is in a
helper the named function calls). Tiers are set by hand; the live probe retunes them (1_11_test_plan.md step 3).

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


def T(id, distribution, heldout, module, func, prompt, buggy, fixed, tests, hidden, difficulty="plain"):
    return dict(id=id, distribution=distribution, heldout=heldout, module=module, func=func, prompt=prompt,
                buggy=buggy, fixed=fixed, tests=tests, hidden=hidden, difficulty=difficulty)


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
    # plain: the prompt states the wrong and the right output
    T("obo_inclusive_range", "off_by_one", False, "steps", "inclusive_range",
      "inclusive_range(1, 3) returns [1, 2] instead of [1, 2, 3].",
      '''
      def inclusive_range(a, b):
          """Return the integers from a to b, both included."""
          return list(range(a, b))
      ''',
      '''
      def inclusive_range(a, b):
          """Return the integers from a to b, both included."""
          return list(range(a, b + 1))
      ''',
      [("test_basic", "inclusive_range(1, 3)", "[1, 2, 3]"),
       ("test_single", "inclusive_range(0, 0)", "[0]"),
       ("test_offset", "inclusive_range(5, 7)", "[5, 6, 7]")],
      [("test_negative", "inclusive_range(-1, 1)", "[-1, 0, 1]"),
       ("test_reversed", "inclusive_range(3, 2)", "[]")]),
    T("obo_up_to", "off_by_one", False, "upto", "up_to",
      "up_to([1, 2, 3, 4], 2) returns [1, 2] instead of [1, 2, 3].",
      '''
      def up_to(xs, i):
          """Return the items of xs up to and including index i."""
          return xs[:i]
      ''',
      '''
      def up_to(xs, i):
          """Return the items of xs up to and including index i."""
          return xs[:i + 1]
      ''',
      [("test_middle", "up_to([1, 2, 3, 4], 2)", "[1, 2, 3]"),
       ("test_first", "up_to([1], 0)", "[1]"),
       ("test_last", "up_to(['a', 'b'], 1)", "['a', 'b']")],
      [("test_zero", "up_to([5, 6, 7], 0)", "[5]"),
       ("test_long", "up_to([1, 2, 3, 4, 5], 3)", "[1, 2, 3, 4]")]),
    T("obo_pad_left", "off_by_one", False, "pad", "pad_left",
      "pad_left('7', 3, '0') returns '07' instead of '007'.",
      '''
      def pad_left(s, width, ch):
          """Pad s on the left with ch until it is width characters long (longer strings are unchanged)."""
          return ch * (width - len(s) - 1) + s
      ''',
      '''
      def pad_left(s, width, ch):
          """Pad s on the left with ch until it is width characters long (longer strings are unchanged)."""
          return ch * (width - len(s)) + s
      ''',
      [("test_zeros", "pad_left('7', 3, '0')", "'007'"),
       ("test_dots", "pad_left('ab', 4, '.')", "'..ab'"),
       ("test_one", "pad_left('x', 2, ' ')", "' x'")],
      [("test_full", "pad_left('abc', 3, '0')", "'abc'"),
       ("test_empty", "pad_left('', 2, '-')", "'--'")]),
    # symptom: the prompt gives only the symptom
    T("obo_middle", "off_by_one", False, "middle", "middle",
      "middle() does not return the middle item of the list.",
      '''
      def middle(xs):
          """Return the middle item of a list of odd length."""
          return xs[len(xs) // 2 + 1]
      ''',
      '''
      def middle(xs):
          """Return the middle item of a list of odd length."""
          return xs[len(xs) // 2]
      ''',
      [("test_three", "middle([1, 2, 3])", "2"),
       ("test_one", "middle([5])", "5"),
       ("test_five", "middle([1, 2, 3, 4, 5])", "3")],
      [("test_letters", "middle(['a', 'b', 'c'])", "'b'"),
       ("test_seven", "middle([9, 8, 7, 6, 5, 4, 3])", "6")],
      difficulty="symptom"),
    T("obo_first_half", "off_by_one", False, "halves", "first_half",
      "first_half() loses an item on lists of odd length.",
      '''
      def first_half(xs):
          """Return the first half of xs; on odd lengths the middle item belongs to the first half."""
          return xs[:len(xs) // 2]
      ''',
      '''
      def first_half(xs):
          """Return the first half of xs; on odd lengths the middle item belongs to the first half."""
          return xs[:(len(xs) + 1) // 2]
      ''',
      [("test_odd", "first_half([1, 2, 3])", "[1, 2]"),
       ("test_even", "first_half([1, 2, 3, 4])", "[1, 2]"),
       ("test_one", "first_half([7])", "[7]")],
      [("test_empty", "first_half([])", "[]"),
       ("test_five", "first_half([1, 2, 3, 4, 5])", "[1, 2, 3]")],
      difficulty="symptom"),
    T("obo_countdown", "off_by_one", False, "countdown", "countdown",
      "The list countdown() returns is too short.",
      '''
      def countdown(n):
          """Return [n, n - 1, ..., 1]."""
          return list(range(n, 1, -1))
      ''',
      '''
      def countdown(n):
          """Return [n, n - 1, ..., 1]."""
          return list(range(n, 0, -1))
      ''',
      [("test_three", "countdown(3)", "[3, 2, 1]"),
       ("test_one", "countdown(1)", "[1]"),
       ("test_five", "countdown(5)", "[5, 4, 3, 2, 1]")],
      [("test_zero", "countdown(0)", "[]"),
       ("test_two", "countdown(2)", "[2, 1]")],
      difficulty="symptom"),
    T("obo_in_bounds", "off_by_one", False, "bounds", "in_bounds",
      "Code that checks in_bounds(i, xs) before reading xs[i] still crashes with IndexError sometimes.",
      '''
      def in_bounds(i, xs):
          """True when i is a valid non-negative index into xs."""
          return 0 <= i <= len(xs)
      ''',
      '''
      def in_bounds(i, xs):
          """True when i is a valid non-negative index into xs."""
          return 0 <= i < len(xs)
      ''',
      [("test_past_end", "in_bounds(3, [1, 2, 3])", "False"),
       ("test_first", "in_bounds(0, [1])", "True"),
       ("test_last", "in_bounds(2, [1, 2, 3])", "True")],
      [("test_empty", "in_bounds(0, [])", "False"),
       ("test_negative", "in_bounds(-1, [1])", "False")],
      difficulty="symptom"),
    # indirect: the bug is in a helper the named function calls
    T("obo_last_words", "off_by_one", False, "words", "last_words",
      "last_words('a b c d', 2) returns 'd' instead of 'c d'.",
      '''
      def _tail(xs, k):
          """Return the last k items of xs (all of xs when k >= len(xs))."""
          start = max(len(xs) - k + 1, 0)
          return xs[start:]


      def last_words(text, k):
          """Return the last k words of text, joined by single spaces."""
          return " ".join(_tail(text.split(), k))
      ''',
      '''
      def _tail(xs, k):
          """Return the last k items of xs (all of xs when k >= len(xs))."""
          start = max(len(xs) - k, 0)
          return xs[start:]


      def last_words(text, k):
          """Return the last k words of text, joined by single spaces."""
          return " ".join(_tail(text.split(), k))
      ''',
      [("test_two", "last_words('a b c d', 2)", "'c d'"),
       ("test_one", "last_words('x y', 1)", "'y'"),
       ("test_all", "last_words('one two three', 3)", "'one two three'")],
      [("test_more_than_all", "last_words('a b', 5)", "'a b'"),
       ("test_four", "last_words('p q r s t', 4)", "'q r s t'")],
      difficulty="indirect"),
    T("obo_count_increases", "off_by_one", False, "trend", "count_increases",
      "count_increases() misses some increases.",
      '''
      def _pairs(xs):
          """Return every pair of neighbouring items (xs[i], xs[i + 1])."""
          return [(xs[i], xs[i + 1]) for i in range(len(xs) - 2)]


      def count_increases(xs):
          """Count how many items are larger than the item just before them."""
          return sum(b > a for a, b in _pairs(xs))
      ''',
      '''
      def _pairs(xs):
          """Return every pair of neighbouring items (xs[i], xs[i + 1])."""
          return [(xs[i], xs[i + 1]) for i in range(len(xs) - 1)]


      def count_increases(xs):
          """Count how many items are larger than the item just before them."""
          return sum(b > a for a, b in _pairs(xs))
      ''',
      [("test_rising", "count_increases([1, 2, 3])", "2"),
       ("test_falling", "count_increases([3, 2, 1])", "0"),
       ("test_mixed", "count_increases([1, 3, 2, 4])", "2")],
      [("test_single", "count_increases([5])", "0"),
       ("test_plateaus", "count_increases([1, 1, 2, 2, 3])", "2")],
      difficulty="indirect"),
    T("obo_page_items", "off_by_one", False, "pager", "page",
      "page(items, 1, 10) skips the first ten items.",
      '''
      def _offset(n, size):
          """Index of the first item on page n (pages are 1-based)."""
          return n * size


      def page(items, n, size):
          """Return page n (1-based) of items, size items per page."""
          start = _offset(n, size)
          return items[start:start + size]
      ''',
      '''
      def _offset(n, size):
          """Index of the first item on page n (pages are 1-based)."""
          return (n - 1) * size


      def page(items, n, size):
          """Return page n (1-based) of items, size items per page."""
          start = _offset(n, size)
          return items[start:start + size]
      ''',
      [("test_first", "page(list(range(10)), 1, 3)", "[0, 1, 2]"),
       ("test_second", "page(list(range(10)), 2, 3)", "[3, 4, 5]"),
       ("test_partial", "page(list(range(10)), 4, 3)", "[9]")],
      [("test_short_list", "page(['a', 'b'], 1, 5)", "['a', 'b']"),
       ("test_third", "page(list(range(6)), 3, 2)", "[4, 5]")],
      difficulty="indirect"),
    T("obo_line_number", "off_by_one", False, "textpos", "line_number",
      "line_number(text, pos) is wrong when pos points at a newline character.",
      '''
      def _newlines_before(text, end):
          """Count the newline characters in text[:end]."""
          return text.count("\\n", 0, end + 1)


      def line_number(text, pos):
          """Return the 1-based line number of the character at index pos (a newline character belongs to the line it ends)."""
          return _newlines_before(text, pos) + 1
      ''',
      '''
      def _newlines_before(text, end):
          """Count the newline characters in text[:end]."""
          return text.count("\\n", 0, end)


      def line_number(text, pos):
          """Return the 1-based line number of the character at index pos (a newline character belongs to the line it ends)."""
          return _newlines_before(text, pos) + 1
      ''',
      [("test_start", "line_number('ab\\ncd', 0)", "1"),
       ("test_second_line", "line_number('ab\\ncd', 3)", "2"),
       ("test_on_newline", "line_number('ab\\ncd', 2)", "1")],
      [("test_one_line", "line_number('xyz', 2)", "1"),
       ("test_blank_lines", "line_number('\\n\\n', 1)", "2")],
      difficulty="indirect"),
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
    # plain (logic and traces: ../LOGIC.md, phase 5)
    T("te_shout", "type_error", False, "shout", "shout",
      "shout('hi', '3') raises TypeError: can't multiply sequence by non-int of type 'str'; it should return 'HI HI HI'.",
      '''
      def shout(word, times):
          """Return word in upper case, repeated times times, joined by single spaces (times: int or numeric str)."""
          return " ".join([word.upper()] * times)
      ''',
      '''
      def shout(word, times):
          """Return word in upper case, repeated times times, joined by single spaces (times: int or numeric str)."""
          return " ".join([word.upper()] * int(times))
      ''',
      [("test_str_times", "shout('hi', '3')", "'HI HI HI'"),
       ("test_int_times", "shout('a', 2)", "'A A'"),
       ("test_one", "shout('ok', '1')", "'OK'")],
      [("test_zero", "shout('x', '0')", "''"),
       ("test_int_three", "shout('go', 3)", "'GO GO GO'")]),
    T("te_digit_count", "type_error", False, "digits", "digit_count",
      "digit_count(123) raises TypeError: object of type 'int' has no len(); it should return 3.",
      '''
      def digit_count(n):
          """Return the number of decimal digits in a non-negative integer n."""
          return len(n)
      ''',
      '''
      def digit_count(n):
          """Return the number of decimal digits in a non-negative integer n."""
          return len(str(n))
      ''',
      [("test_three", "digit_count(123)", "3"),
       ("test_zero", "digit_count(0)", "1"),
       ("test_five", "digit_count(99999)", "5")],
      [("test_ten", "digit_count(10)", "2"),
       ("test_single", "digit_count(7)", "1")]),
    T("te_minutes", "type_error", False, "timeconv", "minutes",
      "minutes('125') raises TypeError: unsupported operand type(s) for //: 'str' and 'int'; it should return 2.",
      '''
      def minutes(seconds):
          """Return the whole minutes (rounded down) in seconds, a string such as '125'."""
          return seconds // 60
      ''',
      '''
      def minutes(seconds):
          """Return the whole minutes (rounded down) in seconds, a string such as '125'."""
          return int(seconds) // 60
      ''',
      [("test_two", "minutes('125')", "2"),
       ("test_under_one", "minutes('59')", "0"),
       ("test_ten", "minutes('600')", "10")],
      [("test_zero", "minutes('0')", "0"),
       ("test_just_over", "minutes('61')", "1")]),
    # symptom
    T("te_add_minutes", "type_error", False, "clock", "add_minutes",
      "add_minutes() crashes for every input.",
      '''
      def add_minutes(clock, minutes):
          """Add minutes to clock ('HH:MM') and return the new 'HH:MM', wrapping at 24 hours."""
          h, m = clock.split(":")
          total = (h * 60 + m + minutes) % 1440
          return f"{total // 60:02d}:{total % 60:02d}"
      ''',
      '''
      def add_minutes(clock, minutes):
          """Add minutes to clock ('HH:MM') and return the new 'HH:MM', wrapping at 24 hours."""
          h, m = clock.split(":")
          total = (int(h) * 60 + int(m) + minutes) % 1440
          return f"{total // 60:02d}:{total % 60:02d}"
      ''',
      [("test_next_hour", "add_minutes('09:30', 45)", "'10:15'"),
       ("test_midnight_wrap", "add_minutes('23:50', 20)", "'00:10'"),
       ("test_zero", "add_minutes('00:00', 0)", "'00:00'")],
      [("test_full_hour", "add_minutes('12:00', 60)", "'13:00'"),
       ("test_full_day", "add_minutes('01:05', 1440)", "'01:05'")],
      difficulty="symptom"),
    T("te_full_name", "type_error", False, "names", "full_name",
      "full_name() crashes for people without a middle name.",
      '''
      def full_name(first, middle, last):
          """Join the name parts with single spaces; middle may be None or '' and is skipped then."""
          return " ".join([first, middle, last])
      ''',
      '''
      def full_name(first, middle, last):
          """Join the name parts with single spaces; middle may be None or '' and is skipped then."""
          return " ".join(p for p in (first, middle, last) if p)
      ''',
      [("test_no_middle", "full_name('Ana', None, 'Lee')", "'Ana Lee'"),
       ("test_with_middle", "full_name('Bo', 'C', 'Du')", "'Bo C Du'"),
       ("test_short_names", "full_name('X', None, 'Y')", "'X Y'")],
      [("test_empty_middle", "full_name('Mo', '', 'Ra')", "'Mo Ra'"),
       ("test_other_middle", "full_name('Jo', 'Q', 'Lu')", "'Jo Q Lu'")],
      difficulty="symptom"),
    T("te_over_limit", "type_error", False, "limits", "over_limit",
      "over_limit() crashes when the limit comes from the config file.",
      '''
      def over_limit(values, limit):
          """Return the integer values strictly greater than limit (a numeric string read from config), in order."""
          return [v for v in values if v > limit]
      ''',
      '''
      def over_limit(values, limit):
          """Return the integer values strictly greater than limit (a numeric string read from config), in order."""
          return [v for v in values if v > int(limit)]
      ''',
      [("test_basic", "over_limit([1, 5, 10], '4')", "[5, 10]"),
       ("test_empty", "over_limit([], '0')", "[]"),
       ("test_equal", "over_limit([3, 3], '3')", "[]")],
      [("test_negative", "over_limit([-1, 0, 1], '0')", "[1]"),
       ("test_big", "over_limit([100], '99')", "[100]")],
      difficulty="symptom"),
    T("te_merge_tags", "type_error", False, "tags", "merge_tags",
      "merge_tags() crashes for some callers.",
      '''
      def merge_tags(a, b):
          """a and b are sets or lists of tags; return every tag found in either, once, sorted."""
          return sorted(a + b)
      ''',
      '''
      def merge_tags(a, b):
          """a and b are sets or lists of tags; return every tag found in either, once, sorted."""
          return sorted(set(a) | set(b))
      ''',
      [("test_sets", "merge_tags({'b', 'a'}, {'c'})", "['a', 'b', 'c']"),
       ("test_lists", "merge_tags(['x'], ['y'])", "['x', 'y']"),
       ("test_mixed", "merge_tags({'a'}, ['a'])", "['a']")],
      [("test_empty", "merge_tags(set(), set())", "[]"),
       ("test_duplicates", "merge_tags(['b', 'a'], ['a'])", "['a', 'b']")],
      difficulty="symptom"),
    # indirect
    T("te_count_above_mean", "type_error", False, "meanline", "count_above_mean",
      "count_above_mean('1,2,3') raises TypeError: object of type 'map' has no len().",
      '''
      def _ints(line):
          """Return the integers of a comma-separated line, as a list."""
          return map(int, line.split(","))


      def count_above_mean(line):
          """Count the integers of a comma-separated line that are strictly above their mean."""
          xs = _ints(line)
          mean = sum(xs) / len(xs)
          return sum(x > mean for x in xs)
      ''',
      '''
      def _ints(line):
          """Return the integers of a comma-separated line, as a list."""
          return list(map(int, line.split(",")))


      def count_above_mean(line):
          """Count the integers of a comma-separated line that are strictly above their mean."""
          xs = _ints(line)
          mean = sum(xs) / len(xs)
          return sum(x > mean for x in xs)
      ''',
      [("test_three", "count_above_mean('1,2,3')", "1"),
       ("test_equal", "count_above_mean('5,5')", "0"),
       ("test_outlier", "count_above_mean('1,1,1,9')", "1")],
      [("test_single", "count_above_mean('10')", "0"),
       ("test_negative", "count_above_mean('-2,0,2,4')", "2")],
      difficulty="indirect"),
    T("te_url", "type_error", False, "urls", "url",
      "url() crashes when a parameter value is a number.",
      '''
      def _query(params):
          """Return 'k=v' pairs sorted by key and joined by '&'."""
          return "&".join(k + "=" + v for k, v in sorted(params.items()))


      def url(path, params):
          """Return path, plus '?' and the query string when params is not empty."""
          return path + ("?" + _query(params) if params else "")
      ''',
      '''
      def _query(params):
          """Return 'k=v' pairs sorted by key and joined by '&'."""
          return "&".join(f"{k}={v}" for k, v in sorted(params.items()))


      def url(path, params):
          """Return path, plus '?' and the query string when params is not empty."""
          return path + ("?" + _query(params) if params else "")
      ''',
      [("test_int_value", "url('/a', {'page': 2})", "'/a?page=2'"),
       ("test_no_params", "url('/b', {})", "'/b'"),
       ("test_sorted_mixed", "url('/c', {'q': 'x', 'n': 1})", "'/c?n=1&q=x'")],
      [("test_str_only", "url('/d', {'z': 'y'})", "'/d?z=y'"),
       ("test_zero_value", "url('/e', {'a': 0, 'b': 10})", "'/e?a=0&b=10'")],
      difficulty="indirect"),
    T("te_latest_version", "type_error", False, "versions", "latest",
      "latest(['1.9', '1.10']) returns '1.9'.",
      '''
      def _key(version):
          """Return the parts of a dotted version as integers, for comparing."""
          return version.split(".")


      def latest(versions):
          """Return the highest of the dotted version strings."""
          return max(versions, key=_key)
      ''',
      '''
      def _key(version):
          """Return the parts of a dotted version as integers, for comparing."""
          return [int(p) for p in version.split(".")]


      def latest(versions):
          """Return the highest of the dotted version strings."""
          return max(versions, key=_key)
      ''',
      [("test_minor_ten", "latest(['1.9', '1.10'])", "'1.10'"),
       ("test_major", "latest(['2.0', '1.5'])", "'2.0'"),
       ("test_patch_ten", "latest(['0.2.10', '0.2.9'])", "'0.2.10'")],
      [("test_single", "latest(['3'])", "'3'"),
       ("test_major_ten", "latest(['10.0', '9.9'])", "'10.0'")],
      difficulty="indirect"),
    T("te_longest_name", "type_error", False, "cleaning", "longest_name",
      "longest_name() raises TypeError: object of type 'NoneType' has no len().",
      '''
      def _clean(name):
          """Return name without surrounding spaces."""
          name.strip()


      def longest_name(names):
          """Return the length of the longest name, ignoring surrounding spaces."""
          return max(len(_clean(n)) for n in names)
      ''',
      '''
      def _clean(name):
          """Return name without surrounding spaces."""
          return name.strip()


      def longest_name(names):
          """Return the length of the longest name, ignoring surrounding spaces."""
          return max(len(_clean(n)) for n in names)
      ''',
      [("test_padded", "longest_name([' ab ', 'c'])", "2"),
       ("test_single", "longest_name(['abc'])", "3"),
       ("test_spaces", "longest_name(['  x  ', 'yy'])", "2")],
      [("test_empty_name", "longest_name(['', 'a'])", "1"),
       ("test_inner_space", "longest_name([' long name '])", "9")],
      difficulty="indirect"),
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
    T("ho_obo_every_nth", "off_by_one", True, "every", "every_nth",
      "every_nth([1, 2, 3, 4, 5, 6], 2) returns [3, 5] instead of [2, 4, 6].",
      '''
      def every_nth(xs, n):
          """Return every n-th item of xs, starting with the n-th (1-based)."""
          return xs[n::n]
      ''',
      '''
      def every_nth(xs, n):
          """Return every n-th item of xs, starting with the n-th (1-based)."""
          return xs[n - 1::n]
      ''',
      [("test_pairs", "every_nth([1, 2, 3, 4, 5, 6], 2)", "[2, 4, 6]"),
       ("test_all", "every_nth([1, 2, 3], 1)", "[1, 2, 3]"),
       ("test_thirds", "every_nth([1, 2, 3, 4, 5, 6, 7], 3)", "[3, 6]")],
      [("test_empty", "every_nth([], 2)", "[]"),
       ("test_too_short", "every_nth(['a', 'b'], 3)", "[]")]),
    T("ho_obo_bar", "off_by_one", True, "bar", "bar",
      "Text bars drawn by bar() do not have the requested width.",
      '''
      def bar(filled, width):
          """Return a bar of exactly width characters: filled '#' characters, then '.' characters."""
          return "#" * filled + "." * (width - filled - 1)
      ''',
      '''
      def bar(filled, width):
          """Return a bar of exactly width characters: filled '#' characters, then '.' characters."""
          return "#" * filled + "." * (width - filled)
      ''',
      [("test_partial", "bar(2, 5)", "'##...'"),
       ("test_empty", "bar(0, 3)", "'...'"),
       ("test_full", "bar(4, 4)", "'####'")],
      [("test_half", "bar(1, 2)", "'#.'"),
       ("test_one_empty", "bar(0, 1)", "'.'")],
      difficulty="symptom"),
    T("ho_obo_last_field", "off_by_one", True, "fields", "last_field",
      "last_field('a, b, c') raises IndexError.",
      '''
      def _last_index(xs):
          """Index of the last item of a non-empty list."""
          return len(xs)


      def last_field(line):
          """Return the last comma-separated field of line, without surrounding spaces."""
          fields = line.split(",")
          return fields[_last_index(fields)].strip()
      ''',
      '''
      def _last_index(xs):
          """Index of the last item of a non-empty list."""
          return len(xs) - 1


      def last_field(line):
          """Return the last comma-separated field of line, without surrounding spaces."""
          fields = line.split(",")
          return fields[_last_index(fields)].strip()
      ''',
      [("test_three", "last_field('a, b, c')", "'c'"),
       ("test_one", "last_field('x')", "'x'"),
       ("test_no_spaces", "last_field('1,2')", "'2'")],
      [("test_padded", "last_field('a,b, last ')", "'last'"),
       ("test_only", "last_field(' only ')", "'only'")],
      difficulty="indirect"),
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
    T("ho_te_count_unique", "type_error", True, "rows", "count_unique",
      "count_unique([[1, 2], [1, 2], [3]]) raises TypeError: unhashable type: 'list'; it should return 2.",
      '''
      def count_unique(rows):
          """Return how many distinct rows there are; each row is a list, and order inside a row matters."""
          return len(set(rows))
      ''',
      '''
      def count_unique(rows):
          """Return how many distinct rows there are; each row is a list, and order inside a row matters."""
          return len(set(tuple(r) for r in rows))
      ''',
      [("test_dupes", "count_unique([[1, 2], [1, 2], [3]])", "2"),
       ("test_empty", "count_unique([])", "0"),
       ("test_distinct", "count_unique([[1], [2]])", "2")],
      [("test_one_row", "count_unique([[0, 0]])", "1"),
       ("test_order_matters", "count_unique([[1, 2], [2, 1]])", "2")]),
    T("ho_te_format_all", "type_error", True, "formatting", "format_all",
      "format_all() crashes whenever it is given values.",
      '''
      def format_all(values, template):
          """Fill template (a str.format template such as '<{}>') with each value; return the list of results."""
          return [template(v) for v in values]
      ''',
      '''
      def format_all(values, template):
          """Fill template (a str.format template such as '<{}>') with each value; return the list of results."""
          return [template.format(v) for v in values]
      ''',
      [("test_brackets", "format_all(['a', 'b'], '<{}>')", "['<a>', '<b>']"),
       ("test_empty", "format_all([], '{}')", "[]"),
       ("test_number", "format_all([1], 'n={}')", "['n=1']")],
      [("test_padded", "format_all([7], '{:03d}')", "['007']"),
       ("test_no_placeholder", "format_all(['x', 'y'], 'same')", "['same', 'same']")],
      difficulty="symptom"),
    T("ho_te_elapsed", "type_error", True, "elapsed", "elapsed",
      "elapsed(' 10', '25 ') raises TypeError: unsupported operand type(s) for -: 'str' and 'str'.",
      '''
      def _to_int(s):
          """Parse a numeric string that may have spaces around it."""
          return s.strip()


      def elapsed(start, end):
          """Return end - start for two numeric strings."""
          return _to_int(end) - _to_int(start)
      ''',
      '''
      def _to_int(s):
          """Parse a numeric string that may have spaces around it."""
          return int(s.strip())


      def elapsed(start, end):
          """Return end - start for two numeric strings."""
          return _to_int(end) - _to_int(start)
      ''',
      [("test_padded", "elapsed(' 10', '25 ')", "15"),
       ("test_zero", "elapsed('0', '0')", "0"),
       ("test_small", "elapsed('5', '7')", "2")],
      [("test_same", "elapsed('100', '100')", "0"),
       ("test_both_padded", "elapsed(' 1 ', ' 31 ')", "30")],
      difficulty="indirect"),
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
                "editable_paths": ["src/*.py"], "test_command": TEST_COMMAND, "difficulty": t["difficulty"]}
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
