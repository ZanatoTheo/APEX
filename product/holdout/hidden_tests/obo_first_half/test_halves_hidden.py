import unittest

from src.halves import first_half


class TestFirstHalfHidden(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(first_half([]), [])

    def test_five(self):
        self.assertEqual(first_half([1, 2, 3, 4, 5]), [1, 2, 3])
