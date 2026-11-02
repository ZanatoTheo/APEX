import unittest

from src.limits import over_limit


class TestOverLimitHidden(unittest.TestCase):
    def test_negative(self):
        self.assertEqual(over_limit([-1, 0, 1], '0'), [1])

    def test_big(self):
        self.assertEqual(over_limit([100], '99'), [100])
