import unittest

from src.digits import digit_count


class TestDigitCountHidden(unittest.TestCase):
    def test_ten(self):
        self.assertEqual(digit_count(10), 2)

    def test_single(self):
        self.assertEqual(digit_count(7), 1)
