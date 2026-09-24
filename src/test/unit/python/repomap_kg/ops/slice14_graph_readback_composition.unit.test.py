"""Migrated Slice14 isolated controls; zero new integration credit."""

from __future__ import annotations
import os
from pathlib import Path
import tempfile
import unittest
from repomap_kg.ops.preflight import _scan_preflight_root
from repomap_test_support.test_scratch import select_scratch_root


class Slice14GraphReadbackCompositionUnitTests(unittest.TestCase):
    def test_s14_b07_ops_preflight_root_scanning_symlinks(self) -> None:
        """Preflight root scanner detects internal and external symlinks."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmp:
            root = Path(tmp) / "scan_root"
            outside = Path(tmp) / "outside"
            root.mkdir()
            outside.mkdir()

            internal_file = root / "real_file.py"
            internal_file.write_text("print('hi')\n", encoding="utf-8")

            outside_file = outside / "outside_target.py"
            outside_file.write_text("print('outside')\n", encoding="utf-8")

            internal_link = root / "link_internal.py"
            os.symlink(internal_file.name, internal_link)

            external_link = root / "link_external.py"
            os.symlink(str(outside_file), external_link)

            scan = _scan_preflight_root(root, ())
            self.assertEqual(scan["symlink_count"], 2)
            self.assertEqual(scan["symlinks_skipped_outside_root"], 1)
            self.assertEqual(scan["files_considered"], 3)
            self.assertEqual(scan["files_included"], 2)
            self.assertEqual(scan["files_skipped"], 1)


    def test_s14_b08_ops_preflight_root_scanning_generated_and_excludes(self) -> None:
        """Preflight root scanner detects generated output, custom excludes, and secret-like names."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmp:
            root = Path(tmp) / "scan_root"
            root.mkdir()

            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("print('app')\n", encoding="utf-8")

            (root / "build").mkdir()
            (root / "build" / "output.o").write_text("binary", encoding="utf-8")

            (root / "custom_ignored").mkdir()
            (root / "custom_ignored" / "skip.txt").write_text("ignore", encoding="utf-8")

            (root / "src" / "api_key.json").write_text('{"token": "xyz"}', encoding="utf-8")
            (root / "src" / "auth_secret.txt").write_text("secret_value", encoding="utf-8")

            scan = _scan_preflight_root(root, ("custom_ignored",))
            self.assertGreaterEqual(scan["generated_output_skips"], 1)
            self.assertGreaterEqual(scan["secret_like_path_count"], 2)
            self.assertEqual(scan["configured_exclude_hit_counts"].get("custom_ignored", 0), 1)
            self.assertGreaterEqual(scan["directories_skipped"], 2)
