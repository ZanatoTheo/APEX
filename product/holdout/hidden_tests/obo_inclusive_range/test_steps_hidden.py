import unittest

from src.steps import inclusive_range


class TestInclusiveRangeHidden(unittest.TestCase):
    def test_negative(self):
        self.assertEqual(inclusive_range(-1, 1), [-1, 0, 1])

    def test_reversed(self):
        self.assertEqual(inclusive_range(3, 2), [])
