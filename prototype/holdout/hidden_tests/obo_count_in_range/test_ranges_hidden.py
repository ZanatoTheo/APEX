import unittest

from src.ranges import count_in_range


class TestCountInRangeHidden(unittest.TestCase):
    def test_both_ends(self):
        self.assertEqual(count_in_range([0, 5, 10], 0, 10), 3)

    def test_none(self):
        self.assertEqual(count_in_range([3, 3, 3], 1, 2), 0)
