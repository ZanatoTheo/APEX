import unittest

from src.versions import latest


class TestLatestHidden(unittest.TestCase):
    def test_single(self):
        self.assertEqual(latest(['3']), '3')

    def test_major_ten(self):
        self.assertEqual(latest(['10.0', '9.9']), '10.0')
