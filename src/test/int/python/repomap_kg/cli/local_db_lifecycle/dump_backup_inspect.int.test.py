import hashlib
import json
import subprocess
import tempfile
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

from repomap_test_support.cli_integration import (
    CliIntegrationTestCase,
)

from repomap_kg.runtime.local import LocalRuntimeIdentity


class CliLocalDbDumpBackupInspectIntegrationTests(CliIntegrationTestCase):
    def test_local_db_dump_dry_run_plans_backup_without_starting_runtime(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_exit, _setup_stdout, setup_stderr = self.run_module_entrypoint(
                "local", "setup", "--repo-map-home", str(home), "--json",
            )
            self.assertEqual(setup_exit, 0, setup_stderr)

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "local", "db", "dump", "--repo-map-home", str(home), "--database", "repomap",
                "--reason", "integration dry run", "--dry-run", "--json",
            )

            self.assertEqual(exit_code, 0, stderr)
            payload = json.loads(stdout)
            self.assertEqual(payload["command"], "dump")
            self.assertEqual(payload["result"], "dry_run")
            self.assertFalse(payload["backup_path_created"])
            self.assertFalse(payload["direct_db_required"])
            self.assertFalse(payload["destructive_db_actions"])
            self.assertFalse(payload["dump_executed"])
            self.assertFalse((home / "backups").exists())
            self.assertNotIn("POSTGRES_PASSWORD", stdout)
    def test_local_db_backups_and_backup_info_read_manifest_fixture(self):
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

            list_exit, list_stdout, list_stderr = self.run_module_entrypoint(
                "local", "db", "backups", "--repo-map-home", str(home), "--json",
            )
            list_table_exit, list_table_stdout, list_table_stderr = self.run_module_entrypoint(
                "local", "db", "backups", "--repo-map-home", str(home),
            )
            info_exit, info_stdout, info_stderr = self.run_module_entrypoint(
                "local", "db", "backup-info", "--repo-map-home", str(home),
                "runtime123--repomap--20260702T010203Z", "--json",
            )
            info_table_exit, info_table_stdout, info_table_stderr = self.run_module_entrypoint(
                "local", "db", "backup-info", "--repo-map-home", str(home), str(backup_dir / "manifest.json"),
            )

        self.assertEqual(list_exit, 0, list_stderr)
        listing = json.loads(list_stdout)
        self.assertEqual(listing["backup_count"], 1)
        self.assertEqual(listing["backups"][0]["backup_id"], manifest["backup_id"])
        self.assertEqual(list_table_exit, 0, list_table_stderr)
        self.assertIn("RepoMap local DB backups", list_table_stdout)
        self.assertIn("runtime123--repomap--20260702T010203Z", list_table_stdout)
        self.assertEqual(info_exit, 0, info_stderr)
        info = json.loads(info_stdout)
        self.assertEqual(info["manifest"]["backup_id"], manifest["backup_id"])
        self.assertFalse(info["manifest"]["restore_supported"])
        self.assertEqual(info_table_exit, 0, info_table_stderr)
        self.assertIn("RepoMap local DB backup info", info_table_stdout)
        self.assertIn("restore_supported=false", info_table_stdout)
        self.assertNotIn(
            "POSTGRES_PASSWORD",
            list_stdout + info_stdout + list_table_stdout + info_table_stdout,
        )
    def test_live_ops6_local_db_backup_inspect_reports_bounded_toc(self):
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
            dump_bytes = b"synthetic-dump"
            (backup_dir / "dump.pgcustom").write_bytes(dump_bytes)
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
                        "size_bytes": len(dump_bytes),
                        "sha256": hashlib.sha256(dump_bytes).hexdigest(),
                    }
                ],
                "dump_format": "pgcustom",
                "restore_supported": True,
            }
            (backup_dir / "manifest.json").write_text(
                json.dumps(manifest, sort_keys=True),
                encoding="utf-8",
            )
            toc = "\n".join(
                [
                    "1; 1259 16390 TABLE public repositories repomap",
                    "2; 1259 16391 TABLE public raw_observations repomap",
                    "3; 0 16390 TABLE DATA public repositories repomap",
                ]
            )

            def fake_runner(command, **kwargs):
                if command[:2] == ["docker", "inspect"]:
                    return subprocess.CompletedProcess(command, 0, stdout=inspect_payload, stderr="")
                if command[:2] == ["docker", "exec"] and "/usr/bin/pg_restore" in command:
                    self.assertEqual(kwargs.get("input"), dump_bytes)
                    return subprocess.CompletedProcess(command, 0, stdout=toc.encode("utf-8"), stderr=b"")
                raise AssertionError(command)

            with patch("repomap_kg.runtime.backup.subprocess.run", side_effect=fake_runner):
                inspect_exit, inspect_stdout, inspect_stderr = self.run_repo_map_in_process(
                    "local", "db", "backup-inspect", "--repo-map-home", str(home), manifest["backup_id"], "--json",
                )
                inspect_table_exit, inspect_table_stdout, inspect_table_stderr = self.run_repo_map_in_process(
                    "local", "db", "backup-inspect", "--repo-map-home", str(home), manifest["backup_id"],
                )
            info_exit, info_stdout, info_stderr = self.run_module_entrypoint(
                "local", "db", "backup-info", "--repo-map-home", str(home), manifest["backup_id"], "--json",
            )

        self.assertEqual(inspect_exit, 0, inspect_stderr)
        payload = json.loads(inspect_stdout)
        rendered = json.dumps(payload, sort_keys=True)
        self.assertEqual(payload["command"], "backup-inspect")
        self.assertEqual(payload["backup_id"], manifest["backup_id"])
        self.assertTrue(payload["manifest_verified"])
        self.assertTrue(payload["checksum_verified"])
        self.assertTrue(payload["dump_contents_read"])
        self.assertEqual(payload["toc_entry_count"], 3)
        self.assertTrue(payload["expected_repomap_tables"]["repositories"])
        self.assertTrue(payload["expected_repomap_tables"]["raw_observations"])
        self.assertFalse(payload["destructive_db_actions"])
        self.assertFalse(payload["raw_dump_contents_exposed"])
        self.assertFalse(payload["planned_command_exposed"])
        self.assertNotIn(str(home), rendered)
        self.assertNotIn("pg_restore", rendered)
        self.assertNotIn("POSTGRES_PASSWORD", rendered)
        self.assertEqual(inspect_table_exit, 0, inspect_table_stderr)
        self.assertIn("RepoMap local DB backup inspect", inspect_table_stdout)
        self.assertIn("dump_contents_read=true", inspect_table_stdout)
        self.assertEqual(info_exit, 0, info_stderr)
        info = json.loads(info_stdout)
        self.assertEqual(info["command"], "backup-info")
        self.assertFalse(info["dump_contents_read"])
    def test_local_db_dump_writes_manifest_with_fake_owned_container(self):
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
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout=b"fake-cli-dump",
                        stderr=b"",
                    )
                raise AssertionError(command)

            with patch("repomap_kg.runtime.backup.subprocess.run", side_effect=fake_runner):
                exit_code, stdout, stderr = self.run_repo_map_in_process(
                    "local", "db", "dump", "--repo-map-home", str(home), "--database", "repomap", "--json",
                )

            self.assertEqual(exit_code, 0, stderr)
            payload = json.loads(stdout)
            backup_path = next((home / "backups").rglob("manifest.json")).parent
            self.assertEqual(payload["result"], "success")
            self.assertTrue(payload["dump_executed"])
            self.assertTrue((backup_path / "dump.pgcustom").is_file())
            self.assertTrue((backup_path / "manifest.json").is_file())
            self.assertTrue((backup_path / "restore.md").is_file())
            manifest = json.loads((backup_path / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["backup_kind"], "manual-dump")
            self.assertFalse(manifest["direct_db_exposure"]["required"])
            self.assertTrue(manifest["restore_supported"])
            self.assertNotIn("POSTGRES_PASSWORD", stdout)
    def test_local_db_dump_all_uses_exact_configured_graph_control_set(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_exit, _setup_stdout, setup_stderr = self.run_module_entrypoint(
                "local", "setup", "--repo-map-home", str(home), "--json",
            )
            self.assertEqual(setup_exit, 0, setup_stderr)
            identity = LocalRuntimeIdentity.from_home(home)
            inspect_payload = json.dumps([{"Id": "container-123", "Config": {"Image": "postgres:16-alpine", "Labels": identity.labels("postgres")}}])

            def fake_runner(command, **kwargs):
                if command[:2] == ["docker", "inspect"]:
                    return subprocess.CompletedProcess(command, 0, stdout=inspect_payload, stderr="")
                if command[:2] == ["docker", "exec"]:
                    return subprocess.CompletedProcess(command, 0, stdout=b"dump-all", stderr=b"")
                raise AssertionError(command)

            with (
                patch("repomap_kg.cli.maintenance_window_for_coordinated_backup", return_value=nullcontext()),
                patch("repomap_kg.runtime.backup.subprocess.run", side_effect=fake_runner),
            ):
                exit_code, stdout, stderr = self.run_repo_map_in_process(
                    "local", "db", "dump-all", "--repo-map-home", str(home), "--json",
                )

            self.assertEqual(exit_code, 0, stderr)
            payload = json.loads(stdout)
            backup_path = next((home / "backups").rglob("manifest.json")).parent
            self.assertEqual(payload["backup_kind"], "manual-dump-all")
            self.assertEqual(
                payload["databases"],
                ["repomap", "repomap_control"],
            )
            self.assertTrue((backup_path / "repomap.pgcustom").is_file())
            self.assertTrue((backup_path / "repomap_control.pgcustom").is_file())
            manifest = json.loads((backup_path / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(
                manifest["scope"],
                "exact-configured-graph-control-databases",
            )
            self.assertEqual(
                [item["name"] for item in manifest["dump_files"]],
                ["repomap.pgcustom", "repomap_control.pgcustom"],
            )
            self.assertEqual(manifest["recovery_point"]["status"], "stable")
    def test_local_db_dump_all_dry_run_and_error_paths_are_safe(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_exit, _setup_stdout, setup_stderr = self.run_module_entrypoint(
                "local", "setup", "--repo-map-home", str(home), "--json",
            )
            self.assertEqual(setup_exit, 0, setup_stderr)
            identity = LocalRuntimeIdentity.from_home(home)
            inspect_payload = json.dumps([{"Id": "container-123", "Config": {"Image": "postgres:16-alpine", "Labels": identity.labels("postgres")}}])

            dry_exit, dry_stdout, dry_stderr = self.run_module_entrypoint(
                "local", "db", "dump-all", "--repo-map-home", str(home), "--dry-run", "--json",
            )
            bad_name_exit, bad_name_stdout, bad_name_stderr = self.run_module_entrypoint(
                "local", "db", "dump", "--repo-map-home", str(home), "--database", "../repomap", "--dry-run", "--json",
            )

            def unowned_runner(command, **kwargs):
                unowned_payload = json.dumps([{"Id": "container-123", "Config": {"Image": "postgres:16-alpine", "Labels": {"org.repomap.runtime": "false"}}}])
                return subprocess.CompletedProcess(command, 0, stdout=unowned_payload, stderr="")

            with patch("repomap_kg.runtime.backup.subprocess.run", side_effect=unowned_runner):
                unowned_exit, unowned_stdout, unowned_stderr = self.run_repo_map_in_process(
                    "local", "db", "dump", "--repo-map-home", str(home), "--database", "repomap", "--json",
                )

            def failing_runner(command, **kwargs):
                if command[:2] == ["docker", "inspect"]:
                    return subprocess.CompletedProcess(command, 0, stdout=inspect_payload, stderr="")
                return subprocess.CompletedProcess(
                    command, 1, stdout=b"", stderr=b"POSTGRES_PASSWORD=fake-cli-secret password=fake-cli-secret"
                )

            with patch("repomap_kg.runtime.backup.subprocess.run", side_effect=failing_runner):
                fail_exit, fail_stdout, fail_stderr = self.run_repo_map_in_process(
                    "local", "db", "dump", "--repo-map-home", str(home), "--database", "repomap", "--json",
                )

        self.assertEqual(dry_exit, 0, dry_stderr)
        dry_payload = json.loads(dry_stdout)
        self.assertEqual(dry_payload["command"], "dump-all")
        self.assertEqual(
            dry_payload["databases"],
            ["repomap", "repomap_control"],
        )
        self.assertFalse(dry_payload["backup_path_created"])
        self.assertEqual(bad_name_exit, 1)
        self.assertEqual(bad_name_stdout, "")
        self.assertIn("database name must be a safe PostgreSQL identifier", bad_name_stderr)
        self.assertEqual(unowned_exit, 1)
        self.assertEqual(unowned_stdout, "")
        self.assertIn("not RepoMap-owned", unowned_stderr)
        self.assertEqual(fail_exit, 1)
        self.assertEqual(fail_stdout, "")
        self.assertIn("[REDACTED]", fail_stderr)
        self.assertNotIn("fake-cli-secret", fail_stderr)
        self.assertEqual(list((home / "backups").rglob("manifest.json")), [])
        self.assertEqual(list((home / "backups").rglob("*.pgcustom")), [])
