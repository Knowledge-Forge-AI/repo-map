import unittest


class DogfoodTest(unittest.TestCase):
    def test_fixture_shape(self):
        self.assertTrue(True)


def test_pytest_fixture_shape():
    assert True
