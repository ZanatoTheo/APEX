import unittest

from src.elapsed import elapsed


class TestElapsed(unittest.TestCase):
    def test_padded(self):
        self.assertEqual(elapsed(' 10', '25 '), 15)

    def test_zero(self):
        self.assertEqual(elapsed('0', '0'), 0)

    def test_small(self):
        self.assertEqual(elapsed('5', '7'), 2)
