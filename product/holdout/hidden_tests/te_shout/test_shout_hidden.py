import unittest

from src.shout import shout


class TestShoutHidden(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(shout('x', '0'), '')

    def test_int_three(self):
        self.assertEqual(shout('go', 3), 'GO GO GO')
