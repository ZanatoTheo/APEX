import unittest

from src.fields import last_field


class TestLastFieldHidden(unittest.TestCase):
    def test_padded(self):
        self.assertEqual(last_field('a,b, last '), 'last')

    def test_only(self):
        self.assertEqual(last_field(' only '), 'only')
