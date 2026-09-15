from __future__ import annotations

import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from repomap_kg.storage.row_spool import RowSpool


class RowSpoolUnitTests(unittest.TestCase):
    def test_replays_rows_and_cleans_up_private_file(self):
        rows = (
            {"stage_id": "stage-1", "family_ordinal": 0, "value": 1},
            {"stage_id": "stage-1", "family_ordinal": 1, "value": True},
        )

        with RowSpool.from_rows(rows) as spool:
            path = spool.path
            self.assertEqual(len(spool), len(rows))
            self.assertEqual(tuple(spool), rows)
            self.assertEqual(tuple(spool), rows)
            self.assertEqual(spool.byte_count, path.stat().st_size)
            self.assertEqual(
                stat.S_IMODE(path.stat().st_mode),
                stat.S_IRUSR | stat.S_IWUSR,
            )

        self.assertFalse(path.exists())

    def test_closed_spool_rejects_replay(self):
        spool = RowSpool.from_rows(({"value": "test"},))
        spool.close()

        with self.assertRaisesRegex(RuntimeError, "spool is closed"):
            tuple(spool)

    def test_rejects_non_mapping_rows_without_leaking_file(self):
        with self.assertRaisesRegex(ValueError, "staged row is invalid"):
            RowSpool.from_rows(({"value": "ok"}, "invalid"))  # type: ignore[arg-type]

    def test_artifact_growth_is_observed_before_spool_bytes_are_written(self):
        samples = []
        spool_path = None

        with tempfile.TemporaryDirectory() as directory:
            original_mkstemp = tempfile.mkstemp

            def private_mkstemp(*, prefix, suffix):
                nonlocal spool_path
                descriptor, raw_path = original_mkstemp(
                    prefix=prefix,
                    suffix=suffix,
                    dir=directory,
                )
                spool_path = Path(raw_path)
                return descriptor, raw_path

            def reject_growth(projected_bytes):
                samples.append(projected_bytes)
                assert spool_path is not None
                self.assertEqual(spool_path.stat().st_size, 0)
                raise MemoryError("artifact ceiling")

            with patch(
                "repomap_kg.storage.row_spool.tempfile.mkstemp",
                private_mkstemp,
            ):
                with self.assertRaisesRegex(MemoryError, "artifact ceiling"):
                    RowSpool.from_rows(
                        ({"value": "private"},),
                        artifact_observer=reject_growth,
                    )

            self.assertTrue(samples)
            assert spool_path is not None
            self.assertFalse(spool_path.exists())
