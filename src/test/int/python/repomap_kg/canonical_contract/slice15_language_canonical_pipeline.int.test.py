"""Retained Slice15 runtime setup and schema-upgrade caller composition."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from repomap_kg.runtime.backup_records import LocalDbBackupError
from repomap_kg.runtime.local import setup_local_runtime
from repomap_kg.runtime.schema_upgrade import upgrade_graph_schema


class Slice15LanguageCanonicalPipelineIntegrationTests(unittest.TestCase):
    """Slice 15 Group S15-A integration tests for language, config, and runtime pipeline."""


    def test_s15_a06_runtime_schema_upgrade_precondition_validation(self) -> None:
        """upgrade_graph_schema enforces --backup-first, confirmation, and dry-run boundaries."""
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            setup_local_runtime(home)

            # 1. Missing backup_first raises LocalDbBackupError
            with self.assertRaises(LocalDbBackupError) as cm_bk:
                upgrade_graph_schema(
                    home, database="repomap", backup_first=False, confirmed=True
                )
            self.assertIn("backup-first", str(cm_bk.exception))

            # 2. Missing confirmed without dry_run raises confirmation error
            with self.assertRaises(LocalDbBackupError) as cm_conf:
                upgrade_graph_schema(
                    home,
                    database="repomap",
                    backup_first=True,
                    confirmed=False,
                    dry_run=False,
                )
            self.assertIn("confirmation", str(cm_conf.exception))

            # 3. Dry run mode returns planned actions without executing
            dry_res = upgrade_graph_schema(
                home,
                database="repomap",
                backup_first=True,
                confirmed=False,
                dry_run=True,
            )
            self.assertEqual(dry_res.result, "dry_run")
            self.assertEqual(dry_res.schema_before, "unknown")
            self.assertEqual(dry_res.schema_after, "planned")
            self.assertIn("inspect-target", dry_res.planned_actions)
            self.assertIn("create-and-inspect-backup", dry_res.planned_actions)
