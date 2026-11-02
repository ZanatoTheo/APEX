import unittest

from src.meanline import count_above_mean


class TestCountAboveMeanHidden(unittest.TestCase):
    def test_single(self):
        self.assertEqual(count_above_mean('10'), 0)

    def test_negative(self):
        self.assertEqual(count_above_mean('-2,0,2,4'), 2)
