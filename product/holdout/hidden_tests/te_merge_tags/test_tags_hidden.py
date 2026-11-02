import unittest

from src.tags import merge_tags


class TestMergeTagsHidden(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(merge_tags(set(), set()), [])

    def test_duplicates(self):
        self.assertEqual(merge_tags(['b', 'a'], ['a']), ['a', 'b'])
