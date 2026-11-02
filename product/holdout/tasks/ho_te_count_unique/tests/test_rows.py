import unittest

from src.rows import count_unique


class TestCountUnique(unittest.TestCase):
    def test_dupes(self):
        self.assertEqual(count_unique([[1, 2], [1, 2], [3]]), 2)

    def test_empty(self):
        self.assertEqual(count_unique([]), 0)

    def test_distinct(self):
        self.assertEqual(count_unique([[1], [2]]), 2)
