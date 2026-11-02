import unittest

from src.upto import up_to


class TestUpToHidden(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(up_to([5, 6, 7], 0), [5])

    def test_long(self):
        self.assertEqual(up_to([1, 2, 3, 4, 5], 3), [1, 2, 3, 4])
