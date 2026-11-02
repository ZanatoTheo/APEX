import unittest

from src.chunks import chunk


class TestChunk(unittest.TestCase):
    def test_even(self):
        self.assertEqual(chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])

    def test_odd(self):
        self.assertEqual(chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])

    def test_short(self):
        self.assertEqual(chunk([1], 3), [[1]])
