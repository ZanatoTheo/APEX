import unittest

from src.greet import greeting


class TestGreetingHidden(unittest.TestCase):
    def test_empty_name(self):
        self.assertEqual(greeting('', 0), 'Hi , you are 0')

    def test_big_age(self):
        self.assertEqual(greeting('Zoe', 101), 'Hi Zoe, you are 101')
