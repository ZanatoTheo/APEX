import unittest

from src.limits import over_limit


class TestOverLimit(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(over_limit([1, 5, 10], '4'), [5, 10])

    def test_empty(self):
        self.assertEqual(over_limit([], '0'), [])

    def test_equal(self):
        self.assertEqual(over_limit([3, 3], '3'), [])
