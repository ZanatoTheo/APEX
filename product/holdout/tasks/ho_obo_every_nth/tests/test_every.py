import unittest

from src.every import every_nth


class TestEveryNth(unittest.TestCase):
    def test_pairs(self):
        self.assertEqual(every_nth([1, 2, 3, 4, 5, 6], 2), [2, 4, 6])

    def test_all(self):
        self.assertEqual(every_nth([1, 2, 3], 1), [1, 2, 3])

    def test_thirds(self):
        self.assertEqual(every_nth([1, 2, 3, 4, 5, 6, 7], 3), [3, 6])
