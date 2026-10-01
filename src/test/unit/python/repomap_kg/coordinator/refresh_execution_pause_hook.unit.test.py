"""Unit tests for the pre-publication system test pause hook safety and lifecycle contract."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
import unittest

from repomap_kg.coordinator._refresh_execution import (
    _is_safe_test_path,
    _run_system_test_pause,
)


class RefreshExecutionPauseHookUnitTests(unittest.TestCase):
    """Test safety validation and lifecycle cleaning for pre-publication pause hook."""

    def setUp(self) -> None:
        self.orig_env = os.environ.get("_REPOMAP_SYSTEM_TEST_PAUSE_PATH")

    def tearDown(self) -> None:
        if self.orig_env is None:
            os.environ.pop("_REPOMAP_SYSTEM_TEST_PAUSE_PATH", None)
        else:
            os.environ["_REPOMAP_SYSTEM_TEST_PAUSE_PATH"] = self.orig_env

    def test_safe_test_path_validation(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as raw_dir:
            temp_dir = Path(raw_dir)
            temp_dir.chmod(0o700)
            target = temp_dir / "pause_trigger"

            # Valid 0700 directory
            self.assertTrue(_is_safe_test_path(target))

            # Non-absolute path is refused
            self.assertFalse(_is_safe_test_path(Path("relative/pause_trigger")))

            # Non-0700 directory is refused
            temp_dir.chmod(0o755)
            self.assertFalse(_is_safe_test_path(target))
            temp_dir.chmod(0o777)
            self.assertFalse(_is_safe_test_path(target))

            # Restore 0700 for symlink tests
            temp_dir.chmod(0o700)

            # Symlink trigger path is refused
            real_file = temp_dir / "real_file"
            real_file.touch()
            symlink_target = temp_dir / "symlink_trigger"
            try:
                symlink_target.symlink_to(real_file)
                self.assertFalse(_is_safe_test_path(symlink_target))
            except OSError:
                pass

    def test_run_system_test_pause_disabled_by_default(self) -> None:
        os.environ.pop("_REPOMAP_SYSTEM_TEST_PAUSE_PATH", None)
        cap = SimpleNamespace(job_id="job-1", attempt=1)
        # Should return immediately without error
        _run_system_test_pause(cap)

    def test_run_system_test_pause_lifecycle_and_cleanup(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as raw_dir:
            temp_dir = Path(raw_dir)
            temp_dir.chmod(0o700)
            pause_path = temp_dir / "pause_trigger"
            ready_path = temp_dir / "pause_trigger.ready"

            # Do not create pause_path so the loop exits immediately
            os.environ["_REPOMAP_SYSTEM_TEST_PAUSE_PATH"] = str(pause_path)
            cap = SimpleNamespace(job_id="job-42", attempt=2)
            _run_system_test_pause(cap)

            # Self-cleaning ensures ready_path is removed upon completion
            self.assertFalse(ready_path.exists())


if __name__ == "__main__":
    unittest.main()
