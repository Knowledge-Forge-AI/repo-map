import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from repomap_test_support.local_db_backup import LocalDbBackupUnitTestCase

from repomap_kg.runtime.backup import (
    LocalDbBackupError,
    format_drop_result_table,
    drop_database,
)
from repomap_kg.runtime.local import LocalRuntimeIdentity, setup_local_runtime


class LocalDbBackupDropLifecycleUnitTests(LocalDbBackupUnitTestCase):
    def test_drop_requires_backup_first_and_confirmation_for_non_dry_run(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)

            with self.assertRaises(LocalDbBackupError) as missing_backup:
                drop_database(
                    home,
                    database="repomap",
                    backup_first=False,
                    dry_run=True,
                    command_runner=self.unexpected_runner,
                )
            self.assertEqual(
                missing_backup.exception.diagnostics[0].code,
                "backup-first-required",
            )

            with self.assertRaises(LocalDbBackupError) as missing_confirmation:
                drop_database(
                    home,
                    database="repomap",
                    backup_first=True,
                    confirmed=False,
                    command_runner=self.unexpected_runner,
                )
            self.assertEqual(
                missing_confirmation.exception.diagnostics[0].code,
                "drop-confirmation-required",
            )

    def test_drop_dry_run_plans_backup_and_drop_without_creating_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            identity = LocalRuntimeIdentity.from_home(home)
            calls: list[list[str]] = []

            def fake_runner(command, **kwargs):
                calls.append(list(command))
                if command[:2] == ["docker", "inspect"]:
                    return self.owned_container_result(identity, command)
                if command[:2] == ["docker", "exec"]:
                    self.assertIn("-tAc", command)
                    return subprocess.CompletedProcess(command, 0, stdout=b"1\n", stderr=b"")
                raise AssertionError(command)

            result = drop_database(
                home,
                database="repomap",
                backup_first=True,
                dry_run=True,
                timestamp="20260702T010203Z",
                reason="test drop",
                command_runner=fake_runner,
            )

            payload = result.to_jsonable()
            self.assertEqual(payload["command"], "drop")
            self.assertEqual(payload["result"], "dry_run")
            self.assertTrue(payload["backup_first"])
            self.assertFalse(payload["confirmation_received"])
            self.assertTrue(payload["target_existed"])
            self.assertFalse(payload["backup_path_created"])
            self.assertFalse(payload["database_dropped"])
            self.assertFalse(payload["destructive_db_actions"])
            self.assertFalse(payload["direct_db_required"])
            self.assertIn("create-backup", payload["planned_actions"])
            self.assertIn("drop-database", payload["planned_actions"])
            self.assertIn("local db init --database repomap --from-dump", payload["restore_command_hint"])
            self.assertFalse(result.backup_plan.backup_path.exists())
            self.assertTrue(any(call[:2] == ["docker", "inspect"] for call in calls))
            self.assertTrue(any(call[:2] == ["docker", "exec"] for call in calls))
            self.assertIn("backup_first=true", format_drop_result_table(result))

    def test_drop_creates_and_verifies_backup_before_drop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            identity = LocalRuntimeIdentity.from_home(home)
            events: list[str] = []

            def fake_runner(command, **kwargs):
                if command[:2] == ["docker", "inspect"]:
                    events.append("inspect")
                    return self.owned_container_result(identity, command)
                if command[:2] == ["docker", "exec"] and "-tAc" in command:
                    events.append("exists")
                    return subprocess.CompletedProcess(command, 0, stdout=b"1\n", stderr=b"")
                if command[:2] == ["docker", "exec"] and "/usr/bin/pg_dump" in command:
                    events.append("backup")
                    return subprocess.CompletedProcess(command, 0, stdout=b"pre-drop-dump", stderr=b"")
                if command[:2] == ["docker", "exec"] and "DROP DATABASE" in " ".join(command):
                    events.append("drop")
                    return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")
                raise AssertionError(command)

            result = drop_database(
                home,
                database="repomap",
                backup_first=True,
                confirmed=True,
                timestamp="20260702T010203Z",
                reason="test drop",
                command_runner=fake_runner,
            )

            payload = result.to_jsonable()
            backup_path = result.backup_plan.backup_path
            manifest = json.loads((backup_path / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["result"], "success")
            self.assertTrue(payload["backup_path_created"])
            self.assertTrue(payload["checksum_verified"])
            self.assertTrue(payload["database_dropped"])
            self.assertTrue(payload["destructive_db_actions"])
            self.assertEqual(manifest["backup_kind"], "pre-drop")
            self.assertEqual(manifest["dump_files"][0]["sha256"], hashlib.sha256(b"pre-drop-dump").hexdigest())
            self.assertTrue((backup_path / "restore.md").is_file())
            self.assertLess(events.index("backup"), events.index("drop"))
            self.assertIn("init --database repomap --from-dump", payload["restore_command_hint"])
            self.assertNotIn("POSTGRES_PASSWORD", json.dumps(payload))

    def test_drop_refuses_missing_database_and_verification_failure_without_drop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            identity = LocalRuntimeIdentity.from_home(home)

            def missing_runner(command, **kwargs):
                if command[:2] == ["docker", "inspect"]:
                    return self.owned_container_result(identity, command)
                if command[:2] == ["docker", "exec"]:
                    return subprocess.CompletedProcess(command, 0, stdout=b"0\n", stderr=b"")
                raise AssertionError(command)

            with self.assertRaises(LocalDbBackupError) as missing:
                drop_database(
                    home,
                    database="repomap",
                    backup_first=True,
                    confirmed=True,
                    command_runner=missing_runner,
                )
            self.assertEqual(missing.exception.diagnostics[0].code, "database-not-found")

            events: list[str] = []

            def corrupting_runner(command, **kwargs):
                if command[:2] == ["docker", "inspect"]:
                    return self.owned_container_result(identity, command)
                if command[:2] == ["docker", "exec"] and "-tAc" in command:
                    return subprocess.CompletedProcess(command, 0, stdout=b"1\n", stderr=b"")
                if command[:2] == ["docker", "exec"] and "/usr/bin/pg_dump" in command:
                    events.append("backup")
                    return subprocess.CompletedProcess(command, 0, stdout=b"pre-drop-dump", stderr=b"")
                if command[:2] == ["docker", "exec"] and "DROP DATABASE" in " ".join(command):
                    events.append("drop")
                    return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")
                raise AssertionError(command)

            from repomap_kg.runtime.backup_manifests import (
                write_manifest_and_restore_docs as original_manifest_writer,
            )

            def corrupt_manifest(plan, **kwargs):
                original_manifest_writer(plan, **kwargs)
                manifest_path = plan.manifest_path
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["dump_files"][0]["sha256"] = "0" * 64
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with patch(
                "repomap_kg.runtime._backup_lifecycle.write_manifest_and_restore_docs",
                side_effect=corrupt_manifest,
            ):
                with self.assertRaises(LocalDbBackupError) as corrupt:
                    drop_database(
                        home,
                        database="repomap",
                        backup_first=True,
                        confirmed=True,
                        timestamp="20260702T010204Z",
                        command_runner=corrupting_runner,
                    )

            self.assertEqual(corrupt.exception.diagnostics[0].code, "backup-checksum-mismatch")
            self.assertEqual(events, ["backup"])

    def test_drop_rejects_system_databases_and_redacts_failures(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            identity = LocalRuntimeIdentity.from_home(home)

            for database in ("template0", "template1", "postgres"):
                with self.assertRaises(LocalDbBackupError) as caught:
                    drop_database(
                        home,
                        database=database,
                        backup_first=True,
                        dry_run=True,
                        command_runner=self.unexpected_runner,
                    )
                self.assertEqual(caught.exception.diagnostics[0].code, "database-not-owned")

            def failing_drop_runner(command, **kwargs):
                if command[:2] == ["docker", "inspect"]:
                    return self.owned_container_result(identity, command)
                if command[:2] == ["docker", "exec"] and "-tAc" in command:
                    return subprocess.CompletedProcess(command, 0, stdout=b"1\n", stderr=b"")
                if command[:2] == ["docker", "exec"] and "/usr/bin/pg_dump" in command:
                    return subprocess.CompletedProcess(command, 0, stdout=b"pre-drop-dump", stderr=b"")
                return subprocess.CompletedProcess(
                    command,
                    1,
                    stdout=b"",
                    stderr=b"POSTGRES_PASSWORD=fake-secret password=fake-secret",
                )

            with self.assertRaises(LocalDbBackupError) as drop_error:
                drop_database(
                    home,
                    database="repomap",
                    backup_first=True,
                    confirmed=True,
                    timestamp="20260702T010205Z",
                    command_runner=failing_drop_runner,
                )
            rendered = json.dumps(
                [item.to_jsonable() for item in drop_error.exception.diagnostics],
                sort_keys=True,
            )
            self.assertIn("[REDACTED]", rendered)
            self.assertNotIn("fake-secret", rendered)
