import unittest

from src.ports import next_free_port


class TestNextFreePortHidden(unittest.TestCase):
    def test_unordered(self):
        self.assertEqual(next_free_port('443,80'), 444)

    def test_numeric_max(self):
        self.assertEqual(next_free_port('9,10'), 11)
