import unittest

from src.words import last_words


class TestLastWordsHidden(unittest.TestCase):
    def test_more_than_all(self):
        self.assertEqual(last_words('a b', 5), 'a b')

    def test_four(self):
        self.assertEqual(last_words('p q r s t', 4), 'q r s t')
