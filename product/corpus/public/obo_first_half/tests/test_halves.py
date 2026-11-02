import unittest

from src.halves import first_half


class TestFirstHalf(unittest.TestCase):
    def test_odd(self):
        self.assertEqual(first_half([1, 2, 3]), [1, 2])

    def test_even(self):
        self.assertEqual(first_half([1, 2, 3, 4]), [1, 2])

    def test_one(self):
        self.assertEqual(first_half([7]), [7])
