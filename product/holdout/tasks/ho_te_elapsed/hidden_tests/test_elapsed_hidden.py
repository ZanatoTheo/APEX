import unittest

from src.elapsed import elapsed


class TestElapsedHidden(unittest.TestCase):
    def test_same(self):
        self.assertEqual(elapsed('100', '100'), 0)

    def test_both_padded(self):
        self.assertEqual(elapsed(' 1 ', ' 31 '), 30)
