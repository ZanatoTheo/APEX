import unittest

from src.urls import url


class TestUrlHidden(unittest.TestCase):
    def test_str_only(self):
        self.assertEqual(url('/d', {'z': 'y'}), '/d?z=y')

    def test_zero_value(self):
        self.assertEqual(url('/e', {'a': 0, 'b': 10}), '/e?a=0&b=10')
