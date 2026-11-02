import unittest

from src.ports import next_free_port


class TestNextFreePort(unittest.TestCase):
    def test_two(self):
        self.assertEqual(next_free_port('80,443'), 444)

    def test_one(self):
        self.assertEqual(next_free_port('8080'), 8081)

    def test_small(self):
        self.assertEqual(next_free_port('1,2'), 3)
