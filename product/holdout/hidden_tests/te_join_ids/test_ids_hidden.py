import unittest

from src.ids import join_ids


class TestJoinIdsHidden(unittest.TestCase):
    def test_three(self):
        self.assertEqual(join_ids([0, 10, 200]), '0,10,200')

    def test_repeat(self):
        self.assertEqual(join_ids([7, 7]), '7,7')
