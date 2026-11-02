import unittest

from src.clock import add_minutes


class TestAddMinutesHidden(unittest.TestCase):
    def test_full_hour(self):
        self.assertEqual(add_minutes('12:00', 60), '13:00')

    def test_full_day(self):
        self.assertEqual(add_minutes('01:05', 1440), '01:05')
