import unittest

from src.window import window_sum


class TestWindowSumHidden(unittest.TestCase):
    def test_k_one(self):
        self.assertEqual(window_sum([4, 0, 2], 1), [4, 0, 2])

    def test_longer(self):
        self.assertEqual(window_sum([1, 1, 1, 1, 1], 3), [3, 3, 3])
