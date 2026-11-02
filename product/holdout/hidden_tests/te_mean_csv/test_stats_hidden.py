import unittest

from src.stats import mean_of_csv


class TestMeanOfCsvHidden(unittest.TestCase):
    def test_floor(self):
        self.assertEqual(mean_of_csv('0,0,1'), 0)

    def test_odd_pair(self):
        self.assertEqual(mean_of_csv('5,6'), 5)
