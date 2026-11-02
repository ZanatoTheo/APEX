import unittest

from src.paging import page_count


class TestPageCountHidden(unittest.TestCase):
    def test_one_item(self):
        self.assertEqual(page_count(1, 10), 1)

    def test_partial_tens(self):
        self.assertEqual(page_count(21, 10), 3)
