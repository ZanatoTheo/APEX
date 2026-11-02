import unittest

from src.textpos import line_number


class TestLineNumber(unittest.TestCase):
    def test_start(self):
        self.assertEqual(line_number('ab\ncd', 0), 1)

    def test_second_line(self):
        self.assertEqual(line_number('ab\ncd', 3), 2)

    def test_on_newline(self):
        self.assertEqual(line_number('ab\ncd', 2), 1)
