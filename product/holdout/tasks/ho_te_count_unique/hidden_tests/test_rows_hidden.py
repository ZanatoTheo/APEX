import unittest

from src.rows import count_unique


class TestCountUniqueHidden(unittest.TestCase):
    def test_one_row(self):
        self.assertEqual(count_unique([[0, 0]]), 1)

    def test_order_matters(self):
        self.assertEqual(count_unique([[1, 2], [2, 1]]), 2)
