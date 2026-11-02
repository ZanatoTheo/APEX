import unittest

from apex import canonical
from apex.canonical import CanonicalError


class DumpsTest(unittest.TestCase):
    def test_sorted_compact_utf8(self):
        self.assertEqual(canonical.dumps({"b": 1, "a": [True, None, "é"]}),
                         '{"a":[true,null,"é"],"b":1}'.encode("utf-8"))

    def test_keys_sorted_by_utf16_code_units(self):
        # U+1F600 is a surrogate pair (0xD83D…) and sorts before U+FF61 in UTF-16, after it in code points.
        out = canonical.dumps({"｡": 1, "\U0001F600": 2}).decode("utf-8")
        self.assertLess(out.index("\U0001F600"), out.index("｡"))

    def test_control_chars_escaped(self):
        self.assertEqual(canonical.dumps("a\nb\x01\"\\"), b'"a\\nb\\u0001\\"\\\\"')

    def test_rejects_floats_nan_and_big_ints(self):
        for bad in (1.5, float("nan"), float("inf"), 2**53, -(2**53), {"x": [0.0]}):
            with self.assertRaises(CanonicalError, msg=repr(bad)):
                canonical.dumps(bad)
        canonical.dumps(2**53 - 1)

    def test_rejects_non_string_keys_and_unknown_types(self):
        for bad in ({1: "a"}, {"a": (1, 2)}, {"a": b"x"}):
            with self.assertRaises(CanonicalError):
                canonical.dumps(bad)


class LoadsTest(unittest.TestCase):
    def test_round_trip(self):
        value = {"z": [1, "two", {"k": None}], "a": False}
        self.assertEqual(canonical.loads(canonical.dumps(value)), value)

    def test_rejects_duplicate_keys(self):
        with self.assertRaises(CanonicalError):
            canonical.loads('{"a":1,"a":2}')

    def test_rejects_surrogates_huge_literals_and_deep_nesting(self):
        for bad in ('["\\ud800"]', "[" + "9" * 6000 + "]", "[" * 100000 + "]" * 100000, b"\xff"):
            with self.assertRaises(CanonicalError):
                canonical.loads(bad)
        with self.assertRaises(CanonicalError):
            canonical.dumps("\ud800")

    def test_rejects_nan_floats_and_big_ints(self):
        for bad in ('{"a":NaN}', '[Infinity]', '[1.0]', '[9007199254740993]'):
            with self.assertRaises(CanonicalError, msg=bad):
                canonical.loads(bad)


class HashTest(unittest.TestCase):
    def test_hash_is_key_order_independent(self):
        self.assertEqual(canonical.hash_obj({"a": 1, "b": 2}), canonical.hash_obj({"b": 2, "a": 1}))
        self.assertEqual(len(canonical.hash_obj([])), 64)


if __name__ == "__main__":
    unittest.main()
