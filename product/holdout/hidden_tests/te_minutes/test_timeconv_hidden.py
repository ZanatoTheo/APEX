import unittest

from src.timeconv import minutes


class TestMinutesHidden(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(minutes('0'), 0)

    def test_just_over(self):
        self.assertEqual(minutes('61'), 1)
