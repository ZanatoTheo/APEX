import unittest

from src.prices import total_price


class TestTotalPrice(unittest.TestCase):
    def test_two_rows(self):
        self.assertEqual(total_price([('a', '3'), ('b', '4')]), 7)

    def test_empty(self):
        self.assertEqual(total_price([]), 0)

    def test_one_row(self):
        self.assertEqual(total_price([('x', '10')]), 10)
