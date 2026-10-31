import unittest

from src.tail import last_n


class TestLastNHidden(unittest.TestCase):
    def test_exact_len(self):
        self.assertEqual(last_n([7, 8, 9], 3), [7, 8, 9])

    def test_one(self):
        self.assertEqual(last_n(list(range(10)), 1), [9])
