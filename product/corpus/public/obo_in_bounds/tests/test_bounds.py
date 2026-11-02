import unittest

from src.bounds import in_bounds


class TestInBounds(unittest.TestCase):
    def test_past_end(self):
        self.assertEqual(in_bounds(3, [1, 2, 3]), False)

    def test_first(self):
        self.assertEqual(in_bounds(0, [1]), True)

    def test_last(self):
        self.assertEqual(in_bounds(2, [1, 2, 3]), True)
