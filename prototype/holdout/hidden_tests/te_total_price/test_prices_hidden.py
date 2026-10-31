import unittest

from src.prices import total_price


class TestTotalPriceHidden(unittest.TestCase):
    def test_zeros(self):
        self.assertEqual(total_price([('a', '0'), ('b', '0')]), 0)

    def test_three(self):
        self.assertEqual(total_price([('p', '100'), ('q', '1'), ('r', '2')]), 103)
