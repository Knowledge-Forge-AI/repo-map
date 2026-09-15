import unittest

from repomap_kg.extractors.languages.python import (
    PythonModuleIndex,
    extract_python_file_observations,
)


class PythonTestProfileUnitTests(unittest.TestCase):
    def test_unittest_and_pytest_profile_observations_are_static_and_bounded(self):
        content = (
            "import unittest\n"
            "import pytest\n"
            "\n"
            "class SampleTest(unittest.TestCase):\n"
            "    def setUp(self):\n"
            "        self.value = 1\n"
            "\n"
            "    def test_unit(self):\n"
            "        self.assertEqual(self.value, 1)\n"
            "        self.assertTrue(self.value)\n"
            "\n"
            "@pytest.fixture\n"
            "def client():\n"
            "    return object()\n"
            "\n"
            "@pytest.mark.parametrize('value', [1, 2])\n"
            "def test_pytest(client, value):\n"
            "    assert value in {1, 2}\n"
            "\n"
            "class TestFeature:\n"
            "    @pytest.mark.slow\n"
            "    def test_method(self):\n"
            "        assert True\n"
        )

        observations = extract_python_file_observations(
            "src/test/unit/python/pkg/test_sample.py",
            content,
            module_index=PythonModuleIndex.empty(),
        )
        kinds = {item.kind for item in observations}
        payload = "\n".join(item.to_json_line() for item in observations)
        test_file = next(item for item in observations if item.kind == "python.test_file")
        unittest_case = next(
            item for item in observations if item.kind == "python.unittest_case"
        )
        fixtures = [item for item in observations if item.kind == "python.pytest_fixture"]
        pytest_tests = [item for item in observations if item.kind == "python.pytest_test"]
        assertions = [item for item in observations if item.kind == "python.test_assertion"]

        self.assertTrue(
            {
                "python.module",
                "python.class",
                "python.method",
                "python.function",
                "python.test_file",
                "python.unittest_case",
                "python.test_method",
                "python.test_function",
                "python.pytest_test",
                "python.pytest_fixture",
                "python.test_parametrize",
                "python.test_assertion",
            }.issubset(kinds)
        )
        self.assertEqual(test_file.metadata["profile"], "python")
        self.assertIn("pytest", test_file.metadata["test_frameworks"])
        self.assertIn("unittest", test_file.metadata["test_frameworks"])
        self.assertEqual(unittest_case.metadata["class_name"], "SampleTest")
        self.assertEqual(unittest_case.metadata["test_method_count"], 1)
        self.assertEqual(fixtures[0].metadata["fixture_name"], "client")
        self.assertEqual({item.metadata["test_name"] for item in pytest_tests}, {"test_pytest", "test_method"})
        self.assertGreaterEqual(sum(item.metadata["assertion_count"] for item in assertions), 4)
        self.assertNotIn("fake", payload)
