from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from typing import Any
import unittest

from repomap_kg.runtime.backup_manifests import BACKUP_FORMAT_VERSION
from repomap_kg.runtime.backup_records import LocalDbBackupError
from repomap_kg.runtime.backup_restore_sets import (
    COORDINATED_SCOPE,
    STABLE_RECOVERY_POINT,
    format_coordinated_restore_table,
    restore_coordinated_backup,
)
from repomap_kg.runtime.local import build_local_runtime_plan, setup_local_runtime


class Slice9CoordinatedBackupRestoreIntegrationTests(unittest.TestCase):
    """Integration slice 9 tests covering complete coordinated backup and restore sets."""

    def _setup_backup_fixture(self, tmpdir: str) -> tuple[Path, Path, Any]:
        home = Path(tmpdir) / "home"
        setup_local_runtime(home)
        plan = build_local_runtime_plan(home)
        backup_dir = home / "backups" / "all-databases" / "20260921T120000Z"
        backup_dir.mkdir(parents=True)

        dump_files_list = []
        for db in plan.owned_databases:
            dump_path = backup_dir / f"{db}.pgcustom"
            content = f"content_for_{db}".encode("utf-8")
            dump_path.write_bytes(content)
            dump_files_list.append(
                {
                    "name": f"{db}.pgcustom",
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size_bytes": len(content),
                }
            )

        manifest = {
            "backup_format_version": BACKUP_FORMAT_VERSION,
            "backup_id": "test-backup-s9",
            "scope": COORDINATED_SCOPE,
            "databases": list(plan.owned_databases),
            "recovery_point": STABLE_RECOVERY_POINT,
            "dump_files": dump_files_list,
        }
        (backup_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return home, backup_dir, plan

    def _default_runner(self, plan: Any) -> Any:
        def runner(cmd: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            cmd_str = " ".join(str(c) for c in cmd)
            if "inspect" in cmd:
                return subprocess.CompletedProcess(
                    cmd,
                    0,
                    stdout=json.dumps(
                        [
                            {
                                "Id": "container-s9",
                                "Config": {
                                    "Image": "postgres:16-alpine",
                                    "Labels": plan.identity.labels("postgres"),
                                },
                            }
                        ]
                    ),
                    stderr="",
                )
            if "SELECT COUNT(*)" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, stdout="0\n", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        return runner

    def test_s9_c01_coordinated_backup_complete_set_manifest_validation(self) -> None:
        """Coordinated restore validates manifest format version, scope, stability, and databases."""
        with tempfile.TemporaryDirectory() as tmpdir:
            home, backup_dir, plan = self._setup_backup_fixture(tmpdir)
            manifest_file = backup_dir / "manifest.json"
            valid_manifest = json.loads(manifest_file.read_text(encoding="utf-8"))

            cases = (
                ({"backup_format_version": 999}, "coordinated-backup-scope-invalid"),
                ({"scope": "single-database"}, "coordinated-backup-scope-invalid"),
                ({"database": "repomap"}, "coordinated-backup-scope-invalid"),
                ({"recovery_point": {"status": "unstable"}}, "coordinated-backup-unstable"),
                ({"databases": ["only_one_db"]}, "coordinated-backup-topology-mismatch"),
            )
            for override, expected_code in cases:
                mutated = dict(valid_manifest)
                mutated.update(override)
                manifest_file.write_text(json.dumps(mutated), encoding="utf-8")
                with self.subTest(override=override):
                    with self.assertRaises(LocalDbBackupError) as ctx:
                        restore_coordinated_backup(
                            home,
                            backup=backup_dir,
                            dry_run=True,
                            command_runner=self._default_runner(plan),
                        )
                    codes = [d.code for d in ctx.exception.diagnostics]
                    self.assertIn(expected_code, codes)

    def test_s9_c02_coordinated_backup_dump_set_and_checksum_verification(self) -> None:
        """Dump file presence, checksum matching, and missing dump files are strictly verified."""
        with tempfile.TemporaryDirectory() as tmpdir:
            home, backup_dir, plan = self._setup_backup_fixture(tmpdir)
            manifest_file = backup_dir / "manifest.json"
            valid_manifest = json.loads(manifest_file.read_text(encoding="utf-8"))

            mutated = dict(valid_manifest)
            mutated["dump_files"] = valid_manifest["dump_files"][:1]
            manifest_file.write_text(json.dumps(mutated), encoding="utf-8")
            with self.assertRaises(LocalDbBackupError) as ctx:
                restore_coordinated_backup(
                    home,
                    backup=backup_dir,
                    dry_run=True,
                    command_runner=self._default_runner(plan),
                )
            self.assertIn("coordinated-backup-dump-set-invalid", [d.code for d in ctx.exception.diagnostics])

            manifest_file.write_text(json.dumps(valid_manifest), encoding="utf-8")
            missing_dump = backup_dir / f"{plan.owned_databases[0]}.pgcustom"
            missing_dump.unlink()
            with self.assertRaises(LocalDbBackupError) as ctx:
                restore_coordinated_backup(
                    home,
                    backup=backup_dir,
                    dry_run=True,
                    command_runner=self._default_runner(plan),
                )
            self.assertIn("backup-dump-missing", [d.code for d in ctx.exception.diagnostics])

            missing_dump.write_bytes(b"tampered_corrupt_content")
            with self.assertRaises(LocalDbBackupError) as ctx:
                restore_coordinated_backup(
                    home,
                    backup=backup_dir,
                    dry_run=True,
                    command_runner=self._default_runner(plan),
                )
            self.assertIn("backup-checksum-mismatch", [d.code for d in ctx.exception.diagnostics])

    def test_s9_c03_coordinated_restore_target_exists_refusal(self) -> None:
        """Restore refuses execution when any configured target database already exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            home, backup_dir, plan = self._setup_backup_fixture(tmpdir)

            def runner_with_existing(cmd, **kwargs):
                cmd_str = " ".join(str(c) for c in cmd)
                if "inspect" in cmd:
                    return subprocess.CompletedProcess(
                        cmd,
                        0,
                        stdout=json.dumps([{"Id": "c", "Config": {"Image": "i", "Labels": plan.identity.labels("postgres")}}]),
                        stderr="",
                    )
                if "SELECT COUNT(*)" in cmd_str:
                    return subprocess.CompletedProcess(cmd, 0, stdout="1\n", stderr="")
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

            with self.assertRaises(LocalDbBackupError) as ctx:
                restore_coordinated_backup(
                    home,
                    backup=backup_dir,
                    dry_run=False,
                    command_runner=runner_with_existing,
                )
            codes = [d.code for d in ctx.exception.diagnostics]
            self.assertIn("coordinated-restore-target-exists", codes)

    def test_s9_c04_coordinated_restore_dry_run_and_table_formatting(self) -> None:
        """Dry run verifies integrity without mutating databases and renders informative table."""
        with tempfile.TemporaryDirectory() as tmpdir:
            home, backup_dir, plan = self._setup_backup_fixture(tmpdir)
            result = restore_coordinated_backup(
                home,
                backup=backup_dir,
                dry_run=True,
                command_runner=self._default_runner(plan),
            )
            self.assertEqual(result.result, "dry_run")
            self.assertEqual(result.databases_created, ())
            self.assertEqual(result.dumps_restored, ())
            self.assertTrue(result.checksum_verified)
            self.assertTrue(result.target_preflight_complete)

            table = format_coordinated_restore_table(result)
            self.assertIn("result=dry_run", table)
            self.assertIn("backup_id=test-backup-s9", table)
            self.assertIn("checksum_verified=true", table)
            self.assertIn("all_targets_absent=true", table)

    def test_s9_c05_coordinated_restore_full_execution_order_and_roles(self) -> None:
        """Full restore creates and restores graphs first, control last, then reconciles roles."""
        with tempfile.TemporaryDirectory() as tmpdir:
            home, backup_dir, plan = self._setup_backup_fixture(tmpdir)
            recorded_actions = []

            def tracking_runner(cmd, **kwargs):
                cmd_str = " ".join(str(c) for c in cmd)
                if "inspect" in cmd:
                    return subprocess.CompletedProcess(
                        cmd,
                        0,
                        stdout=json.dumps([{"Id": "c", "Config": {"Image": "i", "Labels": plan.identity.labels("postgres")}}]),
                        stderr="",
                    )
                if "SELECT COUNT(*)" in cmd_str:
                    return subprocess.CompletedProcess(cmd, 0, stdout="0\n", stderr="")
                if "CREATE DATABASE" in cmd_str:
                    db = cmd[-1].replace('CREATE DATABASE "', "").replace('";', "")
                    recorded_actions.append(f"create:{db}")
                    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
                if "pg_restore" in cmd_str and "-d" in cmd:
                    db = cmd[cmd.index("-d") + 1]
                    recorded_actions.append(f"restore:{db}")
                    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
                if "psql" in cmd_str and kwargs.get("input"):
                    input_text = kwargs["input"].decode("utf-8", errors="replace")
                    if "COORDINATOR_CONTROL_ROLE" in input_text or "REFRESH_PUBLICATION_ROLE" in input_text:
                        recorded_actions.append("roles_reconciled")
                    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

            result = restore_coordinated_backup(
                home,
                backup=backup_dir,
                dry_run=False,
                command_runner=tracking_runner,
            )
            self.assertEqual(result.result, "success")
            self.assertEqual(result.dumps_restored, ("repomap", "repomap_control"))
            payload = result.to_jsonable()
            self.assertTrue(payload["control_restored_last"])

            self.assertIn("create:repomap", recorded_actions)
            self.assertIn("restore:repomap", recorded_actions)
            self.assertIn("create:repomap_control", recorded_actions)
            self.assertIn("restore:repomap_control", recorded_actions)
            idx_graph_restore = recorded_actions.index("restore:repomap")
            idx_ctrl_restore = recorded_actions.index("restore:repomap_control")
            self.assertLess(idx_graph_restore, idx_ctrl_restore)

    def test_s9_c06_coordinated_restore_failure_clean_reverse_rollback(self) -> None:
        """Partial restore failure rolls back created target databases in reverse order."""
        with tempfile.TemporaryDirectory() as tmpdir:
            home, backup_dir, plan = self._setup_backup_fixture(tmpdir)
            cleaned_up = []

            def failing_runner(cmd, **kwargs):
                cmd_str = " ".join(str(c) for c in cmd)
                if "inspect" in cmd:
                    return subprocess.CompletedProcess(
                        cmd,
                        0,
                        stdout=json.dumps([{"Id": "c", "Config": {"Image": "i", "Labels": plan.identity.labels("postgres")}}]),
                        stderr="",
                    )
                if "SELECT COUNT(*)" in cmd_str:
                    return subprocess.CompletedProcess(cmd, 0, stdout="0\n", stderr="")
                if "CREATE DATABASE" in cmd_str:
                    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
                if "pg_restore" in cmd_str and "-d" in cmd and cmd[cmd.index("-d") + 1] == "repomap_control":
                    raise RuntimeError("synthetic restore failure on control db")
                if "DROP DATABASE" in cmd_str:
                    cleaned_up.append(cmd_str)
                    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

            with self.assertRaises(RuntimeError) as ctx:
                restore_coordinated_backup(
                    home,
                    backup=backup_dir,
                    dry_run=False,
                    command_runner=failing_runner,
                )
            self.assertIn("synthetic restore failure", str(ctx.exception))
            self.assertEqual(len(cleaned_up), 2)
            self.assertIn('"repomap_control"', cleaned_up[0])
            self.assertIn('"repomap"', cleaned_up[1])

    def test_s9_c07_coordinated_restore_cleanup_failure_compounding(self) -> None:
        """Compounded failure during cleanup raises coordinated-restore-cleanup-failed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            home, backup_dir, plan = self._setup_backup_fixture(tmpdir)

            def catastrophic_runner(cmd, **kwargs):
                cmd_str = " ".join(str(c) for c in cmd)
                if "inspect" in cmd:
                    return subprocess.CompletedProcess(
                        cmd,
                        0,
                        stdout=json.dumps([{"Id": "c", "Config": {"Image": "i", "Labels": plan.identity.labels("postgres")}}]),
                        stderr="",
                    )
                if "SELECT COUNT(*)" in cmd_str:
                    return subprocess.CompletedProcess(cmd, 0, stdout="0\n", stderr="")
                if "CREATE DATABASE" in cmd_str:
                    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
                if "pg_restore" in cmd_str and "-d" in cmd and cmd[cmd.index("-d") + 1] == "repomap_control":
                    raise RuntimeError("initial restore failure")
                if "DROP DATABASE" in cmd_str:
                    raise RuntimeError("cleanup drop failure")
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

            with self.assertRaises(LocalDbBackupError) as ctx:
                restore_coordinated_backup(
                    home,
                    backup=backup_dir,
                    dry_run=False,
                    command_runner=catastrophic_runner,
                )
            codes = [d.code for d in ctx.exception.diagnostics]
            self.assertIn("coordinated-restore-cleanup-failed", codes)


if __name__ == "__main__":
    import sys
    sys.exit('Direct execution unsupported; use tools/run_tests.py for container sandbox admission.')
