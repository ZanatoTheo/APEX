import unittest

from src.countdown import countdown


class TestCountdown(unittest.TestCase):
    def test_three(self):
        self.assertEqual(countdown(3), [3, 2, 1])

    def test_one(self):
        self.assertEqual(countdown(1), [1])

    def test_five(self):
        self.assertEqual(countdown(5), [5, 4, 3, 2, 1])
