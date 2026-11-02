import unittest

from src.nth import nth_from_end


class TestNthFromEndHidden(unittest.TestCase):
    def test_letters(self):
        self.assertEqual(nth_from_end(['a', 'b'], 1), 'b')

    def test_single(self):
        self.assertEqual(nth_from_end([9], 1), 9)
