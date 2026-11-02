import unittest

from src.formatting import format_all


class TestFormatAll(unittest.TestCase):
    def test_brackets(self):
        self.assertEqual(format_all(['a', 'b'], '<{}>'), ['<a>', '<b>'])

    def test_empty(self):
        self.assertEqual(format_all([], '{}'), [])

    def test_number(self):
        self.assertEqual(format_all([1], 'n={}'), ['n=1'])
