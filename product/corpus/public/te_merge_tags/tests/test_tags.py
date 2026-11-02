import unittest

from src.tags import merge_tags


class TestMergeTags(unittest.TestCase):
    def test_sets(self):
        self.assertEqual(merge_tags({'b', 'a'}, {'c'}), ['a', 'b', 'c'])

    def test_lists(self):
        self.assertEqual(merge_tags(['x'], ['y']), ['x', 'y'])

    def test_mixed(self):
        self.assertEqual(merge_tags({'a'}, ['a']), ['a'])
