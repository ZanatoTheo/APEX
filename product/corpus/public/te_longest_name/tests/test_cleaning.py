import unittest

from src.cleaning import longest_name


class TestLongestName(unittest.TestCase):
    def test_padded(self):
        self.assertEqual(longest_name([' ab ', 'c']), 2)

    def test_single(self):
        self.assertEqual(longest_name(['abc']), 3)

    def test_spaces(self):
        self.assertEqual(longest_name(['  x  ', 'yy']), 2)
