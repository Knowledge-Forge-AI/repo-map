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


class CliLocalDbDropGuardIntegrationTests(CliIntegrationTestCase):
    def test_local_db_drop_requires_backup_first_confirmation_and_supports_dry_run(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_exit, _setup_stdout, setup_stderr = self.run_module_entrypoint(
                "local", "setup", "--repo-map-home", str(home), "--json",
            )
            self.assertEqual(setup_exit, 0, setup_stderr)
            identity = LocalRuntimeIdentity.from_home(home)

            missing_backup_exit, missing_backup_stdout, missing_backup_stderr = self.run_module_entrypoint(
                "local", "db", "drop", "--repo-map-home", str(home), "--database", "repomap", "--dry-run", "--json",
            )
            missing_yes_exit, missing_yes_stdout, missing_yes_stderr = self.run_module_entrypoint(
                "local", "db", "drop", "--repo-map-home", str(home), "--database", "repomap", "--backup-first", "--json",
            )

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
                    return subprocess.CompletedProcess(command, 0, stdout=b"1\n", stderr=b"")
                raise AssertionError(command)

            with patch(
                "repomap_kg.runtime.backup.subprocess.run",
                side_effect=fake_runner,
            ):
                dry_exit, dry_stdout, dry_stderr = self.run_repo_map_in_process(
                    "local", "db", "drop", "--repo-map-home", str(home), "--database", "repomap", "--backup-first", "--dry-run", "--json",
                )

        self.assertEqual(missing_backup_exit, 1)
        self.assertEqual(missing_backup_stdout, "")
        self.assertIn("backup-first", missing_backup_stderr)
        self.assertEqual(missing_yes_exit, 1)
        self.assertEqual(missing_yes_stdout, "")
        self.assertIn("confirmation", missing_yes_stderr)
        self.assertEqual(dry_exit, 0, dry_stderr)
        payload = json.loads(dry_stdout)
        self.assertEqual(payload["command"], "drop")
        self.assertEqual(payload["result"], "dry_run")
        self.assertTrue(payload["backup_first"])
        self.assertFalse(payload["confirmation_received"])
        self.assertFalse(payload["database_dropped"])
        self.assertFalse(payload["backup_path_created"])
        self.assertIn("init --database repomap --from-dump", payload["restore_command_hint"])
        self.assertNotIn("POSTGRES_PASSWORD", dry_stdout)
    def test_local_db_drop_fake_runtime_orders_backup_verify_then_drop(self):
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
            events = []

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

            with (
                patch(
                    "repomap_kg.cli.maintenance_window_for_database_drop",
                    return_value=nullcontext(),
                ),
                patch(
                    "repomap_kg.runtime.backup.subprocess.run",
                    side_effect=fake_runner,
                ),
            ):
                exit_code, stdout, stderr = self.run_repo_map_in_process(
                    "local",
                    "db",
                    "drop",
                    "--repo-map-home",
                    str(home),
                    "--database",
                    "repomap",
                    "--backup-first",
                    "--yes",
                    "--reason",
                    "integration drop",
                    "--json",
                )

            payload = json.loads(stdout) if stdout else {}
            backup_path = next((home / "backups").rglob("manifest.json")).parent
            manifest_exists = (backup_path / "manifest.json").is_file()
            restore_exists = (backup_path / "restore.md").is_file()

        self.assertEqual(exit_code, 0, stderr)
        self.assertEqual(payload["result"], "success")
        self.assertTrue(payload["checksum_verified"])
        self.assertTrue(payload["database_dropped"])
        self.assertTrue(payload["destructive_db_actions"])
        self.assertLess(events.index("backup"), events.index("drop"))
        self.assertTrue(manifest_exists)
        self.assertTrue(restore_exists)
        self.assertIn("init --database repomap --from-dump", payload["restore_command_hint"])
        self.assertNotIn("POSTGRES_PASSWORD", stdout)
    def test_local_db_drop_failure_paths_are_safe_and_table_output_is_bounded(self):
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

            system_exit, system_stdout, system_stderr = self.run_module_entrypoint(
                "local",
                "db",
                "drop",
                "--repo-map-home",
                str(home),
                "--database",
                "postgres",
                "--backup-first",
                "--dry-run",
                "--json",
            )

            missing_events = []

            def missing_runner(command, **kwargs):
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
                if command[:2] == ["docker", "exec"] and "-tAc" in command:
                    missing_events.append("exists")
                    return subprocess.CompletedProcess(command, 0, stdout=b"0\n", stderr=b"")
                missing_events.append("unexpected")
                return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

            with (
                patch(
                    "repomap_kg.cli.maintenance_window_for_database_drop",
                    return_value=nullcontext(),
                ),
                patch(
                    "repomap_kg.runtime.backup.subprocess.run",
                    side_effect=missing_runner,
                ),
            ):
                missing_exit, missing_stdout, missing_stderr = self.run_repo_map_in_process(
                    "local",
                    "db",
                    "drop",
                    "--repo-map-home",
                    str(home),
                    "--database",
                    "repomap",
                    "--backup-first",
                    "--yes",
                    "--json",
                )

            def table_runner(command, **kwargs):
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
                    return subprocess.CompletedProcess(command, 0, stdout=b"1\n", stderr=b"")
                raise AssertionError(command)

            with patch("repomap_kg.runtime.backup.subprocess.run", side_effect=table_runner):
                table_exit, table_stdout, table_stderr = self.run_repo_map_in_process(
                    "local",
                    "db",
                    "drop",
                    "--repo-map-home",
                    str(home),
                    "--database",
                    "repomap",
                    "--backup-first",
                    "--dry-run",
                )

            def failing_backup_runner(command, **kwargs):
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
                if command[:2] == ["docker", "exec"] and "-tAc" in command:
                    return subprocess.CompletedProcess(command, 0, stdout=b"1\n", stderr=b"")
                if command[:2] == ["docker", "exec"] and "/usr/bin/pg_dump" in command:
                    return subprocess.CompletedProcess(
                        command,
                        1,
                        stdout=b"",
                        stderr=b"POSTGRES_PASSWORD=fake-secret password=fake-secret",
                    )
                raise AssertionError(command)

            with (
                patch(
                    "repomap_kg.cli.maintenance_window_for_database_drop",
                    return_value=nullcontext(),
                ),
                patch(
                    "repomap_kg.runtime.backup.subprocess.run",
                    side_effect=failing_backup_runner,
                ),
            ):
                backup_exit, backup_stdout, backup_stderr = self.run_repo_map_in_process(
                    "local",
                    "db",
                    "drop",
                    "--repo-map-home",
                    str(home),
                    "--database",
                    "repomap",
                    "--backup-first",
                    "--yes",
                    "--json",
                )

        self.assertEqual(system_exit, 1)
        self.assertEqual(system_stdout, "")
        self.assertIn("authorized RepoMap lifecycle target", system_stderr)
        self.assertEqual(missing_exit, 1)
        self.assertEqual(missing_stdout, "")
        self.assertIn("target database does not exist", missing_stderr)
        self.assertEqual(missing_events, ["exists"])
        self.assertEqual(table_exit, 0, table_stderr)
        self.assertIn("RepoMap local DB drop: result=dry_run", table_stdout)
        self.assertIn("backup_first=true", table_stdout)
        self.assertIn("restore_command=", table_stdout)
        self.assertEqual(backup_exit, 1)
        self.assertEqual(backup_stdout, "")
        self.assertIn("[REDACTED]", backup_stderr)
        self.assertNotIn("fake-secret", backup_stderr)
    def test_local_db_drop_has_no_backup_bypass_flags(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            for flag in ("--no-backup", "--force-no-backup", "--wipe", "--reset", "--truncate", "--clear"):
                exit_code, stdout, stderr = self.run_module_entrypoint(
                    "local",
                    "db",
                    "drop",
                    "--repo-map-home",
                    str(home),
                    "--database",
                    "repomap",
                    "--backup-first",
                    "--dry-run",
                    flag,
                )

                self.assertEqual(exit_code, 2)
                self.assertEqual(stdout, "")
                self.assertIn("unrecognized arguments", stderr)
    def test_local_db_does_not_register_destructive_lifecycle_commands(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            for command in ("restore", "drop-all", "wipe", "reset", "truncate", "clear"):
                exit_code, stdout, stderr = self.run_module_entrypoint(
                    "local",
                    "db",
                    command,
                    "--repo-map-home",
                    str(home),
                )

                self.assertEqual(exit_code, 2)
                self.assertEqual(stdout, "")
                self.assertIn("invalid choice", stderr)

            for flag in ("--replace", "--force", "--drop-existing", "--overwrite", "--reset"):
                exit_code, stdout, stderr = self.run_module_entrypoint(
                    "local",
                    "db",
                    "init",
                    "--repo-map-home",
                    str(home),
                    "--database",
                    "repomap",
                    "--from-source",
                    flag,
                )

                self.assertEqual(exit_code, 2)
                self.assertEqual(stdout, "")
                self.assertIn("unrecognized arguments", stderr)
