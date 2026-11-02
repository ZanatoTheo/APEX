import unittest

from src.every import every_nth


class TestEveryNthHidden(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(every_nth([], 2), [])

    def test_too_short(self):
        self.assertEqual(every_nth(['a', 'b'], 3), [])
