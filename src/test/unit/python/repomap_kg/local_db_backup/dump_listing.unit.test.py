import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from repomap_test_support.local_db_backup import LocalDbBackupUnitTestCase

from repomap_kg.runtime.backup import (
    LocalDbBackupError,
    dump_all_databases,
    dump_database,
    list_backups,
    read_backup_info,
)
from repomap_kg.runtime.local import LocalRuntimeIdentity, setup_local_runtime


class LocalDbBackupDumpListingUnitTests(LocalDbBackupUnitTestCase):
    def test_dump_dry_run_plans_backup_without_creating_directory_or_requiring_direct_db(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)

            result = dump_database(
                home,
                database="repomap",
                dry_run=True,
                timestamp="20260702T010203Z",
                reason="test backup",
            )

            payload = result.to_jsonable()
            self.assertEqual(payload["command"], "dump")
            self.assertEqual(payload["result"], "dry_run")
            self.assertEqual(payload["database"], "repomap")
            self.assertEqual(payload["backup_kind"], "manual-dump")
            self.assertIn("/backups/", str(result.plan.backup_path))
            self.assertTrue(str(result.plan.backup_path).endswith("/repomap/20260702T010203Z"))
            self.assertFalse(result.plan.backup_path.exists())
            self.assertFalse(payload["direct_db_required"])
            self.assertFalse(payload["destructive_db_actions"])
            self.assertFalse(payload["dump_executed"])
            self.assertEqual(result.planned_command[:3], ("docker", "exec", "-e"))
            self.assertNotIn("POSTGRES_PASSWORD", json.dumps(payload))

    def test_dump_writes_pgcustom_manifest_restore_doc_and_checksum_from_owned_container(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            identity = LocalRuntimeIdentity.from_home(home)
            calls: list[list[str]] = []

            def fake_runner(command, **kwargs):
                calls.append(list(command))
                if command[:2] == ["docker", "inspect"]:
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout=json.dumps(
                            [
                                {
                                    "Id": "container-123",
                                    "Config": {
                                        "Image": "postgres:16-alpine",
                                        "Labels": identity.labels("postgres"),
                                    },
                                }
                            ]
                        ),
                        stderr="",
                    )
                if command[:2] == ["docker", "exec"]:
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout=b"fake-pgcustom-dump",
                        stderr=b"",
                    )
                raise AssertionError(command)

            result = dump_database(
                home,
                database="repomap",
                timestamp="20260702T010203Z",
                command_runner=fake_runner,
            )

            self.assertTrue(result.to_jsonable())
            backup_path = result.plan.backup_path
            dump_path = backup_path / "dump.pgcustom"
            manifest_path = backup_path / "manifest.json"
            restore_path = backup_path / "restore.md"
            self.assertTrue(dump_path.is_file())
            self.assertTrue(manifest_path.is_file())
            self.assertTrue(restore_path.is_file())
            self.assertEqual(dump_path.read_bytes(), b"fake-pgcustom-dump")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["backup_format_version"], 1)
            self.assertEqual(manifest["backup_kind"], "manual-dump")
            self.assertEqual(manifest["database"], "repomap")
            self.assertEqual(manifest["container"]["name"], identity.postgres_container)
            self.assertEqual(manifest["dump_files"][0]["name"], "dump.pgcustom")
            self.assertEqual(
                manifest["dump_files"][0]["sha256"],
                hashlib.sha256(b"fake-pgcustom-dump").hexdigest(),
            )
            self.assertFalse(manifest["direct_db_exposure"]["enabled"])
            self.assertTrue(manifest["restore_supported"])
            self.assertIn("new databases only", restore_path.read_text(encoding="utf-8"))
            self.assertNotIn("POSTGRES_PASSWORD", json.dumps(manifest))
            self.assertIn(["docker", "inspect", identity.postgres_container], calls)
            self.assertTrue(any(call[:2] == ["docker", "exec"] for call in calls))

    def test_dump_refuses_unsafe_database_names_and_unowned_containers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            with self.assertRaises(LocalDbBackupError):
                dump_database(home, database="../repomap", dry_run=True)

            def fake_runner(command, **kwargs):
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps(
                        [
                            {
                                "Id": "container-123",
                                "Config": {
                                    "Image": "postgres:16-alpine",
                                    "Labels": {"org.repomap.runtime": "false"},
                                },
                            }
                        ]
                    ),
                    stderr="",
                )

            with self.assertRaises(LocalDbBackupError) as caught:
                dump_database(
                    home,
                    database="repomap",
                    timestamp="20260702T010203Z",
                    command_runner=fake_runner,
                )
            self.assertIn("not RepoMap-owned", str(caught.exception))

    def test_dump_all_captures_exact_configured_graph_control_set(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            identity = LocalRuntimeIdentity.from_home(home)

            def fake_runner(command, **kwargs):
                if command[:2] == ["docker", "inspect"]:
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout=json.dumps(
                            [
                                {
                                    "Id": "container-123",
                                    "Config": {
                                        "Image": "postgres:16-alpine",
                                        "Labels": identity.labels("postgres"),
                                    },
                                }
                            ]
                        ),
                        stderr="",
                    )
                if command[:2] == ["docker", "exec"]:
                    return subprocess.CompletedProcess(command, 0, stdout=b"dump", stderr=b"")
                raise AssertionError(command)

            result = dump_all_databases(
                home,
                timestamp="20260702T010203Z",
                command_runner=fake_runner,
            )

            payload = result.to_jsonable()
            self.assertEqual(payload["command"], "dump-all")
            self.assertEqual(payload["backup_kind"], "manual-dump-all")
            self.assertEqual(
                payload["databases"],
                list(result.plan.plan.owned_databases),
            )
            self.assertTrue(str(result.plan.backup_path).endswith("/all-databases/20260702T010203Z"))
            manifest = json.loads(
                (result.plan.backup_path / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                manifest["scope"],
                "exact-configured-graph-control-databases",
            )
            self.assertEqual(
                [item["name"] for item in manifest["dump_files"]],
                [
                    f"{database}.pgcustom"
                    for database in result.plan.plan.owned_databases
                ],
            )
            self.assertNotIn("recovery_point", manifest)

    def test_backups_listing_and_backup_info_read_manifests_only_under_backup_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            backup_dir = home / "backups" / "runtime123" / "repomap" / "20260702T010203Z"
            backup_dir.mkdir(parents=True)
            manifest = {
                "backup_format_version": 1,
                "backup_id": "runtime123--repomap--20260702T010203Z",
                "backup_kind": "manual-dump",
                "runtime_id": "runtime123",
                "database": "repomap",
                "timestamp": "20260702T010203Z",
                "dump_files": [
                    {
                        "name": "dump.pgcustom",
                        "size_bytes": 4,
                        "sha256": hashlib.sha256(b"dump").hexdigest(),
                    }
                ],
                "restore_supported": False,
            }
            (backup_dir / "manifest.json").write_text(
                json.dumps(manifest, sort_keys=True),
                encoding="utf-8",
            )
            (backup_dir / "dump.pgcustom").write_bytes(b"dump")

            listing = list_backups(home)
            info = read_backup_info(home, "runtime123--repomap--20260702T010203Z")

            self.assertEqual(listing.to_jsonable()["backup_count"], 1)
            self.assertEqual(info.to_jsonable()["manifest"]["backup_id"], manifest["backup_id"])
            with self.assertRaises(LocalDbBackupError):
                read_backup_info(home, Path(tmpdir) / "outside" / "manifest.json")

    def test_dump_refuses_to_overwrite_existing_backup_directory_before_container_access(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            identity = LocalRuntimeIdentity.from_home(home)
            backup_dir = home / "backups" / identity.home_hash / "repomap" / "20260702T010203Z"
            backup_dir.mkdir(parents=True)

            def unexpected_runner(command, **kwargs):
                raise AssertionError(command)

            with self.assertRaises(LocalDbBackupError) as caught:
                dump_database(
                    home,
                    database="repomap",
                    timestamp="20260702T010203Z",
                    command_runner=unexpected_runner,
                )

            self.assertEqual(caught.exception.diagnostics[0].code, "backup-directory-exists")

    def test_dump_reports_missing_password_and_pg_dump_failures_without_secret_leakage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            identity = LocalRuntimeIdentity.from_home(home)
            (home / "runtime" / ".env").write_text(
                "REPOMAP_PG_PASSWORD=fake-secret-value\n",
                encoding="utf-8",
            )

            def inspect_runner(command, **kwargs):
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps(
                        [
                            {
                                "Id": "container-123",
                                "Config": {
                                    "Image": "postgres:16-alpine",
                                    "Labels": identity.labels("postgres"),
                                },
                            }
                        ]
                    ),
                    stderr="",
                )

            with self.assertRaises(LocalDbBackupError) as caught:
                dump_database(
                    home,
                    database="repomap",
                    timestamp="20260702T010203Z",
                    command_runner=inspect_runner,
                )
            self.assertEqual(caught.exception.diagnostics[0].code, "runtime-password-missing")

            (home / "runtime" / ".env").write_text(
                "POSTGRES_PASSWORD=fake-secret-value\n"
                "REPOMAP_PG_PASSWORD=fake-secret-value\n",
                encoding="utf-8",
            )

            def failing_dump_runner(command, **kwargs):
                if command[:2] == ["docker", "inspect"]:
                    return inspect_runner(command, **kwargs)
                return subprocess.CompletedProcess(
                    command,
                    1,
                    stdout=b"",
                    stderr=b"POSTGRES_PASSWORD=fake-secret-value password=fake-secret-value",
                )

            with self.assertRaises(LocalDbBackupError) as dump_error:
                dump_database(
                    home,
                    database="repomap",
                    timestamp="20260702T010204Z",
                    command_runner=failing_dump_runner,
                )
            rendered = json.dumps(
                [item.to_jsonable() for item in dump_error.exception.diagnostics],
                sort_keys=True,
            )
            self.assertIn("[REDACTED]", rendered)
            self.assertNotIn("fake-secret-value", rendered)
