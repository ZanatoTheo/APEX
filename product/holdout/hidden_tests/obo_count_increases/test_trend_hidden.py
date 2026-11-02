import unittest

from src.trend import count_increases


class TestCountIncreasesHidden(unittest.TestCase):
    def test_single(self):
        self.assertEqual(count_increases([5]), 0)

    def test_plateaus(self):
        self.assertEqual(count_increases([1, 1, 2, 2, 3]), 2)
