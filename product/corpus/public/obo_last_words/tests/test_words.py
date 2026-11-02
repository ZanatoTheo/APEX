import unittest

from src.words import last_words


class TestLastWords(unittest.TestCase):
    def test_two(self):
        self.assertEqual(last_words('a b c d', 2), 'c d')

    def test_one(self):
        self.assertEqual(last_words('x y', 1), 'y')

    def test_all(self):
        self.assertEqual(last_words('one two three', 3), 'one two three')
