"""Unit tests for the pre-publication system test pause hook safety and lifecycle contract."""

from __future__ import annotations

import os
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

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
        import tempfile
        with tempfile.TemporaryDirectory() as raw_dir:
            fake_ready = Path(raw_dir) / "ready"
            with patch("repomap_kg.coordinator._refresh_execution._SYSTEM_TEST_READY_PATH", fake_ready):
                os.environ.pop("_REPOMAP_SYSTEM_TEST_PAUSE_PATH", None)
                cap = SimpleNamespace(job_id="job-1", attempt=1)
                _run_system_test_pause(cap)
                self.assertFalse(fake_ready.exists())

    def test_fixed_legacy_path_rejected_outside_container_authority(self) -> None:
        import tempfile
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as raw_dir:
            temp_dir = Path(raw_dir)
            temp_dir.chmod(0o700)
            fake_pause = temp_dir / "system_pause_trigger"
            fake_ready = temp_dir / "system_pause_trigger.ready"
            os.environ["_REPOMAP_SYSTEM_TEST_PAUSE_PATH"] = str(fake_pause)
            cap = SimpleNamespace(job_id="job-legacy-rej", attempt=1)
            mock_marker = MagicMock()
            mock_marker.is_file.return_value = False
            with (
                patch("repomap_kg.coordinator._refresh_execution._SYSTEM_TEST_PAUSE_PATH", fake_pause),
                patch("repomap_kg.coordinator._refresh_execution._SYSTEM_TEST_READY_PATH", fake_ready),
                patch("repomap_kg.coordinator._refresh_execution.CONTAINER_INTERNAL_MARKER", mock_marker),
            ):
                _run_system_test_pause(cap)
                self.assertFalse(fake_ready.exists())

    def test_fixed_legacy_path_accepted_under_container_authority(self) -> None:
        import tempfile
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as raw_dir:
            temp_dir = Path(raw_dir)
            temp_dir.chmod(0o700)
            fake_pause = temp_dir / "system_pause_trigger"
            fake_ready = temp_dir / "system_pause_trigger.ready"
            os.environ["_REPOMAP_SYSTEM_TEST_PAUSE_PATH"] = str(fake_pause)
            cap = SimpleNamespace(job_id="job-legacy-acc", attempt=4)
            fake_pause.touch()
            observed_content: list[str] = []
            mock_marker = MagicMock()
            mock_marker.is_file.return_value = True
            with (
                patch("repomap_kg.coordinator._refresh_execution._SYSTEM_TEST_PAUSE_PATH", fake_pause),
                patch("repomap_kg.coordinator._refresh_execution._SYSTEM_TEST_READY_PATH", fake_ready),
                patch("repomap_kg.coordinator._refresh_execution.CONTAINER_INTERNAL_MARKER", mock_marker),
            ):
                thread = threading.Thread(target=_run_system_test_pause, args=(cap,))
                thread.start()
                deadline = time.monotonic() + 5.0
                while time.monotonic() < deadline:
                    if fake_ready.exists():
                        text = fake_ready.read_text(encoding="utf-8")
                        if "job_id=" in text:
                            observed_content.append(text)
                            break
                    time.sleep(0.02)
                self.assertTrue(len(observed_content) > 0)
                fake_pause.unlink(missing_ok=True)
                thread.join(timeout=5.0)
                self.assertFalse(thread.is_alive())
            self.assertIn("job_id=job-legacy-acc\n", observed_content[0])
            self.assertIn("attempt=4\n", observed_content[0])
            self.assertFalse(fake_ready.exists())

    def test_ready_marker_visible_during_pause_and_removed_after_completion(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as raw_dir:
            temp_dir = Path(raw_dir)
            temp_dir.chmod(0o700)
            pause_path = temp_dir / "pause_trigger"
            ready_path = temp_dir / "pause_trigger.ready"

            pause_path.touch()
            os.environ["_REPOMAP_SYSTEM_TEST_PAUSE_PATH"] = str(pause_path)
            cap = SimpleNamespace(job_id="job-vis", attempt=5)
            thread = threading.Thread(target=_run_system_test_pause, args=(cap,))
            thread.start()
            try:
                deadline = time.monotonic() + 5.0
                content = ""
                while time.monotonic() < deadline:
                    if ready_path.exists():
                        content = ready_path.read_text(encoding="utf-8")
                        if "job_id=" in content:
                            break
                    time.sleep(0.02)
                self.assertTrue(ready_path.exists())
                self.assertIn("job_id=job-vis\n", content)
                self.assertIn("attempt=5\n", content)
                self.assertIn(f"pid={os.getpid()}\n", content)
                pause_path.unlink()
                thread.join(timeout=5.0)
                self.assertFalse(thread.is_alive())
                self.assertFalse(ready_path.exists())
            finally:
                pause_path.unlink(missing_ok=True)
                if thread.is_alive():
                    thread.join(timeout=1.0)

    def test_safe_private_custom_path_works(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as raw_dir:
            temp_dir = Path(raw_dir)
            temp_dir.chmod(0o700)
            pause_path = temp_dir / "custom_trigger"
            ready_path = temp_dir / "custom_trigger.ready"

            os.environ["_REPOMAP_SYSTEM_TEST_PAUSE_PATH"] = str(pause_path)
            cap = SimpleNamespace(job_id="job-custom", attempt=6)
            _run_system_test_pause(cap)
            self.assertFalse(ready_path.exists())


if __name__ == "__main__":
    unittest.main()
