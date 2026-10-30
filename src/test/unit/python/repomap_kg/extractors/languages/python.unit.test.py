import tempfile
import unittest
from pathlib import Path

from common_lore_index.extractors.languages.python import (
    PythonModuleIndex,
    extract_python_file_observations,
    importable_module_name,
    module_name_from_suffix,
    package_roots,
    pyproject_package_roots,
)


class PythonExtractorUnitTests(unittest.TestCase):
    def test_importable_module_name_supports_src_main_package_layout(self):
        self.assertEqual(
            importable_module_name("src/main/python/common_lore_index/cli.py"),
            "common_lore_index.cli",
        )
        self.assertEqual(
            importable_module_name("src/main/python/common_lore_index/__init__.py"),
            "common_lore_index",
        )

    def test_importable_module_name_supports_src_test_python_layout(self):
        self.assertEqual(
            importable_module_name(
                "src/test/unit/python/repomap_kg/test_cli.unit.test.py"
            ),
            "common_lore_index.test_cli.unit.test",
        )
        self.assertEqual(
            importable_module_name(
                "src/test/int/python/repomap_kg/test_storage.int.test.py"
            ),
            "common_lore_index.test_storage.int.test",
        )

    def test_importable_module_name_supports_pyproject_package_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "pyproject.toml").write_text(
                "[tool.setuptools]\n"
                "package-dir = { \"\" = \"lib/python\" }\n",
                encoding="utf-8",
            )

            self.assertEqual(
                importable_module_name(
                    "lib/python/acme/app.py",
                    repository_root=root,
                ),
                "acme.app",
            )

    def test_module_name_helpers_handle_init_files_and_non_python_files(self):
        self.assertEqual(module_name_from_suffix("pkg/__init__.py"), "pkg")
        self.assertIsNone(module_name_from_suffix("__init__.py"))
        self.assertIsNone(importable_module_name("README.md"))

    def test_pyproject_package_roots_ignore_missing_or_malformed_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.assertEqual(pyproject_package_roots(root), ())

            (root / "pyproject.toml").write_text("[tool.setuptools\n")
            self.assertEqual(pyproject_package_roots(root), ())

    def test_package_roots_include_defaults_pyproject_and_test_layouts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "pyproject.toml").write_text(
                "[tool.setuptools]\n"
                "package-dir = { \"\" = \"lib/python\" }\n",
                encoding="utf-8",
            )

            roots = package_roots(root)

        self.assertIn("src/main/python", roots)
        self.assertIn("lib/python", roots)
        self.assertIn("src/test/unit/python", roots)
        self.assertIn("src/test/int/python", roots)

    def test_python_module_index_discovers_known_modules_from_paths(self):
        index = PythonModuleIndex.from_python_paths(
            [
                "src/main/python/pkg/__init__.py",
                "src/main/python/pkg/app.py",
                "README.md",
            ]
        )

        self.assertTrue(index.has_module("pkg"))
        self.assertTrue(index.has_module("pkg.app"))
        self.assertEqual(index.module_to_path["pkg.app"], "src/main/python/pkg/app.py")
        self.assertEqual(index.path_to_module["src/main/python/pkg/__init__.py"], "pkg")

    def test_extract_python_file_observations_finds_symbols_and_imports(self):
        content = (
            "import os\n"
            "from common_lore_index import storage as storage_mod\n"
            "from . import sibling\n"
            "from .subpackage import helper\n"
            "\n"
            "class Demo:\n"
            "    def method(self):\n"
            "        return storage_mod\n"
            "\n"
            "async def build():\n"
            "    return os.name\n"
        )
        module_index = PythonModuleIndex.from_modules(
            {
                "common_lore_index.cli": "src/main/python/common_lore_index/cli.py",
                "common_lore_index.storage": "src/main/python/common_lore_index/storage.py",
                "common_lore_index.sibling": "src/main/python/common_lore_index/sibling.py",
                "common_lore_index.subpackage.helper": (
                    "src/main/python/common_lore_index/subpackage/helper.py"
                ),
            }
        )

        observations = extract_python_file_observations(
            "src/main/python/common_lore_index/cli.py",
            content,
            module_index=module_index,
        )

        self.assertEqual(
            [observation.kind for observation in observations],
            [
                "python.module",
                "python.import",
                "python.import",
                "python.import",
                "python.import",
                "python.class",
                "python.method",
                "python.function",
            ],
        )
        self.assertEqual(observations[0].name, "common_lore_index.cli")
        self.assertEqual(observations[0].start_line, 1)
        self.assertEqual(observations[0].end_line, 11)

        imports = [item for item in observations if item.kind == "python.import"]
        self.assertEqual(
            [(item.name, item.target, item.metadata["resolution"]) for item in imports],
            [
                ("os", "external:python.module:os", "external"),
                (
                    "common_lore_index.storage",
                    "python.module:common_lore_index.storage",
                    "local",
                ),
                (
                    "common_lore_index.sibling",
                    "python.module:common_lore_index.sibling",
                    "local",
                ),
                (
                    "common_lore_index.subpackage.helper",
                    "python.module:common_lore_index.subpackage.helper",
                    "local",
                ),
            ],
        )

        symbol_targets = {
            observation.kind: observation.target
            for observation in observations
            if observation.kind in {"python.class", "python.function"}
        }
        self.assertEqual(
            symbol_targets,
            {
                "python.class": "python.class:common_lore_index.cli:Demo",
                "python.function": "python.function:common_lore_index.cli:build",
            },
        )
        method = next(item for item in observations if item.kind == "python.method")
        self.assertEqual(method.target, "python.method:common_lore_index.cli:Demo:method")
        self.assertEqual(method.metadata["class"], "Demo")

    def test_extract_python_file_observations_reports_unresolved_relative_import(self):
        observations = extract_python_file_observations(
            "scratch.py",
            "from . import sibling\n",
            module_index=PythonModuleIndex.empty(),
        )

        self.assertEqual([item.kind for item in observations], ["python.module", "python.import"])
        import_observation = observations[1]
        self.assertEqual(
            import_observation.target,
            "unknown:python.module:missing-package-context",
        )
        self.assertEqual(import_observation.metadata["resolution"], "unknown")

    def test_extract_python_file_observations_handles_local_import_and_from_fallbacks(self):
        module_index = PythonModuleIndex.from_modules(
            {
                "pkg": "src/main/python/pkg/__init__.py",
                "pkg.lib.helper": "src/main/python/pkg/lib/helper.py",
                "pkg.sibling": "src/main/python/pkg/sibling.py",
            }
        )
        content = (
            "import pkg.lib.helper\n"
            "from pkg import CONSTANT\n"
            "from . import missing\n"
            "from . import *\n"
        )

        observations = extract_python_file_observations(
            "src/main/python/pkg/app.py",
            content,
            module_index=module_index,
        )
        imports = [item for item in observations if item.kind == "python.import"]

        self.assertEqual(
            [(item.name, item.target, item.metadata["resolution"]) for item in imports],
            [
                (
                    "pkg.lib.helper",
                    "python.module:pkg.lib.helper",
                    "local",
                ),
                ("pkg", "python.module:pkg", "local"),
                (
                    "pkg.missing",
                    "unknown:python.module:missing-module",
                    "unknown",
                ),
                (
                    "pkg",
                    "python.module:pkg",
                    "local",
                ),
            ],
        )

    def test_extract_python_file_observations_handles_external_from_and_level_escape(self):
        content = (
            "from pathlib import Path\n"
            "from .. import missing\n"
        )

        observations = extract_python_file_observations(
            "src/main/python/pkg/app.py",
            content,
            module_index=PythonModuleIndex.empty(),
        )
        imports = [item for item in observations if item.kind == "python.import"]

        self.assertEqual(
            [(item.name, item.target, item.metadata["resolution"]) for item in imports],
            [
                ("pathlib", "external:python.module:pathlib", "external"),
                (
                    "missing",
                    "unknown:python.module:missing-package-context",
                    "unknown",
                ),
            ],
        )

    def test_extract_python_file_observations_captures_decorators_bases_and_async(self):
        content = (
            "class Base:\n"
            "    pass\n"
            "\n"
            "@decorator\n"
            "class Service(Base):\n"
            "    @classmethod\n"
            "    async def run(cls):\n"
            "        return cls\n"
            "\n"
            "@decorator\n"
            "async def build():\n"
            "    return Service\n"
        )

        observations = extract_python_file_observations(
            "src/main/python/pkg/app.py",
            content,
            module_index=PythonModuleIndex.empty(),
        )

        service = next(
            item for item in observations
            if item.kind == "python.class" and item.name == "Service"
        )
        method = next(item for item in observations if item.kind == "python.method")
        function = next(
            item for item in observations
            if item.kind == "python.function" and item.name == "build"
        )
        self.assertEqual(service.metadata["bases"], ["Base"])
        self.assertEqual(service.metadata["decorators"], ["decorator"])
        self.assertTrue(method.metadata["async"])
        self.assertEqual(method.metadata["decorators"], ["classmethod"])
        self.assertTrue(function.metadata["async"])
        self.assertEqual(function.metadata["decorators"], ["decorator"])

    def test_package_roots_ignore_non_mapping_package_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "pyproject.toml").write_text(
                "[tool.setuptools]\npackage-dir = \"src\"\n",
                encoding="utf-8",
            )

            self.assertEqual(pyproject_package_roots(root), ())

    def test_extract_python_file_observations_ignores_non_importable_paths(self):
        observations = extract_python_file_observations(
            "README.md",
            "not python",
            module_index=PythonModuleIndex.empty(),
        )

        self.assertEqual(observations, ())

    def test_extract_python_file_observations_handles_empty_module(self):
        observations = extract_python_file_observations(
            "src/main/python/empty.py",
            "",
            module_index=PythonModuleIndex.empty(),
        )

        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].kind, "python.module")
        self.assertEqual(observations[0].end_line, 1)

    def test_extract_python_file_observations_reports_syntax_errors_without_source(self):
        observations = extract_python_file_observations(
            "src/main/python/broken.py",
            "def nope(:\n",
            module_index=PythonModuleIndex.empty(),
        )

        self.assertEqual([item.kind for item in observations], ["python.parse_error"])
        self.assertEqual(observations[0].metadata["error_kind"], "malformed-python")
        self.assertNotIn("def nope", str(observations[0].metadata))

if __name__ == "__main__":
    unittest.main()
