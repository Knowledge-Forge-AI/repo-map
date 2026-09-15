import unittest

from repomap_kg.extractors.config.generic import extract_config_file_observations
from repomap_kg.extractors.config.python_support import (
    _is_secret_key,
    _python_bounded_string,
    _python_sequence_count,
)


class ConfigExtractorPythonBoundariesUnitTests(unittest.TestCase):
    def test_pyproject_toml_rich_metadata_and_dependencies(self):
        obs = extract_config_file_observations(
            "pyproject.toml",
            """[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "my-awesome-pkg"
version = "1.2.3"
dynamic = ["readme", "classifiers"]
dependencies = [
    "requests>=2.28.0",
    "pydantic>=2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "ruff>=0.1.0",
]
test = [
    "pytest-cov",
]
[tool.secret_section]
api_token = "super-secret-12345"
password = "hidden"
""",
        )
        self.assertEqual(obs[0].kind, "config.document")
        pyprojects = [o for o in obs if o.kind == "python.pyproject"]
        self.assertEqual(len(pyprojects), 1)
        meta = pyprojects[0].metadata
        self.assertEqual(meta["project_name"], "my-awesome-pkg")
        self.assertEqual(meta["project_version"], "1.2.3")
        self.assertIn("readme", meta["dynamic_metadata"])
        self.assertEqual(len(meta["optional_dependency_groups"]), 2)

        dep_groups = [o for o in obs if o.kind == "python.dependency_group"]
        self.assertEqual(len(dep_groups), 2)

    def test_requirements_txt_comprehensive_features(self):
        content = """# Requirements with index, constraints, hashes, and VCS
--index-url https://pypi.org/simple
--extra-index-url https://user:pass@private.repo.org/simple
-r common-requirements.txt
-c constraints.txt
--trusted-host private.repo.org
--hash=sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
requests>=2.28.0; python_version >= '3.10'
git+https://github.com/psf/black.git@main#egg=black
https://example.com/custom-package-1.0.tar.gz
"""
        obs = extract_config_file_observations("requirements.txt", content)
        self.assertEqual(obs[0].kind, "python.package_file")
        kinds = {o.kind for o in obs}
        self.assertIn("python.requirement", kinds)
        self.assertIn("python.reference", kinds)

    def test_pyproject_poetry_and_extras_boundaries(self):
        poetry_obs = extract_config_file_observations(
            "sub/pyproject.toml",
            """[tool.poetry]
name = "poetry-pkg"
version = "0.1.0"

[tool.poetry.dependencies]
python = "^3.10"
flask = "^2.0"

[tool.poetry.group.dev.dependencies]
pytest = "^7.0"
""",
        )
        self.assertEqual(poetry_obs[0].kind, "config.document")

    def test_python_support_helpers_boundaries(self):
        self.assertTrue(_is_secret_key("token"))
        self.assertFalse(_is_secret_key("normal_key"))
        self.assertEqual(_python_bounded_string("short"), "short")
        self.assertEqual(_python_bounded_string("a" * 300), "<string:300>")
        self.assertEqual(_python_sequence_count([1, 2, 3]), 3)
        self.assertEqual(_python_sequence_count(None), 0)
        self.assertEqual(_python_sequence_count("not-a-list"), 0)


if __name__ == "__main__":
    unittest.main()
