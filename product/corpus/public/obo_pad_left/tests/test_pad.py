import unittest

from src.pad import pad_left


class TestPadLeft(unittest.TestCase):
    def test_zeros(self):
        self.assertEqual(pad_left('7', 3, '0'), '007')

    def test_dots(self):
        self.assertEqual(pad_left('ab', 4, '.'), '..ab')

    def test_one(self):
        self.assertEqual(pad_left('x', 2, ' '), ' x')
