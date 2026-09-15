import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from repomap_test_support.cli_integration import (
    CliIntegrationTestCase,
)

from repomap_kg.runtime.local import LocalRuntimeIdentity
from repomap_kg.storage import discover_migrations


def _ready_ledger_output() -> bytes:
    rows = ("\t".join((str(m.ordinal), m.changeset_id, m.relative_path, m.checksum)) for m in discover_migrations())
    return ("\n".join(rows) + "\n").encode()


class CliLocalDbInitIntegrationTests(CliIntegrationTestCase):
    def test_local_db_init_from_source_dry_run_requires_explicit_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_exit, _setup_stdout, setup_stderr = self.run_module_entrypoint(
                "local", "setup", "--repo-map-home", str(home), "--json",
            )
            self.assertEqual(setup_exit, 0, setup_stderr)
            identity = LocalRuntimeIdentity.from_home(home)
            inspect_payload = json.dumps([{"Id": "container-123", "Config": {"Image": "postgres:16-alpine", "Labels": identity.labels("postgres")}}])

            calls: list[list[str]] = []

            def fake_runner(command, **kwargs):
                calls.append(list(command))
                if command[:2] == ["docker", "inspect"]:
                    return subprocess.CompletedProcess(command, 0, stdout=inspect_payload, stderr="")
                if command[:2] == ["docker", "exec"]:
                    return subprocess.CompletedProcess(command, 0, stdout=b"0\n", stderr=b"")
                raise AssertionError(command)

            missing_exit, missing_stdout, missing_stderr = self.run_module_entrypoint(
                "local", "db", "init", "--repo-map-home", str(home), "--database", "repomap", "--json",
            )
            both_exit, both_stdout, both_stderr = self.run_module_entrypoint(
                "local", "db", "init", "--repo-map-home", str(home), "--database", "repomap",
                "--from-source", "--from-dump", str(home / "backups" / "missing"), "--json",
            )

            with patch("repomap_kg.runtime.backup.subprocess.run", side_effect=fake_runner):
                exit_code, stdout, stderr = self.run_repo_map_in_process(
                    "local", "db", "init", "--repo-map-home", str(home), "--database", "repomap",
                    "--from-source", "--dry-run", "--json",
                )

        self.assertEqual(missing_exit, 2)
        self.assertEqual(missing_stdout, "")
        self.assertIn("one of the arguments --from-source --from-dump is required", missing_stderr)
        self.assertEqual(both_exit, 2)
        self.assertEqual(both_stdout, "")
        self.assertIn("not allowed with argument", both_stderr)
        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["command"], "init")
        self.assertEqual(payload["source_mode"], "source")
        self.assertEqual(payload["result"], "dry_run")
        self.assertFalse(payload["database_created"])
        self.assertFalse(payload["schema_initialized"])
        self.assertFalse(payload["direct_db_required"])
        self.assertFalse(payload["destructive_db_actions"])
        self.assertNotIn("POSTGRES_PASSWORD", stdout)
    def test_local_db_init_from_dump_dry_run_validates_fixture_backup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_exit, _setup_stdout, setup_stderr = self.run_module_entrypoint(
                "local", "setup", "--repo-map-home", str(home), "--json",
            )
            self.assertEqual(setup_exit, 0, setup_stderr)
            identity = LocalRuntimeIdentity.from_home(home)
            inspect_payload = json.dumps([{"Id": "container-123", "Config": {"Image": "postgres:16-alpine", "Labels": identity.labels("postgres")}}])
            backup_dir = home / "backups" / identity.home_hash / "repomap" / "20260702T010203Z"
            backup_dir.mkdir(parents=True)
            dump = b"fake-cli-restore-dump"
            (backup_dir / "dump.pgcustom").write_bytes(dump)
            manifest = {
                "backup_format_version": 1,
                "backup_id": f"{identity.home_hash}--repomap--20260702T010203Z",
                "backup_kind": "manual-dump",
                "runtime_id": identity.home_hash,
                "database": "repomap",
                "databases": ["repomap"],
                "timestamp": "20260702T010203Z",
                "dump_files": [
                    {
                        "name": "dump.pgcustom",
                        "size_bytes": len(dump),
                        "sha256": hashlib.sha256(dump).hexdigest(),
                    }
                ],
                "dump_format": "pgcustom",
                "restore_supported": False,
            }
            (backup_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

            calls: list[list[str]] = []

            def fake_runner(command, **kwargs):
                calls.append(list(command))
                if command[:2] == ["docker", "inspect"]:
                    return subprocess.CompletedProcess(command, 0, stdout=inspect_payload, stderr="")
                if command[:2] == ["docker", "exec"]:
                    return subprocess.CompletedProcess(command, 0, stdout=b"0\n", stderr=b"")
                raise AssertionError(command)

            with patch("repomap_kg.runtime.backup.subprocess.run", side_effect=fake_runner):
                exit_code, stdout, stderr = self.run_repo_map_in_process(
                    "local", "db", "init", "--repo-map-home", str(home), "--database", "repomap",
                    "--from-dump", str(backup_dir), "--dry-run", "--json",
                )

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["source_mode"], "dump")
        self.assertEqual(payload["backup_id"], manifest["backup_id"])
        self.assertEqual(payload["dump_file"], "dump.pgcustom")
        self.assertTrue(payload["checksum_verified"])
        self.assertFalse(payload["dump_restored"])
        self.assertIn("restore-dump", payload["planned_actions"])
        self.assertNotIn("planned_command", payload)
        self.assertNotIn("pg_restore", stdout)
        self.assertNotIn("POSTGRES_PASSWORD", stdout)
    def test_local_db_init_from_source_success_applies_schema_with_fake_container(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_exit, _setup_stdout, setup_stderr = self.run_module_entrypoint(
                "local", "setup", "--repo-map-home", str(home), "--json",
            )
            self.assertEqual(setup_exit, 0, setup_stderr)
            identity = LocalRuntimeIdentity.from_home(home)
            inspect_payload = json.dumps([{"Id": "container-123", "Config": {"Image": "postgres:16-alpine", "Labels": identity.labels("postgres")}}])
            calls = []

            def fake_runner(command, **kwargs):
                calls.append((command, kwargs))
                if command[:2] == ["docker", "inspect"]:
                    return subprocess.CompletedProcess(command, 0, stdout=inspect_payload, stderr="")
                if "to_regclass('public.repomap_schema_migrations')" in " ".join(command):
                    return subprocess.CompletedProcess(command, 0, stdout=b"t\n", stderr=b"")
                if "FROM repomap_schema_migrations ORDER BY ordinal" in " ".join(command):
                    return subprocess.CompletedProcess(
                        command, 0, stdout=_ready_ledger_output(), stderr=b""
                    )
                if command[:2] == ["docker", "exec"] and "-tAc" in command:
                    return subprocess.CompletedProcess(command, 0, stdout=b"0\n", stderr=b"")
                if command[:2] == ["docker", "exec"]:
                    return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")
                raise AssertionError(command)

            with patch("repomap_kg.runtime.backup.subprocess.run", side_effect=fake_runner):
                exit_code, stdout, stderr = self.run_repo_map_in_process(
                    "local", "db", "init", "--repo-map-home", str(home), "--database", "repomap", "--from-source",
                )

        self.assertEqual(exit_code, 0, stderr)
        self.assertIn("RepoMap local DB init: result=success", stdout)
        self.assertIn("source_mode=source", stdout)
        self.assertIn("database_created=true", stdout)
        self.assertIn("schema_initialized=true", stdout)
        self.assertTrue(
            any(
                call[0][:2] == ["docker", "exec"]
                and "-i" in call[0]
                and isinstance(call[1].get("input"), bytes)
                and b"CREATE TABLE" in call[1]["input"]
                for call in calls
            )
        )
        self.assertFalse(any("5432" in " ".join(call[0]) for call in calls))
        self.assertNotIn("POSTGRES_PASSWORD", stdout + stderr)
    def test_local_db_init_from_dump_success_and_existing_db_refusal_are_safe(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_exit, _setup_stdout, setup_stderr = self.run_module_entrypoint(
                "local", "setup", "--repo-map-home", str(home), "--json",
            )
            self.assertEqual(setup_exit, 0, setup_stderr)
            identity = LocalRuntimeIdentity.from_home(home)
            inspect_payload = json.dumps([{"Id": "container-123", "Config": {"Image": "postgres:16-alpine", "Labels": identity.labels("postgres")}}])
            backup_dir = home / "backups" / identity.home_hash / "repomap" / "20260702T010203Z"
            backup_dir.mkdir(parents=True)
            dump = b"fake-cli-restore-dump"
            (backup_dir / "dump.pgcustom").write_bytes(dump)
            manifest = {
                "backup_format_version": 1,
                "backup_id": f"{identity.home_hash}--repomap--20260702T010203Z",
                "backup_kind": "manual-dump",
                "runtime_id": identity.home_hash,
                "database": "repomap",
                "databases": ["repomap"],
                "timestamp": "20260702T010203Z",
                "dump_files": [
                    {
                        "name": "dump.pgcustom",
                        "size_bytes": len(dump),
                        "sha256": hashlib.sha256(dump).hexdigest(),
                    }
                ],
                "dump_format": "pgcustom",
                "restore_supported": True,
            }
            (backup_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            calls = []
            restore_chunks: list[bytes] = []

            def success_runner(command, **kwargs):
                calls.append((command, kwargs))
                if command[:2] == ["docker", "inspect"]:
                    return subprocess.CompletedProcess(command, 0, stdout=inspect_payload, stderr="")
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
                    while chunk := stream.read(5):
                        restore_chunks.append(chunk)
                    return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")
                if command[:2] == ["docker", "exec"]:
                    return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")
                raise AssertionError(command)

            with patch("repomap_kg.runtime.backup.subprocess.run", side_effect=success_runner):
                exit_code, stdout, stderr = self.run_repo_map_in_process(
                    "local", "db", "init", "--repo-map-home", str(home), "--database", "repomap",
                    "--from-dump", str(backup_dir / "manifest.json"), "--json",
                )

            existing_calls = []

            def existing_runner(command, **kwargs):
                existing_calls.append(command)
                if command[:2] == ["docker", "inspect"]:
                    return subprocess.CompletedProcess(command, 0, stdout=inspect_payload, stderr="")
                if command[:2] == ["docker", "exec"] and "-tAc" in command:
                    return subprocess.CompletedProcess(command, 0, stdout=b"1\n", stderr=b"")
                raise AssertionError(command)

            with patch("repomap_kg.runtime.backup.subprocess.run", side_effect=existing_runner):
                exists_exit, exists_stdout, exists_stderr = self.run_repo_map_in_process(
                    "local", "db", "init", "--repo-map-home", str(home), "--database", "repomap",
                    "--from-dump", f"{identity.home_hash}--repomap--20260702T010203Z", "--json",
                )

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["result"], "success")
        self.assertEqual(payload["source_mode"], "dump")
        self.assertTrue(payload["database_created"])
        self.assertTrue(payload["dump_restored"])
        self.assertTrue(payload["checksum_verified"])
        self.assertTrue(
            any(
                call[0][:2] == ["docker", "exec"]
                and "/usr/bin/pg_restore" in call[0]
                for call in calls
            )
        )
        self.assertEqual(b"".join(restore_chunks), dump)
        self.assertGreater(len(restore_chunks), 1)
        self.assertEqual(exists_exit, 1)
        self.assertEqual(exists_stdout, "")
        self.assertIn("target database already exists", exists_stderr)
        self.assertFalse(any("CREATE DATABASE" in " ".join(command) for command in existing_calls))
        self.assertNotIn("POSTGRES_PASSWORD", stdout + stderr + exists_stderr)
    def test_local_db_init_from_dump_rejects_bad_backup_before_container_access(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_exit, _setup_stdout, setup_stderr = self.run_module_entrypoint(
                "local",
                "setup",
                "--repo-map-home",
                str(home),
                "--json",
            )
            self.assertEqual(setup_exit, 0, setup_stderr)
            identity = LocalRuntimeIdentity.from_home(home)
            backup_dir = home / "backups" / identity.home_hash / "repomap" / "20260702T010203Z"
            backup_dir.mkdir(parents=True)
            (backup_dir / "dump.pgcustom").write_bytes(b"changed")
            (backup_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "backup_format_version": 1,
                        "backup_id": f"{identity.home_hash}--repomap--20260702T010203Z",
                        "backup_kind": "manual-dump",
                        "runtime_id": identity.home_hash,
                        "database": "repomap",
                        "databases": ["repomap"],
                        "timestamp": "20260702T010203Z",
                        "dump_files": [
                            {
                                "name": "dump.pgcustom",
                                "size_bytes": 4,
                                "sha256": hashlib.sha256(b"dump").hexdigest(),
                            }
                        ],
                        "dump_format": "pgcustom",
                    }
                ),
                encoding="utf-8",
            )

            with patch("repomap_kg.runtime.backup.subprocess.run") as run_mock:
                checksum_exit, checksum_stdout, checksum_stderr = self.run_repo_map_in_process(
                    "local",
                    "db",
                    "init",
                    "--repo-map-home",
                    str(home),
                    "--database",
                    "repomap",
                    "--from-dump",
                    str(backup_dir),
                    "--dry-run",
                    "--json",
                )

            outside_exit, outside_stdout, outside_stderr = self.run_module_entrypoint(
                "local",
                "db",
                "init",
                "--repo-map-home",
                str(home),
                "--database",
                "repomap",
                "--from-dump",
                str(Path(tmpdir) / "outside" / "manifest.json"),
                "--dry-run",
                "--json",
            )

        self.assertEqual(checksum_exit, 1)
        self.assertEqual(checksum_stdout, "")
        self.assertIn("backup dump checksum does not match manifest", checksum_stderr)
        run_mock.assert_not_called()
        self.assertEqual(outside_exit, 1)
        self.assertEqual(outside_stdout, "")
        self.assertIn("backup path must stay under REPOMAP_HOME/backups", outside_stderr)
