import json
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from repomap_test_support.cli_integration import (
    CliIntegrationTestCase,
)

from repomap_kg.runtime.backup import verify_drop_backup
from repomap_kg.runtime.local import LocalRuntimeIdentity


class CliLocalDbLifecycleSmokeChainIntegrationTests(CliIntegrationTestCase):
    def test_live_harden1_lifecycle_cli_smoke_chain_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            synthetic_db = "repomap_live_harden1"
            setup_exit, setup_stdout, setup_stderr = self.run_module_entrypoint(
                "local",
                "setup",
                "--repo-map-home",
                str(home),
                "--json",
            )
            self.assertEqual(setup_exit, 0, setup_stderr)
            config_path = home / "repomap.rpl.toml"
            config_text = config_path.read_text(encoding="utf-8")
            graph_marker = 'repository_name = "repo-map"\n'
            self.assertEqual(config_text.count(graph_marker), 1)
            config_path.write_text(
                config_text.replace(
                    graph_marker,
                    graph_marker + f'database = "{synthetic_db}"\n',
                    1,
                ),
                encoding="utf-8",
            )
            setup_payload = json.loads(setup_stdout)
            self.assertIn("created_file_count", setup_payload)
            self.assertNotIn("created_files", setup_payload)
            self.assertNotIn("planned_command", setup_payload)
            self.assert_lifecycle_public_output_safe(
                setup_stdout,
                home,
                allow_container_runtime_label=True,
            )
            identity = LocalRuntimeIdentity.from_home(home)
            dump_bytes = b"live-harden1-synthetic-dump"
            toc = "\n".join(
                [
                    "1; 1259 16390 TABLE public repositories repomap",
                    "2; 1259 16391 TABLE public raw_observations repomap",
                    "3; 1259 16392 TABLE public canonical_nodes repomap",
                    "4; 0 16390 TABLE DATA public repositories repomap",
                    "5; 0 16391 TABLE DATA public raw_observations repomap",
                ]
            )
            events: list[str] = []

            @contextmanager
            def maintenance_window(window_home, database):
                self.assertEqual(Path(window_home), home)
                self.assertEqual(database, synthetic_db)
                events.append("maintenance-enter")
                try:
                    yield
                finally:
                    events.append("maintenance-exit")

            def verify_under_maintenance(backup_result, database):
                self.assertIn("maintenance-enter", events)
                self.assertNotIn("maintenance-exit", events)
                events.append("verify")
                return verify_drop_backup(backup_result, database)

            def fake_runner(command, **kwargs):
                command_text = " ".join(command)
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
                if command[:2] == ["docker", "exec"] and "/usr/bin/pg_restore" in command:
                    events.append("inspect")
                    self.assertEqual(kwargs.get("input"), dump_bytes)
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout=toc.encode("utf-8"),
                        stderr=b"",
                    )
                if command[:2] == ["docker", "exec"] and "/usr/bin/pg_dump" in command:
                    self.assertNotIn("maintenance-exit", events)
                    events.append("backup")
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout=dump_bytes,
                        stderr=b"",
                    )
                if command[:2] == ["docker", "exec"] and "DROP DATABASE" in command_text:
                    self.assertNotIn("maintenance-exit", events)
                    events.append("drop")
                    return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")
                if command[:2] == ["docker", "exec"] and "-tAc" in command:
                    events.append("exists")
                    return subprocess.CompletedProcess(command, 0, stdout=b"1\n", stderr=b"")
                raise AssertionError(command)

            with (
                patch(
                    "repomap_kg.cli.maintenance_window_for_database_drop",
                    side_effect=maintenance_window,
                ),
                patch(
                    "repomap_kg.runtime.backup.verify_drop_backup",
                    side_effect=verify_under_maintenance,
                ),
                patch(
                    "repomap_kg.runtime.backup.subprocess.run",
                    side_effect=fake_runner,
                ),
            ):
                drop_exit, drop_stdout, drop_stderr = self.run_repo_map_in_process(
                    "local",
                    "db",
                    "drop",
                    "--repo-map-home",
                    str(home),
                    "--database",
                    synthetic_db,
                    "--backup-first",
                    "--yes",
                    "--reason",
                    "live harden synthetic chain",
                    "--json",
                )
                self.assertEqual(drop_exit, 0, drop_stderr)
                drop_payload = json.loads(drop_stdout)
                backup_id = drop_payload["backup_id"]
                backup_dir = next((home / "backups").rglob("manifest.json")).parent
                inspect_exit, inspect_stdout, inspect_stderr = self.run_repo_map_in_process(
                    "local",
                    "db",
                    "backup-inspect",
                    "--repo-map-home",
                    str(home),
                    backup_id,
                    "--json",
                )
                inspect_table_exit, inspect_table_stdout, inspect_table_stderr = (
                    self.run_repo_map_in_process(
                        "local",
                        "db",
                        "backup-inspect",
                        "--repo-map-home",
                        str(home),
                        backup_id,
                    )
                )

            info_exit, info_stdout, info_stderr = self.run_module_entrypoint(
                "local",
                "db",
                "backup-info",
                "--repo-map-home",
                str(home),
                backup_id,
                "--json",
            )

        self.assertEqual(drop_payload["command"], "drop")
        self.assertEqual(drop_payload["result"], "success")
        self.assertTrue(drop_payload["backup_first"])
        self.assertEqual(drop_payload["backup_kind"], "pre-drop")
        self.assertTrue(drop_payload["backup_id"])
        self.assertTrue(drop_payload["checksum_verified"])
        self.assertTrue(drop_payload["restore_supported"])
        self.assertIn("init --database", drop_payload["restore_command_hint"])
        self.assertTrue(drop_payload["destructive_db_actions"])
        self.assertTrue(drop_payload["database_dropped"])
        self.assertLess(events.index("maintenance-enter"), events.index("backup"))
        self.assertLess(events.index("backup"), events.index("verify"))
        self.assertLess(events.index("verify"), events.index("drop"))
        self.assertLess(events.index("drop"), events.index("maintenance-exit"))
        self.assert_lifecycle_public_output_safe(
            drop_stdout,
            home,
            backup_dir,
            backup_dir / "manifest.json",
            backup_dir / "dump.pgcustom",
            backup_dir / "restore.md",
            raw_dump_marker=dump_bytes.decode("utf-8"),
        )

        self.assertEqual(inspect_exit, 0, inspect_stderr)
        inspect_payload = json.loads(inspect_stdout)
        self.assertEqual(inspect_payload["command"], "backup-inspect")
        self.assertEqual(inspect_payload["backup_id"], backup_id)
        self.assertTrue(inspect_payload["manifest_verified"])
        self.assertTrue(inspect_payload["checksum_verified"])
        self.assertTrue(inspect_payload["dump_contents_read"])
        self.assertEqual(inspect_payload["toc_entry_count"], 5)
        self.assertEqual(inspect_payload["table_count"], 3)
        self.assertEqual(inspect_payload["table_data_count"], 2)
        self.assertTrue(inspect_payload["expected_repomap_tables"]["repositories"])
        self.assertTrue(inspect_payload["expected_repomap_tables"]["raw_observations"])
        self.assertTrue(inspect_payload["expected_repomap_tables"]["canonical_nodes"])
        self.assertFalse(inspect_payload["raw_dump_contents_exposed"])
        self.assertFalse(inspect_payload["planned_command_exposed"])
        self.assert_lifecycle_public_output_safe(
            inspect_stdout,
            home,
            backup_dir,
            backup_dir / "manifest.json",
            backup_dir / "dump.pgcustom",
            backup_dir / "restore.md",
            raw_dump_marker=dump_bytes.decode("utf-8"),
        )
        self.assertNotIn("TABLE public repositories", inspect_stdout)

        self.assertEqual(inspect_table_exit, 0, inspect_table_stderr)
        self.assertIn("RepoMap local DB backup inspect", inspect_table_stdout)
        self.assertIn("dump_contents_read=true", inspect_table_stdout)
        self.assert_lifecycle_public_output_safe(
            inspect_table_stdout,
            home,
            backup_dir,
            backup_dir / "manifest.json",
            backup_dir / "dump.pgcustom",
            backup_dir / "restore.md",
            raw_dump_marker=dump_bytes.decode("utf-8"),
        )
        self.assertNotIn("TABLE public repositories", inspect_table_stdout)

        self.assertEqual(info_exit, 0, info_stderr)
        info_payload = json.loads(info_stdout)
        self.assertEqual(info_payload["command"], "backup-info")
        self.assertEqual(info_payload["manifest"]["backup_id"], backup_id)
        self.assertFalse(info_payload["dump_contents_read"])
        self.assertNotIn("toc_entry_count", info_payload)
        self.assertNotIn("expected_repomap_tables", info_payload)
        self.assert_lifecycle_public_output_safe(
            info_stdout,
            home,
            backup_dir,
            backup_dir / "manifest.json",
            backup_dir / "dump.pgcustom",
            backup_dir / "restore.md",
            raw_dump_marker=dump_bytes.decode("utf-8"),
        )
