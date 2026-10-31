import unittest

from src.window import window_sum


class TestWindowSum(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(window_sum([1, 2, 3, 4], 2), [3, 5, 7])

    def test_whole_list(self):
        self.assertEqual(window_sum([5, 5], 2), [10])

    def test_k_too_big(self):
        self.assertEqual(window_sum([1], 2), [])
