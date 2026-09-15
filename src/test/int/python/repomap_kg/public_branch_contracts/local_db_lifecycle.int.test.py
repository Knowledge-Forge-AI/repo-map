import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from repomap_test_support.public_branch_contracts import (
    owned_container_result,
    unexpected_runner,
    write_backup_fixture,
)
from repomap_kg.runtime.backup import (
    LocalDbBackupError,
    drop_database,
    format_drop_result_table,
    init_database_from_dump,
    init_database_from_source,
)
from repomap_kg.runtime.local import LocalRuntimeIdentity, setup_local_runtime
from repomap_kg.storage import StorageSchemaError


class PublicBranchLocalDbLifecycleIntegrationTests(unittest.TestCase):
    def test_local_db_init_error_contracts_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            identity = LocalRuntimeIdentity.from_home(home)

            def existing_database_runner(command, **kwargs):
                if command[:2] == ["docker", "inspect"]:
                    return owned_container_result(identity, command)
                if command[:2] == ["docker", "exec"]:
                    return subprocess.CompletedProcess(command, 0, stdout=b"1\n", stderr=b"")
                raise AssertionError(command)

            with self.assertRaises(LocalDbBackupError) as existing:
                init_database_from_source(
                    home,
                    database="repomap",
                    command_runner=existing_database_runner,
                )
            self.assertEqual(existing.exception.diagnostics[0].code, "database-already-exists")

            def new_database_runner(command, **kwargs):
                if command[:2] == ["docker", "inspect"]:
                    return owned_container_result(identity, command)
                if command[:2] == ["docker", "exec"] and "-tAc" in command:
                    return subprocess.CompletedProcess(command, 0, stdout=b"0\n", stderr=b"")
                if command[:2] == ["docker", "exec"]:
                    return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")
                raise AssertionError(command)

            with patch(
                "repomap_kg.runtime._backup_operations.graph_schema_initialization_sql",
                side_effect=StorageSchemaError("missing migrations"),
            ):
                with self.assertRaises(LocalDbBackupError) as schema:
                    init_database_from_source(
                        home,
                        database="repomap",
                        command_runner=new_database_runner,
                    )
            self.assertEqual(schema.exception.diagnostics[0].code, "source-schema-unavailable")

            backup_dir = write_backup_fixture(home, identity.home_hash, "repomap")
            manifest_path = backup_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["backup_format_version"] = 999
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(LocalDbBackupError) as format_error:
                init_database_from_dump(
                    home,
                    database="repomap",
                    backup=backup_dir,
                    dry_run=True,
                    command_runner=unexpected_runner,
                )
            self.assertEqual(format_error.exception.diagnostics[0].code, "backup-format-unsupported")

            manifest["backup_format_version"] = 1
            manifest["dump_format"] = "sql.gz"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(LocalDbBackupError) as dump_format:
                init_database_from_dump(
                    home,
                    database="repomap",
                    backup=backup_dir,
                    dry_run=True,
                    command_runner=unexpected_runner,
                )
            self.assertEqual(
                dump_format.exception.diagnostics[0].code,
                "backup-dump-format-unsupported",
            )

            manifest["dump_format"] = "pgcustom"
            manifest["dump_files"] = "not-a-list"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(LocalDbBackupError) as malformed:
                init_database_from_dump(
                    home,
                    database="repomap",
                    backup=backup_dir,
                    dry_run=True,
                    command_runner=unexpected_runner,
                )
            self.assertEqual(malformed.exception.diagnostics[0].code, "backup-manifest-invalid")

            manifest["dump_files"] = [
                {"name": "dump.pgcustom", "size_bytes": 12, "sha256": "0" * 64}
            ]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            (backup_dir / "dump.pgcustom").write_bytes(b"tampered")
            with self.assertRaises(LocalDbBackupError) as checksum:
                init_database_from_dump(
                    home,
                    database="repomap",
                    backup=backup_dir,
                    dry_run=True,
                    command_runner=unexpected_runner,
                )
            self.assertEqual(checksum.exception.diagnostics[0].code, "backup-checksum-mismatch")

            outside = Path(tmpdir) / "outside" / "manifest.json"
            outside.parent.mkdir()
            outside.write_text("{}", encoding="utf-8")
            with self.assertRaises(LocalDbBackupError) as outside_error:
                init_database_from_dump(
                    home,
                    database="repomap",
                    backup=outside,
                    dry_run=True,
                    command_runner=unexpected_runner,
                )
            self.assertEqual(outside_error.exception.diagnostics[0].code, "backup-path-outside-root")

    def test_local_db_drop_backup_first_contracts_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            identity = LocalRuntimeIdentity.from_home(home)

            with self.assertRaises(LocalDbBackupError) as missing_backup:
                drop_database(
                    home,
                    database="repomap",
                    backup_first=False,
                    dry_run=True,
                    command_runner=unexpected_runner,
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
                    command_runner=unexpected_runner,
                )
            self.assertEqual(
                missing_confirmation.exception.diagnostics[0].code,
                "drop-confirmation-required",
            )

            calls: list[list[str]] = []

            def dry_run_runner(command, **kwargs):
                calls.append(list(command))
                if command[:2] == ["docker", "inspect"]:
                    return owned_container_result(identity, command)
                if command[:2] == ["docker", "exec"]:
                    return subprocess.CompletedProcess(command, 0, stdout=b"1\n", stderr=b"")
                raise AssertionError(command)

            dry_run = drop_database(
                home,
                database="repomap",
                backup_first=True,
                dry_run=True,
                timestamp="20260702T010203Z",
                reason="test drop",
                command_runner=dry_run_runner,
            )
            dry_payload = dry_run.to_jsonable()
            self.assertEqual(dry_payload["result"], "dry_run")
            self.assertFalse(dry_payload["backup_path_created"])
            self.assertFalse(dry_payload["database_dropped"])
            self.assertFalse(dry_payload["destructive_db_actions"])
            self.assertIn("create-backup", dry_payload["planned_actions"])
            self.assertIn("drop-database", dry_payload["planned_actions"])
            self.assertFalse(dry_run.backup_plan.backup_path.exists())
            self.assertTrue(any(call[:2] == ["docker", "inspect"] for call in calls))
            self.assertIn("backup_first=true", format_drop_result_table(dry_run))

            events: list[str] = []

            def success_runner(command, **kwargs):
                if command[:2] == ["docker", "inspect"]:
                    events.append("inspect")
                    return owned_container_result(identity, command)
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

            success = drop_database(
                home,
                database="repomap",
                backup_first=True,
                confirmed=True,
                timestamp="20260702T010204Z",
                reason="test drop",
                command_runner=success_runner,
            )
            success_payload = success.to_jsonable()
            manifest = json.loads(
                (success.backup_plan.backup_path / "manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(success_payload["result"], "success")
            self.assertTrue(success_payload["backup_path_created"])
            self.assertTrue(success_payload["checksum_verified"])
            self.assertTrue(success_payload["database_dropped"])
            self.assertTrue(success_payload["destructive_db_actions"])
            self.assertEqual(manifest["backup_kind"], "pre-drop")
            self.assertEqual(
                manifest["dump_files"][0]["sha256"],
                hashlib.sha256(b"pre-drop-dump").hexdigest(),
            )
            self.assertLess(events.index("backup"), events.index("drop"))

            def missing_runner(command, **kwargs):
                if command[:2] == ["docker", "inspect"]:
                    return owned_container_result(identity, command)
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

            for database in ("template0", "template1", "postgres"):
                with self.subTest(database=database):
                    with self.assertRaises(LocalDbBackupError) as forbidden:
                        drop_database(
                            home,
                            database=database,
                            backup_first=True,
                            dry_run=True,
                            command_runner=unexpected_runner,
                        )
                    self.assertEqual(
                        forbidden.exception.diagnostics[0].code,
                        "database-not-owned",
                    )

            def failing_drop_runner(command, **kwargs):
                if command[:2] == ["docker", "inspect"]:
                    return owned_container_result(identity, command)
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
