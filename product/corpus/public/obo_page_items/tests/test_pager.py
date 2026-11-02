import unittest

from src.pager import page


class TestPage(unittest.TestCase):
    def test_first(self):
        self.assertEqual(page(list(range(10)), 1, 3), [0, 1, 2])

    def test_second(self):
        self.assertEqual(page(list(range(10)), 2, 3), [3, 4, 5])

    def test_partial(self):
        self.assertEqual(page(list(range(10)), 4, 3), [9])
