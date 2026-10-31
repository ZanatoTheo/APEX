import unittest

from src.labels import label


class TestLabel(unittest.TestCase):
    def test_int(self):
        self.assertEqual(label('item', 3), 'item-3')

    def test_str(self):
        self.assertEqual(label('x', 'y'), 'x-y')

    def test_zero(self):
        self.assertEqual(label('a', 0), 'a-0')
