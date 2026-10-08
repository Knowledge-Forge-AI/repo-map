"""Unit tests for the post-publication system test pause hook safety and lifecycle contract."""

from __future__ import annotations

import ast
import inspect
import os
from pathlib import Path
import unittest

from repomap_kg.storage.staged_ingestion import (
    _run_staged_full_refresh_admitted,
    _run_system_test_post_publication_pause,
)


class PostPublicationPauseHookUnitTests(unittest.TestCase):
    """Test safety validation, lifecycle cleaning, and placement of post-publication hook."""

    def setUp(self) -> None:
        self.orig_env = os.environ.get("_REPOMAP_SYSTEM_TEST_POST_PUBLICATION_PAUSE_PATH")

    def tearDown(self) -> None:
        if self.orig_env is None:
            os.environ.pop("_REPOMAP_SYSTEM_TEST_POST_PUBLICATION_PAUSE_PATH", None)
        else:
            os.environ["_REPOMAP_SYSTEM_TEST_POST_PUBLICATION_PAUSE_PATH"] = self.orig_env

    def test_placement_between_authority_before_publication_and_execute_final_transaction(self) -> None:
        source = inspect.getsource(_run_staged_full_refresh_admitted)
        tree = ast.parse(source)

        calls: list[tuple[int, str]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = None
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                if name in ("before_publication", "_run_system_test_post_publication_pause", "execute_final_transaction"):
                    calls.append((node.lineno, name))

        calls.sort(key=lambda x: x[0])
        names = [c[1] for c in calls]
        self.assertIn("before_publication", names)
        self.assertIn("_run_system_test_post_publication_pause", names)
        self.assertIn("execute_final_transaction", names)

        idx_before = names.index("before_publication")
        idx_pause = names.index("_run_system_test_post_publication_pause")
        idx_final = names.index("execute_final_transaction")

        self.assertLess(idx_before, idx_pause)
        self.assertLess(idx_pause, idx_final)

    def test_disabled_by_default(self) -> None:
        os.environ.pop("_REPOMAP_SYSTEM_TEST_POST_PUBLICATION_PAUSE_PATH", None)
        _run_system_test_post_publication_pause()

    def test_lifecycle_and_mode_safety(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as raw_dir:
            temp_dir = Path(raw_dir)
            temp_dir.chmod(0o700)
            pause_path = temp_dir / "pause_post_pub"
            ready_path = temp_dir / "pause_post_pub.ready"

            os.environ["_REPOMAP_SYSTEM_TEST_POST_PUBLICATION_PAUSE_PATH"] = str(pause_path)

            # In 0700 dir, should run and clean up ready file
            _run_system_test_post_publication_pause()
            self.assertFalse(ready_path.exists())

            # In non-0700 dir, should refuse and not create ready file
            temp_dir.chmod(0o755)
            _run_system_test_post_publication_pause()
            self.assertFalse(ready_path.exists())


if __name__ == "__main__":
    unittest.main()
