import unittest

from src.countdown import countdown


class TestCountdownHidden(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(countdown(0), [])

    def test_two(self):
        self.assertEqual(countdown(2), [2, 1])
