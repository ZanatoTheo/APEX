import unittest

from src.shout import shout


class TestShout(unittest.TestCase):
    def test_str_times(self):
        self.assertEqual(shout('hi', '3'), 'HI HI HI')

    def test_int_times(self):
        self.assertEqual(shout('a', 2), 'A A')

    def test_one(self):
        self.assertEqual(shout('ok', '1'), 'OK')
