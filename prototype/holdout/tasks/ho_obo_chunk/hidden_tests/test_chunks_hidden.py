import unittest

from src.chunks import chunk


class TestChunkHidden(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(chunk([], 2), [])

    def test_singles(self):
        self.assertEqual(chunk([1, 2, 3], 1), [[1], [2], [3]])
