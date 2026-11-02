import unittest

from src.textpos import line_number


class TestLineNumberHidden(unittest.TestCase):
    def test_one_line(self):
        self.assertEqual(line_number('xyz', 2), 1)

    def test_blank_lines(self):
        self.assertEqual(line_number('\n\n', 1), 2)
