import unittest

from src.upto import up_to


class TestUpTo(unittest.TestCase):
    def test_middle(self):
        self.assertEqual(up_to([1, 2, 3, 4], 2), [1, 2, 3])

    def test_first(self):
        self.assertEqual(up_to([1], 0), [1])

    def test_last(self):
        self.assertEqual(up_to(['a', 'b'], 1), ['a', 'b'])
