import unittest

from src.versions import latest


class TestLatest(unittest.TestCase):
    def test_minor_ten(self):
        self.assertEqual(latest(['1.9', '1.10']), '1.10')

    def test_major(self):
        self.assertEqual(latest(['2.0', '1.5']), '2.0')

    def test_patch_ten(self):
        self.assertEqual(latest(['0.2.10', '0.2.9']), '0.2.10')
