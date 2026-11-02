import unittest

from src.bar import bar


class TestBar(unittest.TestCase):
    def test_partial(self):
        self.assertEqual(bar(2, 5), '##...')

    def test_empty(self):
        self.assertEqual(bar(0, 3), '...')

    def test_full(self):
        self.assertEqual(bar(4, 4), '####')
