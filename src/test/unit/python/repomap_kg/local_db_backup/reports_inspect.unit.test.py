import json
import subprocess
import tempfile
from pathlib import Path

from repomap_test_support.local_db_backup import LocalDbBackupUnitTestCase

from repomap_kg.runtime.backup import (
    format_backup_inspect_table,
    drop_database,
    inspect_backup,
    read_backup_info,
)
from repomap_kg.runtime.local import LocalRuntimeIdentity, setup_local_runtime


class LocalDbBackupReportsInspectUnitTests(LocalDbBackupUnitTestCase):
    def test_live_ops5_local_db_drop_json_omits_low_level_commands(self):
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
            rendered = json.dumps(payload, sort_keys=True)
            self.assertNotIn("planned_command", payload)
            self.assertNotIn(str(home), rendered)
            self.assertNotIn("docker", rendered)
            self.assertNotIn("pg_dump", rendered)
            self.assertNotIn("pg_restore", rendered)
            self.assertNotIn("psql", rendered)
            self.assertNotIn("POSTGRES_PASSWORD", rendered)
            self.assertNotIn("PGPASSWORD", rendered)

    def test_live_ops5_lifecycle_json_preserves_backup_safety_fields(self):
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
            self.assertEqual(payload["database"], "repomap")
            self.assertEqual(payload["backup_id"], f"{identity.home_hash}--repomap--20260702T010203Z")
            self.assertEqual(payload["backup_kind"], "pre-drop")
            self.assertTrue(payload["backup_first"])
            self.assertTrue(payload["target_existed"])
            self.assertFalse(payload["backup_path_created"])
            self.assertFalse(payload["dump_executed"])
            self.assertFalse(payload["database_dropped"])
            self.assertFalse(payload["destructive_db_actions"])
            self.assertFalse(payload["direct_db_required"])
            self.assertTrue(payload["restore_supported"])
            self.assertIn("--from-dump", payload["restore_command_hint"])
            self.assertIn(payload["backup_id"], payload["restore_command_hint"])

    def test_live_ops5_backup_info_json_omits_raw_runtime_command_details(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            identity = LocalRuntimeIdentity.from_home(home)
            backup_dir = self.write_backup_fixture(home, identity.home_hash, "repomap")
            manifest_path = backup_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["restore_supported"] = True
            manifest["restore_hint"] = (
                "repomap-kg local db init --database repomap "
                "--from-dump /Users/slair/private/runtime/dump.pgcustom"
            )
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            info = read_backup_info(home, manifest["backup_id"])

            payload = info.to_jsonable()
            rendered = json.dumps(payload, sort_keys=True)
            self.assertEqual(payload["manifest"]["backup_id"], manifest["backup_id"])
            self.assertTrue(payload["manifest"]["restore_supported"])
            self.assertEqual(
                payload["manifest"]["dump_files"][0]["sha256"],
                manifest["dump_files"][0]["sha256"],
            )
            self.assertNotIn("repo_map_home", payload)
            self.assertNotIn("backups_root", payload)
            self.assertNotIn("manifest_path", payload)
            self.assertNotIn("backup_path", payload["manifest"])
            self.assertNotIn(str(home), rendered)
            self.assertNotIn("/Users/slair/private", rendered)
            self.assertNotIn("pg_dump", rendered)
            self.assertNotIn("pg_restore", rendered)
            self.assertNotIn("psql", rendered)
            self.assertNotIn("POSTGRES_PASSWORD", rendered)
            self.assertNotIn("PGPASSWORD", rendered)

    def test_live_ops6_backup_inspect_json_reports_bounded_toc_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            identity = LocalRuntimeIdentity.from_home(home)
            backup_dir = self.write_backup_fixture(home, identity.home_hash, "repomap")
            manifest_path = backup_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["restore_supported"] = True
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            toc = "\n".join(
                [
                    "; synthetic pg_restore toc",
                    "1; 2615 2200 SCHEMA - public repomap",
                    "2; 1259 16390 TABLE public repositories repomap",
                    "3; 1259 16391 TABLE public runs repomap",
                    "4; 1259 16392 TABLE public raw_observations repomap",
                    "5; 1259 16393 TABLE public unsafe/path repomap",
                    "6; 0 16390 TABLE DATA public repositories repomap",
                    "7; 0 16392 TABLE DATA public raw_observations repomap",
                ]
            )
            calls: list[list[str]] = []

            def fake_runner(command, **kwargs):
                calls.append(list(command))
                if command[:2] == ["docker", "inspect"]:
                    return self.owned_container_result(identity, command)
                if command[:2] == ["docker", "exec"] and "/usr/bin/pg_restore" in command:
                    self.assertEqual(kwargs.get("input"), (backup_dir / "dump.pgcustom").read_bytes())
                    return subprocess.CompletedProcess(command, 0, stdout=toc.encode("utf-8"), stderr=b"")
                raise AssertionError(command)

            result = inspect_backup(
                home,
                manifest["backup_id"],
                command_runner=fake_runner,
            )

            payload = result.to_jsonable()
            self.assertEqual(payload["command"], "backup-inspect")
            self.assertEqual(payload["backup_id"], manifest["backup_id"])
            self.assertEqual(payload["database"], "repomap")
            self.assertEqual(payload["backup_kind"], "manual-dump")
            self.assertTrue(payload["manifest_verified"])
            self.assertTrue(payload["checksum_verified"])
            self.assertTrue(payload["restore_supported"])
            self.assertTrue(payload["dump_contents_read"])
            self.assertEqual(payload["dump_format"], "pgcustom")
            self.assertEqual(payload["toc_entry_count"], 7)
            self.assertEqual(payload["table_count"], 3)
            self.assertEqual(payload["table_data_count"], 2)
            self.assertIn("repositories", payload["tables"])
            self.assertIn("raw_observations", payload["table_data_tables"])
            self.assertTrue(payload["expected_repomap_tables"]["repositories"])
            self.assertTrue(payload["expected_repomap_tables"]["raw_observations"])
            self.assertFalse(payload["expected_repomap_tables"]["canonical_nodes"])
            self.assertFalse(payload["destructive_db_actions"])
            self.assertFalse(payload["raw_dump_contents_exposed"])
            self.assertFalse(payload["planned_command_exposed"])
            self.assertTrue(any("/usr/bin/pg_restore" in call for call in calls))

            table = format_backup_inspect_table(result)
            self.assertIn("RepoMap local DB backup inspect", table)
            self.assertIn("dump_contents_read=true", table)
            self.assertIn("toc_entries=7", table)

    def test_live_ops6_backup_inspect_json_omits_paths_and_raw_commands(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            identity = LocalRuntimeIdentity.from_home(home)
            backup_dir = self.write_backup_fixture(home, identity.home_hash, "repomap")
            manifest_path = backup_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["restore_supported"] = True
            manifest["restore_hint"] = (
                "repomap-kg local db init --database repomap "
                "--from-dump /Users/slair/private/runtime/dump.pgcustom"
            )
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            def fake_runner(command, **kwargs):
                if command[:2] == ["docker", "inspect"]:
                    return self.owned_container_result(identity, command)
                if command[:2] == ["docker", "exec"] and "/usr/bin/pg_restore" in command:
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout=b"1; 1259 16390 TABLE public repositories repomap\n",
                        stderr=b"",
                    )
                raise AssertionError(command)

            payload = inspect_backup(
                home,
                manifest["backup_id"],
                command_runner=fake_runner,
            ).to_jsonable()
            rendered = json.dumps(payload, sort_keys=True)

            self.assertNotIn(str(home), rendered)
            self.assertNotIn(str(backup_dir), rendered)
            self.assertNotIn("/Users/slair/private", rendered)
            self.assertNotIn("planned_command", payload)
            self.assertNotIn("pg_restore", rendered)
            self.assertNotIn("pg_dump", rendered)
            self.assertNotIn("psql", rendered)
            self.assertNotIn("POSTGRES_PASSWORD", rendered)
            self.assertNotIn("PGPASSWORD", rendered)
            self.assertNotIn("TABLE public repositories", rendered)

    def test_live_ops6_backup_inspect_unsupported_dump_is_safe(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            identity = LocalRuntimeIdentity.from_home(home)
            backup_dir = self.write_backup_fixture(home, identity.home_hash, "repomap")
            manifest_path = backup_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["dump_format"] = "plain"
            manifest["dump_files"][0]["name"] = "dump.sql"
            (backup_dir / "dump.sql").write_bytes((backup_dir / "dump.pgcustom").read_bytes())
            (backup_dir / "dump.pgcustom").unlink()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            def fake_runner(command, **kwargs):
                if command[:2] == ["docker", "inspect"]:
                    return self.owned_container_result(identity, command)
                raise AssertionError(command)

            payload = inspect_backup(
                home,
                manifest["backup_id"],
                command_runner=fake_runner,
            ).to_jsonable()
            rendered = json.dumps(payload, sort_keys=True)

            self.assertTrue(payload["checksum_verified"])
            self.assertFalse(payload["dump_contents_read"])
            self.assertEqual(payload["diagnostics"][0]["code"], "backup-dump-toc-unsupported")
            self.assertNotIn(str(home), rendered)
            self.assertNotIn("pg_restore", rendered)

    def test_live_ops6_backup_info_remains_manifest_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            identity = LocalRuntimeIdentity.from_home(home)
            backup_dir = self.write_backup_fixture(home, identity.home_hash, "repomap")
            info = read_backup_info(home, backup_dir / "manifest.json")

            payload = info.to_jsonable()
            self.assertEqual(payload["command"], "backup-info")
            self.assertFalse(payload["dump_contents_read"])
            self.assertNotIn("toc_entry_count", payload)
            self.assertNotIn("expected_repomap_tables", payload)
