from collections import defaultdict, deque
import os
from pathlib import Path
import tempfile
from typing import Any
import unittest

from repomap_kg.service_package.contract import build_service_package_spec
from repomap_kg.service_package.operations import (
    CoordinatorServiceOperations,
    ServiceActionResult,
    ServicePackageError,
)
from repomap_kg.service_package.systemd import SystemdUserAdapter
from repomap_test_support.executable_authority import controlled_service_authority


class RecordingRunner:
    def __init__(self, responses: dict[tuple[str, ...], list[int]] | None = None) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.responses: dict[tuple[str, ...], deque[int]] = defaultdict(deque)
        for argv, values in (responses or {}).items():
            self.responses[argv].extend(values)

    def __call__(self, argv: tuple[str, ...]) -> int:
        self.calls.append(argv)
        outcomes = self.responses[argv]
        return outcomes.popleft() if outcomes else 0


class Slice9ServiceOperationsIntegrationTests(unittest.TestCase):
    """Integration slice 9 tests covering native service lifecycle mutations and safety boundaries."""

    @staticmethod
    def _run_action(ops: CoordinatorServiceOperations, action: str) -> ServiceActionResult:
        res = ops.run(action)
        assert isinstance(res, ServiceActionResult)
        return res

    def _build_ops(
        self,
        root: Path,
        *,
        runner: RecordingRunner | None = None,
        health_probe: Any = None,
    ) -> tuple[CoordinatorServiceOperations, SystemdUserAdapter, RecordingRunner]:
        home = root / "home"
        home.mkdir(mode=0o700, exist_ok=True)
        spec = build_service_package_spec(home)
        adapter = SystemdUserAdapter(user_home=root / "user", uid=os.getuid())
        rec_runner = runner or RecordingRunner()
        probe = health_probe or (lambda _spec: True)
        ops = CoordinatorServiceOperations(
            spec,
            adapter,
            runner=rec_runner,
            health_probe=probe,
        )
        return ops, adapter, rec_runner

    def test_s9_c08_service_action_validation_and_render(self) -> None:
        """Service operations reject unsupported actions, render valid unit syntax, and validate absence."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with controlled_service_authority(root / "exec-auth"):
                ops, adapter, _ = self._build_ops(root)

                with self.assertRaises(ServicePackageError) as ctx:
                    ops.run("not_an_action")
                self.assertIn("service_action_unsupported", str(ctx.exception))

                rendered = ops.run("render")
                assert isinstance(rendered, str)
                self.assertIn("[Unit]", rendered)
                self.assertIn("[Service]", rendered)
                self.assertIn("ExecStart=", rendered)

                result = self._run_action(ops, "validate")
                self.assertEqual(result.action, "validate")
                self.assertFalse(result.installed)

    def test_s9_c09_service_install_directory_preparation_and_permissions(self) -> None:
        """Service install creates private parent directory and writes unit with 0o600 mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with controlled_service_authority(root / "exec-auth"):
                ops, adapter, runner = self._build_ops(root)

                result = self._run_action(ops, "install")
                self.assertEqual(result.action, "install")
                self.assertTrue(result.installed)
                self.assertFalse(result.active)
                self.assertTrue(result.changed)

                self.assertTrue(adapter.target_path.is_file())
                parent_mode = adapter.target_path.parent.stat().st_mode & 0o777
                self.assertEqual(parent_mode, 0o700)
                file_mode = adapter.target_path.stat().st_mode & 0o777
                self.assertEqual(file_mode, 0o600)
                self.assertEqual(runner.calls, list(adapter.reload_commands()))

    def test_s9_c10_service_install_failure_reload_rollback(self) -> None:
        """Failure during daemon-reload after file installation removes the unit and rolls back."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with controlled_service_authority(root / "exec-auth"):
                ops, adapter, _ = self._build_ops(root)
                reload_cmd = adapter.reload_commands()[0]
                runner = RecordingRunner({reload_cmd: [1, 0]})
                ops.runner = runner

                with self.assertRaises(ServicePackageError) as ctx:
                    ops.run("install")
                self.assertIn("service_install_rolled_back", str(ctx.exception))
                self.assertFalse(adapter.target_path.exists())
                self.assertEqual(runner.calls, [reload_cmd, reload_cmd])

    def test_s9_c11_service_start_and_stop_lifecycle_with_enable_disable(self) -> None:
        """Start activates and enables the unit; stop deactivates and disables."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with controlled_service_authority(root / "exec-auth"):
                ops, adapter, runner = self._build_ops(root)
                ops.run("install")
                runner.calls.clear()

                runner.responses[adapter.active_probe_argv()].extend([3, 0])
                runner.responses[adapter.enabled_probe_argv()].extend([1, 0])

                res_start = self._run_action(ops, "start")
                self.assertEqual(res_start.action, "start")
                self.assertTrue(res_start.active)
                self.assertTrue(res_start.enabled)
                self.assertTrue(res_start.changed)
                self.assertIn(adapter.enable_commands()[0], runner.calls)
                self.assertIn(adapter.start_commands()[0], runner.calls)

                runner.calls.clear()
                res_stop = self._run_action(ops, "stop")
                self.assertEqual(res_stop.action, "stop")
                self.assertFalse(res_stop.active)
                self.assertFalse(res_stop.enabled)
                self.assertTrue(res_stop.changed)
                self.assertIn(adapter.stop_commands()[0], runner.calls)
                self.assertIn(adapter.disable_commands()[0], runner.calls)

    def test_s9_c12_service_start_failure_disable_rollback(self) -> None:
        """Failure when starting a service after enable rolls back the enabled state."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with controlled_service_authority(root / "exec-auth"):
                ops, adapter, runner = self._build_ops(root)
                ops.run("install")
                runner.calls.clear()

                runner.responses[adapter.active_probe_argv()].append(3)
                runner.responses[adapter.enabled_probe_argv()].append(1)
                runner.responses[adapter.start_commands()[0]].append(1)

                with self.assertRaises(ServicePackageError) as ctx:
                    ops.run("start")
                self.assertIn("service_start_failed", str(ctx.exception))
                self.assertIn(adapter.enable_commands()[0], runner.calls)
                self.assertIn(adapter.start_commands()[0], runner.calls)
                self.assertIn(adapter.disable_commands()[0], runner.calls)

    def test_s9_c13_service_upgrade_atomic_replacement_and_rollback(self) -> None:
        """Upgrade failure during reload restores prior definition and native state."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with controlled_service_authority(root / "exec-auth"):
                ops, adapter, runner = self._build_ops(root)
                ops.run("install")
                prior_bytes = adapter.target_path.read_bytes()
                runner.calls.clear()

                runner.responses[adapter.active_probe_argv()].extend([0])
                runner.responses[adapter.enabled_probe_argv()].extend([0])
                runner.responses[adapter.start_commands()[0]].extend([1, 0])

                with self.assertRaises(ServicePackageError) as ctx:
                    ops.run("upgrade")
                self.assertIn("service_upgrade_rolled_back", str(ctx.exception))
                self.assertEqual(adapter.target_path.read_bytes(), prior_bytes)

    def test_s9_c14_service_status_probe_and_foreign_definition_detection(self) -> None:
        """Status correctly queries health probe and validate refuses foreign definitions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with controlled_service_authority(root / "exec-auth"):
                ops, adapter, runner = self._build_ops(root, health_probe=lambda _s: True)

                res_uninstalled = self._run_action(ops, "status")
                self.assertFalse(res_uninstalled.installed)
                self.assertFalse(res_uninstalled.active)
                self.assertFalse(res_uninstalled.ready)

                ops.run("install")
                runner.responses[adapter.active_probe_argv()].append(0)
                runner.responses[adapter.enabled_probe_argv()].append(0)
                res_ready = self._run_action(ops, "status")
                self.assertTrue(res_ready.installed)
                self.assertTrue(res_ready.active)
                self.assertTrue(res_ready.ready)

                ops.health_probe = lambda _s: False
                runner.responses[adapter.active_probe_argv()].append(0)
                runner.responses[adapter.enabled_probe_argv()].append(0)
                res_not_ready = self._run_action(ops, "status")
                self.assertFalse(res_not_ready.ready)

                adapter.target_path.write_bytes(b"[Unit]\nDescription=Foreign Unit\n")
                adapter.target_path.chmod(0o600)
                with self.assertRaises(ServicePackageError) as ctx:
                    ops.run("validate")
                self.assertIn("service_definition_unsafe", str(ctx.exception))


if __name__ == "__main__":
    import sys
    sys.exit('Direct execution unsupported; use tools/run_tests.py for container sandbox admission.')
