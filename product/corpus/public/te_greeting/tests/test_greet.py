import unittest

from src.greet import greeting


class TestGreeting(unittest.TestCase):
    def test_int_age(self):
        self.assertEqual(greeting('Ana', 30), 'Hi Ana, you are 30')

    def test_small_age(self):
        self.assertEqual(greeting('Bo', 7), 'Hi Bo, you are 7')

    def test_str_age(self):
        self.assertEqual(greeting('Cy', '5'), 'Hi Cy, you are 5')
