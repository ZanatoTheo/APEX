import unittest

from src.bar import bar


class TestBarHidden(unittest.TestCase):
    def test_half(self):
        self.assertEqual(bar(1, 2), '#.')

    def test_one_empty(self):
        self.assertEqual(bar(0, 1), '.')
