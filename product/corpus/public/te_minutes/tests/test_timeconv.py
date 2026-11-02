import unittest

from src.timeconv import minutes


class TestMinutes(unittest.TestCase):
    def test_two(self):
        self.assertEqual(minutes('125'), 2)

    def test_under_one(self):
        self.assertEqual(minutes('59'), 0)

    def test_ten(self):
        self.assertEqual(minutes('600'), 10)
