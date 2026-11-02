import unittest

from src.clock import add_minutes


class TestAddMinutes(unittest.TestCase):
    def test_next_hour(self):
        self.assertEqual(add_minutes('09:30', 45), '10:15')

    def test_midnight_wrap(self):
        self.assertEqual(add_minutes('23:50', 20), '00:10')

    def test_zero(self):
        self.assertEqual(add_minutes('00:00', 0), '00:00')
