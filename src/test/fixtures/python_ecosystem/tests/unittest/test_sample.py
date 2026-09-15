import unittest


class SampleTest(unittest.TestCase):
    def setUp(self):
        self.value = 1

    def tearDown(self):
        self.value = 0

    def test_adds(self):
        self.assertEqual(self.value + 1, 2)
        self.assertTrue(self.value)


class Helper:
    def test_not_unittest(self):
        pass
