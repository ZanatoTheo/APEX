import unittest

from src.trend import count_increases


class TestCountIncreases(unittest.TestCase):
    def test_rising(self):
        self.assertEqual(count_increases([1, 2, 3]), 2)

    def test_falling(self):
        self.assertEqual(count_increases([3, 2, 1]), 0)

    def test_mixed(self):
        self.assertEqual(count_increases([1, 3, 2, 4]), 2)
