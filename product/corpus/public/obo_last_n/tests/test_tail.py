import unittest

from src.tail import last_n


class TestLastN(unittest.TestCase):
    def test_two(self):
        self.assertEqual(last_n([1, 2, 3, 4], 2), [3, 4])

    def test_more_than_len(self):
        self.assertEqual(last_n([1, 2], 5), [1, 2])

    def test_zero(self):
        self.assertEqual(last_n([1, 2, 3], 0), [])
