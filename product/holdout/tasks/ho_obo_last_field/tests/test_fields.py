import unittest

from src.fields import last_field


class TestLastField(unittest.TestCase):
    def test_three(self):
        self.assertEqual(last_field('a, b, c'), 'c')

    def test_one(self):
        self.assertEqual(last_field('x'), 'x')

    def test_no_spaces(self):
        self.assertEqual(last_field('1,2'), '2')
