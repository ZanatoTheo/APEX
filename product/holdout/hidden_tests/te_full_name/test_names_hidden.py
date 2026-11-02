import unittest

from src.names import full_name


class TestFullNameHidden(unittest.TestCase):
    def test_empty_middle(self):
        self.assertEqual(full_name('Mo', '', 'Ra'), 'Mo Ra')

    def test_other_middle(self):
        self.assertEqual(full_name('Jo', 'Q', 'Lu'), 'Jo Q Lu')
