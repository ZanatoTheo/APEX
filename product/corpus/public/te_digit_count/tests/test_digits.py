import unittest

from src.digits import digit_count


class TestDigitCount(unittest.TestCase):
    def test_three(self):
        self.assertEqual(digit_count(123), 3)

    def test_zero(self):
        self.assertEqual(digit_count(0), 1)

    def test_five(self):
        self.assertEqual(digit_count(99999), 5)
