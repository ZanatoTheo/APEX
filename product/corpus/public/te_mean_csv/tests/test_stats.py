import unittest

from src.stats import mean_of_csv


class TestMeanOfCsv(unittest.TestCase):
    def test_three(self):
        self.assertEqual(mean_of_csv('1,2,3'), 2)

    def test_single(self):
        self.assertEqual(mean_of_csv('10'), 10)

    def test_pair(self):
        self.assertEqual(mean_of_csv('4,4'), 4)
