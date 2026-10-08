import tempfile
import unittest
from pathlib import Path

from repomap_kg.runtime.backup_commands import planned_pg_restore_list_command
from repomap_kg.runtime.local import setup_local_runtime


class LocalDbBackupCommandUnitTests(unittest.TestCase):
    def test_pg_restore_list_reads_archive_from_standard_input(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            plan = setup_local_runtime(home).plan

            command = planned_pg_restore_list_command(plan)

        self.assertEqual(command[-2:], ("/usr/bin/pg_restore", "-l"))

    def test_format_coordinated_restore_table_and_error_handling(self):
        from unittest import mock
        from repomap_kg.runtime.backup_restore_sets import format_coordinated_restore_table

        restore_result = mock.MagicMock()
        restore_result.to_jsonable.return_value = {
            "result": "completed",
            "backup_id": "set-1",
            "restore_order": ["db1", "db2"],
            "checksum_verified": True,
            "control_restored_last": True,
        }
        table = format_coordinated_restore_table(restore_result)
        self.assertIn("backup_id=set-1", table)
