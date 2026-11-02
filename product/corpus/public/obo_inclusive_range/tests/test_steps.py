import unittest

from src.steps import inclusive_range


class TestInclusiveRange(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(inclusive_range(1, 3), [1, 2, 3])

    def test_single(self):
        self.assertEqual(inclusive_range(0, 0), [0])

    def test_offset(self):
        self.assertEqual(inclusive_range(5, 7), [5, 6, 7])
