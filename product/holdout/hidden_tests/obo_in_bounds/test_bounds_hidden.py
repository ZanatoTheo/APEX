import unittest

from src.bounds import in_bounds


class TestInBoundsHidden(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(in_bounds(0, []), False)

    def test_negative(self):
        self.assertEqual(in_bounds(-1, [1]), False)
