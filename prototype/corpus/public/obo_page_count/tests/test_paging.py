import unittest

from src.paging import page_count


class TestPageCount(unittest.TestCase):
    def test_exact(self):
        self.assertEqual(page_count(10, 5), 2)

    def test_partial(self):
        self.assertEqual(page_count(11, 5), 3)

    def test_zero(self):
        self.assertEqual(page_count(0, 5), 0)
