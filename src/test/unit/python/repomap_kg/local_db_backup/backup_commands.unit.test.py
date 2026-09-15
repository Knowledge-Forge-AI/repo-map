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
