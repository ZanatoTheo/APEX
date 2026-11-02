import unittest

from src.cleaning import longest_name


class TestLongestNameHidden(unittest.TestCase):
    def test_empty_name(self):
        self.assertEqual(longest_name(['', 'a']), 1)

    def test_inner_space(self):
        self.assertEqual(longest_name([' long name ']), 9)
