import unittest

from src.ranges import count_in_range


class TestCountInRange(unittest.TestCase):
    def test_middle(self):
        self.assertEqual(count_in_range([1, 2, 3, 4, 5], 2, 4), 3)

    def test_empty(self):
        self.assertEqual(count_in_range([], 0, 10), 0)

    def test_single_point(self):
        self.assertEqual(count_in_range([10], 10, 10), 1)
