import unittest

from src.nth import nth_from_end


class TestNthFromEnd(unittest.TestCase):
    def test_last(self):
        self.assertEqual(nth_from_end([1, 2, 3], 1), 3)

    def test_first(self):
        self.assertEqual(nth_from_end([1, 2, 3], 3), 1)

    def test_pair(self):
        self.assertEqual(nth_from_end([5, 6], 2), 5)
