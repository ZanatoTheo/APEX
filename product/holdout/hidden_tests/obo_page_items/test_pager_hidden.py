import unittest

from src.pager import page


class TestPageHidden(unittest.TestCase):
    def test_short_list(self):
        self.assertEqual(page(['a', 'b'], 1, 5), ['a', 'b'])

    def test_third(self):
        self.assertEqual(page(list(range(6)), 3, 2), [4, 5])
