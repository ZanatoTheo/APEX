import unittest

from src.formatting import format_all


class TestFormatAllHidden(unittest.TestCase):
    def test_padded(self):
        self.assertEqual(format_all([7], '{:03d}'), ['007'])

    def test_no_placeholder(self):
        self.assertEqual(format_all(['x', 'y'], 'same'), ['same', 'same'])
