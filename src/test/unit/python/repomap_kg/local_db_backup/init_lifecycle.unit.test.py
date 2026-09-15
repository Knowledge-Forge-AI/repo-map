import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from repomap_test_support.local_db_backup import LocalDbBackupUnitTestCase

from repomap_kg.runtime.backup import (
    LocalDbBackupError,
    format_init_result_table,
    init_database_from_dump,
    init_database_from_source,
)
from repomap_kg.runtime.local import LocalRuntimeIdentity, setup_local_runtime
from repomap_kg.storage import StorageSchemaError, discover_migrations


def _ready_ledger_output() -> bytes:
    rows = ("\t".join((str(m.ordinal), m.changeset_id, m.relative_path, m.checksum)) for m in discover_migrations())
    return ("\n".join(rows) + "\n").encode()


class LocalDbBackupInitLifecycleUnitTests(LocalDbBackupUnitTestCase):
    def test_init_from_source_dry_run_plans_new_database_without_direct_db(self):
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
                    return subprocess.CompletedProcess(command, 0, stdout=b"0\n", stderr=b"")
                raise AssertionError(command)

            result = init_database_from_source(
                home, database="repomap", dry_run=True, command_runner=fake_runner,
            )

            payload = result.to_jsonable()
            self.assertEqual(payload["command"], "init")
            self.assertEqual(payload["source_mode"], "source")
            self.assertEqual(payload["result"], "dry_run")
            self.assertFalse(payload["target_existed"])
            self.assertFalse(payload["database_created"])
            self.assertFalse(payload["schema_initialized"])
            self.assertFalse(payload["direct_db_required"])
            self.assertFalse(payload["destructive_db_actions"])
            self.assertIn("create-database", payload["planned_actions"])
            self.assertIn("apply-source-schema", payload["planned_actions"])
            self.assertTrue(any(call[:2] == ["docker", "inspect"] for call in calls))
            self.assertTrue(any(call[:2] == ["docker", "exec"] for call in calls))
            self.assertNotIn("POSTGRES_PASSWORD", json.dumps(payload))

    def test_init_from_source_refuses_existing_database_without_modification(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            identity = LocalRuntimeIdentity.from_home(home)

            def fake_runner(command, **kwargs):
                if command[:2] == ["docker", "inspect"]:
                    return self.owned_container_result(identity, command)
                if command[:2] == ["docker", "exec"]:
                    return subprocess.CompletedProcess(command, 0, stdout=b"1\n", stderr=b"")
                raise AssertionError(command)

            with self.assertRaises(LocalDbBackupError) as caught:
                init_database_from_source(home, database="repomap", command_runner=fake_runner)

            self.assertEqual(caught.exception.diagnostics[0].code, "database-already-exists")
            self.assertIn("replacement", caught.exception.diagnostics[0].message)

    def test_init_from_source_creates_database_and_applies_schema(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            identity = LocalRuntimeIdentity.from_home(home)
            calls: list[tuple[list[str], bytes | str | None]] = []

            def fake_runner(command, **kwargs):
                calls.append((list(command), kwargs.get("input")))
                if command[:2] == ["docker", "inspect"]:
                    return self.owned_container_result(identity, command)
                if "to_regclass('public.repomap_schema_migrations')" in " ".join(command):
                    return subprocess.CompletedProcess(command, 0, stdout=b"t\n", stderr=b"")
                if "FROM repomap_schema_migrations ORDER BY ordinal" in " ".join(command):
                    return subprocess.CompletedProcess(command, 0, stdout=_ready_ledger_output(), stderr=b"")
                if command[:2] == ["docker", "exec"] and "-tAc" in command:
                    return subprocess.CompletedProcess(command, 0, stdout=b"0\n", stderr=b"")
                if command[:2] == ["docker", "exec"]:
                    return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")
                raise AssertionError(command)

            result = init_database_from_source(home, database="repomap", command_runner=fake_runner)

            payload = result.to_jsonable()
            self.assertEqual(payload["result"], "success")
            self.assertTrue(payload["database_created"])
            self.assertTrue(payload["schema_initialized"])
            self.assertFalse(payload["dump_restored"])
            self.assertTrue(any("CREATE DATABASE" in " ".join(call) for call, _ in calls))
            schema_inputs = [input_value for call, input_value in calls if "-i" in call and isinstance(input_value, bytes)]
            self.assertTrue(schema_inputs)
            self.assertTrue(any(b"--liquibase formatted sql" in value for value in schema_inputs))
            self.assertIn(b"repomap_read_status", schema_inputs[-1])
            schema_payload = next(value for value in schema_inputs if b"--liquibase formatted sql" in value)
            self.assertTrue(schema_payload.startswith(b"BEGIN;\n"))
            self.assertIn(b"CREATE TABLE repomap_schema_migrations", schema_payload)
            self.assertTrue(schema_payload.rstrip().endswith(b"COMMIT;"))

    def test_init_from_dump_dry_run_validates_manifest_checksum_and_plans_restore(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            identity = LocalRuntimeIdentity.from_home(home)
            backup_dir = self.write_backup_fixture(home, identity.home_hash, "repomap")

            def fake_runner(command, **kwargs):
                if command[:2] == ["docker", "inspect"]:
                    return self.owned_container_result(identity, command)
                if command[:2] == ["docker", "exec"]:
                    return subprocess.CompletedProcess(command, 0, stdout=b"0\n", stderr=b"")
                raise AssertionError(command)

            result = init_database_from_dump(
                home, database="repomap", backup=backup_dir, dry_run=True, command_runner=fake_runner,
            )

            payload = result.to_jsonable()
            self.assertEqual(payload["source_mode"], "dump")
            self.assertEqual(payload["result"], "dry_run")
            self.assertEqual(payload["backup_id"], f"{identity.home_hash}--repomap--20260702T010203Z")
            self.assertEqual(payload["dump_file"], "dump.pgcustom")
            self.assertTrue(payload["checksum_verified"])
            self.assertFalse(payload["database_created"])
            self.assertFalse(payload["dump_restored"])
            self.assertIn("pg_restore", " ".join(result.planned_command))
            self.assertIn("source_mode=dump", format_init_result_table(result))

    def test_init_from_dump_creates_database_and_streams_pg_restore(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            identity = LocalRuntimeIdentity.from_home(home)
            backup_dir = self.write_backup_fixture(home, identity.home_hash, "repomap")
            calls: list[list[str]] = []
            restore_chunks: list[bytes] = []

            def fake_runner(command, **kwargs):
                calls.append(list(command))
                if command[:2] == ["docker", "inspect"]:
                    return self.owned_container_result(identity, command)
                if "to_regclass('public.repomap_schema_migrations')" in " ".join(command):
                    return subprocess.CompletedProcess(command, 0, stdout=b"t\n", stderr=b"")
                if "FROM repomap_schema_migrations ORDER BY ordinal" in " ".join(command):
                    return subprocess.CompletedProcess(
                        command, 0, stdout=_ready_ledger_output(), stderr=b""
                    )
                if command[:2] == ["docker", "exec"] and "-tAc" in command:
                    return subprocess.CompletedProcess(command, 0, stdout=b"0\n", stderr=b"")
                if command[:2] == ["docker", "exec"] and "/usr/bin/pg_restore" in command:
                    self.assertNotIn("input", kwargs)
                    stream = kwargs["stdin"]
                    while chunk := stream.read(4):
                        restore_chunks.append(chunk)
                    return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")
                if command[:2] == ["docker", "exec"]:
                    return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")
                raise AssertionError(command)

            result = init_database_from_dump(
                home, database="repomap", backup=backup_dir, command_runner=fake_runner,
            )

            payload = result.to_jsonable()
            self.assertEqual(payload["result"], "success")
            self.assertTrue(payload["database_created"])
            self.assertFalse(payload["schema_initialized"])
            self.assertTrue(payload["dump_restored"])
            restore_calls = [call for call in calls if "/usr/bin/pg_restore" in call]
            self.assertEqual(len(restore_calls), 1)
            self.assertEqual(b"".join(restore_chunks), b"repomap-dump")
            self.assertGreater(len(restore_chunks), 1)

    def test_init_from_dump_rejects_checksum_mismatch_and_paths_outside_backup_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            identity = LocalRuntimeIdentity.from_home(home)
            backup_dir = self.write_backup_fixture(home, identity.home_hash, "repomap")
            (backup_dir / "dump.pgcustom").write_bytes(b"tampered")

            with self.assertRaises(LocalDbBackupError) as checksum:
                init_database_from_dump(
                    home, database="repomap", backup=backup_dir, dry_run=True, command_runner=self.unexpected_runner,
                )
            self.assertEqual(checksum.exception.diagnostics[0].code, "backup-checksum-mismatch")

            outside = Path(tmpdir) / "outside" / "manifest.json"
            outside.parent.mkdir()
            outside.write_text("{}", encoding="utf-8")
            with self.assertRaises(LocalDbBackupError) as outside_error:
                init_database_from_dump(
                    home, database="repomap", backup=outside, dry_run=True, command_runner=self.unexpected_runner,
                )
            self.assertEqual(outside_error.exception.diagnostics[0].code, "backup-path-outside-root")

    def test_init_from_dump_rejects_malformed_unsupported_and_missing_dump_manifests(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            identity = LocalRuntimeIdentity.from_home(home)
            backup_dir = self.write_backup_fixture(home, identity.home_hash, "repomap")
            manifest_path = backup_dir / "manifest.json"

            def run_init():
                return init_database_from_dump(
                    home, database="repomap", backup=backup_dir, dry_run=True, command_runner=self.unexpected_runner,
                )

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["backup_format_version"] = 999
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(LocalDbBackupError) as format_error:
                run_init()
            self.assertEqual(format_error.exception.diagnostics[0].code, "backup-format-unsupported")

            manifest["backup_format_version"] = 1
            manifest["dump_format"] = "sql.gz"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(LocalDbBackupError) as dump_format:
                run_init()
            self.assertEqual(dump_format.exception.diagnostics[0].code, "backup-dump-format-unsupported")

            manifest["dump_format"] = "pgcustom"
            manifest["dump_files"] = "not-a-list"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(LocalDbBackupError) as malformed:
                run_init()
            self.assertEqual(malformed.exception.diagnostics[0].code, "backup-manifest-invalid")

            manifest["dump_files"] = [{"name": "dump.pgcustom", "size_bytes": 12, "sha256": "0" * 64}]
            (backup_dir / "dump.pgcustom").unlink()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(LocalDbBackupError) as missing:
                run_init()
            self.assertEqual(missing.exception.diagnostics[0].code, "backup-dump-missing")

    def test_init_from_dump_all_manifest_selects_named_database_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            identity = LocalRuntimeIdentity.from_home(home)
            backup_dir = self.write_backup_fixture(
                home,
                identity.home_hash,
                "repomap",
                all_databases=True,
            )

            def fake_runner(command, **kwargs):
                if command[:2] == ["docker", "inspect"]:
                    return self.owned_container_result(identity, command)
                if command[:2] == ["docker", "exec"]:
                    return subprocess.CompletedProcess(command, 0, stdout=b"0\n", stderr=b"")
                raise AssertionError(command)

            result = init_database_from_dump(
                home, database="repomap", backup=backup_dir, dry_run=True, command_runner=fake_runner,
            )
            self.assertEqual(result.to_jsonable()["dump_file"], "repomap.pgcustom")

            with self.assertRaises(LocalDbBackupError) as missing:
                init_database_from_dump(
                    home, database="missing_db", backup=backup_dir, dry_run=True, command_runner=fake_runner,
                )
            self.assertEqual(missing.exception.diagnostics[0].code, "database-not-owned")

    def test_init_redacts_source_schema_and_pg_restore_failures(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            identity = LocalRuntimeIdentity.from_home(home)

            def source_runner(command, **kwargs):
                if command[:2] == ["docker", "inspect"]:
                    return self.owned_container_result(identity, command)
                if command[:2] == ["docker", "exec"] and "-tAc" in command:
                    return subprocess.CompletedProcess(command, 0, stdout=b"0\n", stderr=b"")
                if command[:2] == ["docker", "exec"] and any(
                    text in " ".join(command)
                    for text in ("CREATE DATABASE", "DROP DATABASE")
                ):
                    return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")
                return subprocess.CompletedProcess(
                    command,
                    1,
                    stdout=b"",
                    stderr=b"POSTGRES_PASSWORD=fake-secret password=fake-secret",
                )

            with self.assertRaises(LocalDbBackupError) as schema_error:
                init_database_from_source(home, database="repomap", command_runner=source_runner)
            rendered_schema = json.dumps(
                [item.to_jsonable() for item in schema_error.exception.diagnostics],
                sort_keys=True,
            )
            self.assertIn("[REDACTED]", rendered_schema)
            self.assertNotIn("fake-secret", rendered_schema)

            backup_dir = self.write_backup_fixture(home, identity.home_hash, "repomap")

            def restore_runner(command, **kwargs):
                if command[:2] == ["docker", "inspect"]:
                    return self.owned_container_result(identity, command)
                if command[:2] == ["docker", "exec"] and "-tAc" in command:
                    return subprocess.CompletedProcess(command, 0, stdout=b"0\n", stderr=b"")
                if command[:2] == ["docker", "exec"] and any(
                    text in " ".join(command)
                    for text in ("CREATE DATABASE", "DROP DATABASE")
                ):
                    return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")
                return subprocess.CompletedProcess(
                    command,
                    1,
                    stdout=b"",
                    stderr=b"password=fake-secret",
                )

            with self.assertRaises(LocalDbBackupError) as restore_error:
                init_database_from_dump(
                    home, database="repomap", backup=backup_dir, command_runner=restore_runner,
                )
            rendered_restore = json.dumps(
                [item.to_jsonable() for item in restore_error.exception.diagnostics],
                sort_keys=True,
            )
            self.assertIn("[REDACTED]", rendered_restore)
            self.assertNotIn("fake-secret", rendered_restore)

    def test_init_reports_unavailable_source_migrations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            identity = LocalRuntimeIdentity.from_home(home)

            commands: list[list[str]] = []

            def fake_runner(command, **kwargs):
                commands.append(list(command))
                if command[:2] == ["docker", "inspect"]:
                    return self.owned_container_result(identity, command)
                if command[:2] == ["docker", "exec"] and "-tAc" in command:
                    return subprocess.CompletedProcess(command, 0, stdout=b"0\n", stderr=b"")
                if command[:2] == ["docker", "exec"]:
                    return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")
                raise AssertionError(command)

            with (
                patch(
                    "repomap_kg.runtime._backup_operations.graph_schema_initialization_sql",
                    side_effect=StorageSchemaError("missing migrations"),
                ) as resolver,
                patch(
                    "repomap_kg.runtime._backup_lifecycle.reconcile_graph_database_roles",
                    side_effect=AssertionError("roles must not run after schema resolution failure"),
                ) as roles,
            ):
                with self.assertRaises(LocalDbBackupError) as caught:
                    init_database_from_source(
                        home,
                        database="repomap",
                        command_runner=fake_runner,
                    )
            resolver.assert_called_once_with()
            roles.assert_not_called()
            self.assertTrue(any("DROP DATABASE" in " ".join(command) for command in commands))
            self.assertEqual(caught.exception.diagnostics[0].code, "source-schema-unavailable")

            with self.assertRaises(LocalDbBackupError) as caught_ready:
                init_database_from_source(
                    home,
                    database="repomap",
                    command_runner=fake_runner,
                )
            self.assertEqual(caught_ready.exception.diagnostics[0].code, "graph-schema-not-ready")
