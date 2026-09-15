from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from repomap_kg.graph.discovery import classify_path, discover_repository


class DiscoveryClassificationUnitTests(unittest.TestCase):
    def test_classify_path_uses_extension_directory_and_executable_bit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            script = root / "bin" / "repomap-kg"
            script.parent.mkdir()
            script.write_text("#!/usr/bin/env python3\nprint('ok')\n")
            script.chmod(script.stat().st_mode | 0o111)

            file_info = classify_path(root, script)

        self.assertEqual(file_info.path, "bin/repomap-kg")
        self.assertEqual(file_info.language, "python")
        self.assertEqual(file_info.role, "entrypoint")
        self.assertTrue(file_info.executable)
        self.assertFalse(file_info.generated)
        self.assertRegex(file_info.content_hash, r"^[0-9a-f]{64}$")

    def test_discover_repository_skips_ignored_directories_and_sorts_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write(root / ".git" / "config", "ignored")
            self.write(root / "__pycache__" / "cached.pyc", "ignored")
            self.write(root / "src" / "main" / "python" / "app.py", "print('ok')\n")
            self.write(root / "docs" / "specs" / "architecture.md", "# Arch\n")
            self.write(root / "generated" / "report.json", "{}\n")

            files = discover_repository(root)

        self.assertEqual(
            [file_info.path for file_info in files],
            [
                "docs/specs/architecture.md",
                "generated/report.json",
                "src/main/python/app.py",
            ],
        )
        self.assertEqual(files[0].role, "documentation")
        self.assertEqual(files[1].role, "generated")
        self.assertTrue(files[1].generated)
        self.assertEqual(files[2].language, "python")
        self.assertEqual(files[2].role, "source")

    def test_discover_repository_skips_symlinks_that_escape_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            root = tmp / "repo"
            outside = tmp / "outside"
            self.write(root / "README.md", "# Fixture\n")
            self.write(outside / "linked.md", "# Outside\n")
            self.write(outside / "linked-dir" / "secret.md", "# Outside\n")
            try:
                (root / "linked.md").symlink_to(outside / "linked.md")
                (root / "linked-dir").symlink_to(outside / "linked-dir")
            except OSError as error:
                self.skipTest(f"symlink creation unavailable: {error}")

            files = discover_repository(root)

        self.assertEqual([file_info.path for file_info in files], ["README.md"])

    def test_discover_repository_skips_dangling_file_symlinks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write(root / "README.md", "# Fixture\n")
            try:
                (root / "missing-link").symlink_to(root / "missing-target")
            except OSError as error:
                self.skipTest(f"symlink creation unavailable: {error}")

            files = discover_repository(root)

        self.assertEqual([file_info.path for file_info in files], ["README.md"])

    def test_discover_repository_deduplicates_in_root_file_symlinks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write(root / "target.md", "# Fixture\n")
            try:
                (root / "linked.md").symlink_to(root / "target.md")
            except OSError as error:
                self.skipTest(f"symlink creation unavailable: {error}")

            files = discover_repository(root)

        self.assertEqual(
            [file_info.path for file_info in files],
            ["target.md"],
        )

    def test_discover_repository_applies_configured_file_directory_and_glob_excludes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write(root / "README.md", "# Fixture\n")
            self.write(root / "mcp" / "keep.md", "# Keep\n")
            self.write(root / "mcp" / "server-memory" / "memory.jsonl", "{}\n")
            self.write(root / "mcp" / "server-memory" / "serena" / "state.json", "{}\n")
            self.write(root / "result-abc" / "generated.txt", "generated\n")
            self.write(root / "src" / "app.py", "print('ok')\n")

            files = discover_repository(
                root,
                exclude_paths=(
                    "mcp/server-memory/memory.jsonl",
                    "mcp/server-memory/serena",
                    "result-*",
                ),
            )

        self.assertEqual(
            [file_info.path for file_info in files],
            [
                "README.md",
                "mcp/keep.md",
                "src/app.py",
            ],
        )

    def test_discover_repository_combines_configured_excludes_with_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write(root / ".serena" / "state.json", "{}\n")
            self.write(root / ".terraform" / "terraform.tfstate", "{}\n")
            self.write(root / "node_modules" / "fixture" / "index.js", "export {}\n")
            self.write(root / "result-abc" / "generated.txt", "generated\n")
            self.write(root / "src" / "app.py", "print('ok')\n")

            files = discover_repository(root, exclude_paths=("result-*",))

        self.assertEqual([file_info.path for file_info in files], ["src/app.py"])

    def test_discover_repository_rejects_unsafe_exclude_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write(root / "README.md", "# Fixture\n")

            for exclude_path in ("", "../outside", "/private/tmp/secret"):
                with self.subTest(exclude_path=exclude_path):
                    with self.assertRaises(ValueError):
                        discover_repository(root, exclude_paths=(exclude_path,))

    def test_discover_repository_does_not_open_excluded_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write(root / "README.md", "# Fixture\n")
            self.write(root / "mcp" / "server-memory" / "memory.jsonl", "{}\n")
            real_classify_path = classify_path

            def guarded_classify_path(repository_root, file_path, *, profile=None):
                relative = file_path.relative_to(repository_root).as_posix()
                if relative == "mcp/server-memory/memory.jsonl":
                    raise AssertionError("excluded file was opened")
                return real_classify_path(repository_root, file_path, profile=profile)

            with patch(
                "repomap_kg.graph.discovery.classify_path",
                side_effect=guarded_classify_path,
            ):
                files = discover_repository(
                    root,
                    exclude_paths=("mcp/server-memory/memory.jsonl",),
                )

        self.assertEqual([file_info.path for file_info in files], ["README.md"])

    def test_file_info_emits_raw_observation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "src" / "test" / "unit" / "python" / "app.unit.test.py"
            self.write(source, "import unittest\n")

            file_info = classify_path(root, source)
            observation = file_info.to_observation()

        self.assertEqual(observation.kind, "file")
        self.assertEqual(observation.source_id, file_info.path)
        self.assertEqual(observation.path, file_info.path)
        self.assertEqual(observation.confidence, "extracted")
        self.assertEqual(observation.extractor, "repo-discovery")
        self.assertEqual(observation.metadata["language"], "python")
        self.assertEqual(observation.metadata["role"], "test")
        self.assertEqual(observation.metadata["content_hash"], file_info.content_hash)

    def test_classify_path_recognizes_powershell_extensions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            script = root / "bin" / "maintain.ps1"
            module = root / "src" / "Example.Module.psm1"
            manifest = root / "src" / "Example.Module.psd1"
            self.write(script, "# Static fixture\n")
            self.write(module, "# Static fixture\n")
            self.write(manifest, "@{}\n")

            script_info = classify_path(root, script)
            module_info = classify_path(root, module)
            manifest_info = classify_path(root, manifest)

        self.assertEqual(script_info.language, "powershell")
        self.assertEqual(script_info.role, "entrypoint")
        self.assertEqual(module_info.language, "powershell")
        self.assertEqual(module_info.role, "source")
        self.assertEqual(manifest_info.language, "powershell")
        self.assertEqual(manifest_info.role, "config")

    def test_discover_repository_classifies_python_requirement_files_as_config(self):
        fixture_root = (
            Path(__file__).parents[4]
            / "fixtures"
            / "python_ecosystem"
            / "requirements"
            / "basic"
        )

        file_infos = discover_repository(fixture_root)

        by_path = {file_info.path: file_info for file_info in file_infos}
        self.assertEqual(by_path["requirements.txt"].language, "python")
        self.assertEqual(by_path["requirements.txt"].role, "config")
        self.assertEqual(by_path["dev-requirements.txt"].language, "python")
        self.assertEqual(by_path["dev-requirements.txt"].role, "config")
        self.assertEqual(by_path["test-requirements.txt"].language, "python")
        self.assertEqual(by_path["test-requirements.txt"].role, "config")

    def test_discover_repository_classifies_terraform_hcl_as_config(self):
        fixture_root = Path(__file__).parents[4] / "fixtures" / "terraform_hcl" / "basic"

        file_infos = discover_repository(fixture_root)

        by_path = {file_info.path: file_info for file_info in file_infos}
        self.assertEqual(by_path["main.tf"].language, "terraform")
        self.assertEqual(by_path["main.tf"].role, "config")
        self.assertEqual(by_path["prod.tfvars"].language, "terraform")
        self.assertEqual(by_path["prod.tfvars"].role, "config")
        self.assertEqual(by_path["terraform.tfvars"].language, "terraform")
        self.assertEqual(by_path["terraform.tfvars"].role, "config")
        self.assertEqual(by_path["dev.auto.tfvars"].language, "terraform")
        self.assertEqual(by_path["dev.auto.tfvars"].role, "config")

    def test_unknown_language_and_role_fall_back_honestly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            unknown = root / "mystery" / "blob.weird"
            self.write(unknown, "data\n")

            file_info = classify_path(root, unknown)

        self.assertEqual(file_info.language, "unknown")
        self.assertEqual(file_info.role, "unknown")

    def write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)



if __name__ == "__main__":
    unittest.main()
