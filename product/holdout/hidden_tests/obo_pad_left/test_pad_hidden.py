import unittest

from src.pad import pad_left


class TestPadLeftHidden(unittest.TestCase):
    def test_full(self):
        self.assertEqual(pad_left('abc', 3, '0'), 'abc')

    def test_empty(self):
        self.assertEqual(pad_left('', 2, '-'), '--')
