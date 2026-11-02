import unittest

from src.urls import url


class TestUrl(unittest.TestCase):
    def test_int_value(self):
        self.assertEqual(url('/a', {'page': 2}), '/a?page=2')

    def test_no_params(self):
        self.assertEqual(url('/b', {}), '/b')

    def test_sorted_mixed(self):
        self.assertEqual(url('/c', {'q': 'x', 'n': 1}), '/c?n=1&q=x')
