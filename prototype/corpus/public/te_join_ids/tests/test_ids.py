import unittest

from src.ids import join_ids


class TestJoinIds(unittest.TestCase):
    def test_two(self):
        self.assertEqual(join_ids([1, 2]), '1,2')

    def test_empty(self):
        self.assertEqual(join_ids([]), '')

    def test_one(self):
        self.assertEqual(join_ids([42]), '42')
