import unittest

from src.meanline import count_above_mean


class TestCountAboveMean(unittest.TestCase):
    def test_three(self):
        self.assertEqual(count_above_mean('1,2,3'), 1)

    def test_equal(self):
        self.assertEqual(count_above_mean('5,5'), 0)

    def test_outlier(self):
        self.assertEqual(count_above_mean('1,1,1,9'), 1)
