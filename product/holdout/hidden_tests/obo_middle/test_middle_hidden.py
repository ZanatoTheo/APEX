import unittest

from src.middle import middle


class TestMiddleHidden(unittest.TestCase):
    def test_letters(self):
        self.assertEqual(middle(['a', 'b', 'c']), 'b')

    def test_seven(self):
        self.assertEqual(middle([9, 8, 7, 6, 5, 4, 3]), 6)
