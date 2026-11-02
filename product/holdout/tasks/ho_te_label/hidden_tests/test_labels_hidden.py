import unittest

from src.labels import label


class TestLabelHidden(unittest.TestCase):
    def test_empty_prefix(self):
        self.assertEqual(label('', 5), '-5')

    def test_two_digits(self):
        self.assertEqual(label('v', 10), 'v-10')
