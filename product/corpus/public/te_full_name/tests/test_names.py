import unittest

from src.names import full_name


class TestFullName(unittest.TestCase):
    def test_no_middle(self):
        self.assertEqual(full_name('Ana', None, 'Lee'), 'Ana Lee')

    def test_with_middle(self):
        self.assertEqual(full_name('Bo', 'C', 'Du'), 'Bo C Du')

    def test_short_names(self):
        self.assertEqual(full_name('X', None, 'Y'), 'X Y')
