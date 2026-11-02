import unittest

from src.middle import middle


class TestMiddle(unittest.TestCase):
    def test_three(self):
        self.assertEqual(middle([1, 2, 3]), 2)

    def test_one(self):
        self.assertEqual(middle([5]), 5)

    def test_five(self):
        self.assertEqual(middle([1, 2, 3, 4, 5]), 3)
