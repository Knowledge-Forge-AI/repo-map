import json
import subprocess
import tempfile
from pathlib import Path

from repomap_test_support.local_db_backup import LocalDbBackupUnitTestCase

from repomap_kg.runtime.backup import (
    LocalDbBackupError,
    dump_database,
    format_backup_info_table,
    format_backup_listing_table,
    format_backup_result_table,
    list_backups,
    read_backup_info,
)
from repomap_kg.runtime.local import setup_local_runtime


class LocalDbBackupDumpListingBoundariesUnitTests(LocalDbBackupUnitTestCase):
    def test_inspect_parse_error_and_unavailable_container_are_bounded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)

            def unavailable_runner(command, **kwargs):
                return subprocess.CompletedProcess(command, 1, stdout="", stderr="not found")

            with self.assertRaises(LocalDbBackupError) as unavailable:
                dump_database(
                    home,
                    database="repomap",
                    timestamp="20260702T010203Z",
                    command_runner=unavailable_runner,
                )
            self.assertEqual(
                unavailable.exception.diagnostics[0].code,
                "runtime-container-unavailable",
            )

            def malformed_runner(command, **kwargs):
                return subprocess.CompletedProcess(command, 0, stdout="{not-json", stderr="")

            with self.assertRaises(LocalDbBackupError) as malformed:
                dump_database(
                    home,
                    database="repomap",
                    timestamp="20260702T010204Z",
                    command_runner=malformed_runner,
                )
            self.assertEqual(
                malformed.exception.diagnostics[0].code,
                "runtime-container-inspect-error",
            )

    def test_listing_reports_malformed_manifests_and_tables_stay_bounded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            bad_dir = home / "backups" / "runtime123" / "repomap" / "bad"
            bad_dir.mkdir(parents=True)
            (bad_dir / "manifest.json").write_text("{not-json", encoding="utf-8")

            listing = list_backups(home)

            payload = listing.to_jsonable()
            self.assertEqual(payload["backup_count"], 0)
            self.assertEqual(payload["diagnostics"][0]["code"], "backup-manifest-unreadable")
            listing_table = format_backup_listing_table(listing)
            self.assertIn("backup-manifest-unreadable", listing_table)

            dry_run = dump_database(
                home,
                database="repomap",
                dry_run=True,
                timestamp="20260702T010203Z",
            )
            self.assertIn("direct_db_required=false", format_backup_result_table(dry_run))

    def test_backup_info_by_manifest_path_and_table_output(self):
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
                "dump_files": [],
                "restore_supported": False,
            }
            (backup_dir / "manifest.json").write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )

            info = read_backup_info(home, backup_dir / "manifest.json")
            table = format_backup_info_table(info)

            self.assertIn("RepoMap local DB backup info", table)
            self.assertIn("restore_supported=false", table)
