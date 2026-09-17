"""Unit tests for bounded shard forensics, streaming digests, and snapshot precedence."""

from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
from typing import Any
import unittest
from unittest import mock

from runner_coverage_diagnostics import (
    ShardDiagnosticSnapshot,
    classify_measured_files,
    compute_bounded_file_digest,
    compute_streaming_sha256,
    merge_diagnostic_snapshot,
)
from runner_coverage_forensics import read_anomalous_shard_forensics


class TestRunnerCoverageForensics(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.checkout_root = self.root / "checkout"
        self.source_root = self.checkout_root / "src" / "main"
        self.source_root.mkdir(parents=True)
        (self.source_root / "app.py").write_text("code = 1\n", encoding="utf-8")
        (self.checkout_root / "README.md").write_text("docs\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_forensic_classification_boundaries_and_sanitization(self) -> None:
        """Matrix Item 14: Classify inside source, inside checkout, outside checkout (masked)."""
        ext_file = self.root / "external_secret_path" / "leak.py"
        ext_file.parent.mkdir(parents=True)
        ext_file.write_text("secret = 2\n", encoding="utf-8")

        paths = [
            str(self.source_root / "app.py"),
            str(self.checkout_root / "README.md"),
            str(ext_file),
        ]
        res = classify_measured_files(
            paths,
            source_root=self.source_root,
            checkout_root=self.checkout_root,
            max_paths=10,
        )
        counts = res["classification"]
        self.assertEqual(counts["inside_selected_source"], 1)
        self.assertEqual(counts["inside_checkout_outside_selected_source"], 1)
        self.assertEqual(counts["outside_checkout"], 1)
        self.assertEqual(counts["unreadable_or_invalid"], 0)

        # Ensure raw external paths are not exposed
        for sample in res["retained_samples"]:
            if sample["category"] == "outside_checkout":
                self.assertNotIn(str(ext_file), sample["safe_label"])
                self.assertTrue(sample["safe_label"].startswith("<external:"))

    def test_unreadable_invalid_forensic_bucket(self) -> None:
        """Matrix Item 15: Unreadable and invalid paths categorized into unreadable_or_invalid."""
        paths = [
            "",
            "bad\x00path\x00char",
            "/invalid/\ud800/surrogate",
        ]
        res = classify_measured_files(
            paths,
            source_root=self.source_root,
            checkout_root=self.checkout_root,
            max_paths=10,
        )
        counts = res["classification"]
        self.assertEqual(counts["unreadable_or_invalid"], 3)
        self.assertEqual(counts["inside_selected_source"], 0)

    def test_truncation_metadata_and_retained_digests(self) -> None:
        """Matrix Item 16: Explicit truncation metadata and bounded sample digests."""
        paths = [str(self.source_root / f"file_{i}.py") for i in range(20)]
        res = classify_measured_files(
            paths,
            source_root=self.source_root,
            checkout_root=self.checkout_root,
            max_paths=5,
        )
        self.assertEqual(res["observed_total"], 20)
        self.assertEqual(res["retained_count"], 5)
        self.assertTrue(res["truncated"])
        self.assertEqual(len(res["retained_samples"]), 5)
        for sample in res["retained_samples"]:
            self.assertIn("category", sample)
            self.assertIn("digest", sample)
            self.assertIn("safe_label", sample)

    def test_oversized_shard_streaming_hash_reports_distinct_algorithm(self) -> None:
        """Matrix Item 17: Oversized shard reports algorithm + bound + truncation, never sha256."""
        shard_path = self.root / "oversized.shard"
        # 100KB file with 32KB bound
        bound = 32768
        shard_path.write_bytes(b"X" * (100 * 1024))

        digest, size, header, truncated, alg = compute_bounded_file_digest(
            shard_path, max_bytes=bound
        )
        self.assertTrue(truncated)
        self.assertEqual(size, 100 * 1024)
        self.assertEqual(alg, f"sha256_prefix_{bound}")

        # Streaming helper returns None for sha256 when truncated
        sha_field, size_field, _ = compute_streaming_sha256(
            shard_path, max_bytes=bound
        )
        self.assertIsNone(sha_field)
        self.assertEqual(size_field, 100 * 1024)

    def test_bounded_sqlite_enumeration(self) -> None:
        """Matrix Item 18: SQLite file inspection handles large file counts boundedly via production helper."""
        shard_path = self.root / ".coverage.bounded_500"
        self._create_sample_shard(shard_path, file_count=500)
        valid, count, info, verdict = read_anomalous_shard_forensics(
            shard_path, self.root, max_paths=100,
        )
        self.assertTrue(valid)
        self.assertEqual(count, 500)
        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(info["observed_total"], 500)
        self.assertEqual(info["retained_count"], 100)
        self.assertTrue(info["truncated"])
        self.assertIsNone(verdict)

    def test_zero_value_snapshot_precedence_and_idempotence(self) -> None:
        """Matrix Item 19: Zero measured files, PID 0, False booleans preserved deterministically."""
        base_snap = ShardDiagnosticSnapshot(
            session_id="s1",
            shard_name=".coverage.0",
            file_type="test",
            size_bytes=100,
            sha256="abc",
            reader_status="ok",
            stage="pre_combine",
            measured_files_count=999,
            ppid=123,
            has_config=True,
        )
        child_info = {
            "measured_files_count": 0,
            "ppid": 0,
            "has_config": False,
            "has_manifest": False,
            "has_token": False,
            "failure_class": "clean_no_hits",
            "failure_reason": "explicit_zero_hits",
        }
        merged = merge_diagnostic_snapshot(base_snap, child_info=child_info)
        # Legitimate 0 and False must not be discarded due to truthiness
        self.assertEqual(merged.measured_files_count, 0)
        self.assertEqual(merged.ppid, 0)
        self.assertFalse(merged.has_config)
        self.assertFalse(merged.has_manifest)
        self.assertFalse(merged.has_token)
        self.assertEqual(merged.failure_class, "clean_no_hits")
        self.assertEqual(merged.failure_reason, "explicit_zero_hits")

        # Second merge must be idempotent and not erase fields
        second_merge = merge_diagnostic_snapshot(merged, sqlite_valid=True)
        self.assertEqual(second_merge.measured_files_count, 0)
        self.assertEqual(second_merge.ppid, 0)
        self.assertEqual(second_merge.failure_class, "clean_no_hits")
        self.assertEqual(second_merge.failure_reason, "explicit_zero_hits")

    def _create_sample_shard(
        self, path: Path, *, schema_version: int = 7, file_count: int = 1
    ) -> None:
        conn = sqlite3.connect(path)
        try:
            conn.execute("CREATE TABLE coverage_schema (version INTEGER)")
            conn.execute("INSERT INTO coverage_schema VALUES (?)", (schema_version,))
            conn.execute("CREATE TABLE file (id INTEGER PRIMARY KEY, path TEXT)")
            for i in range(file_count):
                conn.execute(
                    "INSERT INTO file VALUES (?, ?)",
                    (i, str(self.source_root / f"app_{i}.py")),
                )
            conn.commit()
        finally:
            conn.close()

    def test_read_anomalous_shard_forensics_closes_sqlite_connection(self) -> None:
        shard_path = self.root / ".coverage.test_close"
        self._create_sample_shard(shard_path)

        real_connect = sqlite3.connect
        closed_flags: list[bool] = []

        class ConnProxy:
            def __init__(self, target: sqlite3.Connection) -> None:
                self._target = target

            def close(self) -> None:
                closed_flags.append(True)
                self._target.close()

            def __getattr__(self, name: str) -> Any:
                return getattr(self._target, name)

        def spy_connect(*args: Any, **kwargs: Any) -> Any:
            return ConnProxy(real_connect(*args, **kwargs))

        with mock.patch("sqlite3.connect", side_effect=spy_connect):
            valid, count, _, verdict = read_anomalous_shard_forensics(
                shard_path, self.root
            )
            self.assertTrue(valid)
            self.assertEqual(count, 1)
            self.assertIsNone(verdict)
            self.assertTrue(len(closed_flags) >= 1)

    def test_read_anomalous_shard_forensics_never_calls_coverage_data_measured_files(
        self,
    ) -> None:
        shard_path = self.root / ".coverage.test_no_meas"
        self._create_sample_shard(shard_path, file_count=3)

        import coverage

        with mock.patch.object(
            coverage.CoverageData,
            "measured_files",
            side_effect=AssertionError(
                "CoverageData.measured_files must never be called!"
            ),
        ):
            valid, count, info, verdict = read_anomalous_shard_forensics(
                shard_path,
                self.root,
                source_root=self.source_root,
                checkout_root=self.checkout_root,
            )
            self.assertTrue(valid)
            self.assertEqual(count, 3)
            self.assertIsNone(verdict)
            self.assertIsNotNone(info)

    def test_read_anomalous_shard_forensics_count_star_overrides_observed_total(
        self,
    ) -> None:
        shard_path = self.root / ".coverage.test_trunc"
        self._create_sample_shard(shard_path, file_count=20)

        valid, count, info, verdict = read_anomalous_shard_forensics(
            shard_path,
            self.root,
            source_root=self.source_root,
            checkout_root=self.checkout_root,
            max_paths=5,
        )
        self.assertTrue(valid)
        self.assertEqual(count, 20)
        self.assertIsNone(verdict)
        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(info["observed_total"], 20)
        self.assertEqual(info["retained_count"], 5)
        self.assertTrue(info["truncated"])

    def test_read_anomalous_shard_forensics_schema_mismatch_fails_closed(self) -> None:
        shard_path = self.root / ".coverage.test_bad_schema"
        self._create_sample_shard(shard_path, schema_version=6)

        valid, count, info, verdict = read_anomalous_shard_forensics(
            shard_path, self.root
        )
        self.assertFalse(valid)
        self.assertIsNone(count)
        self.assertIsNone(info)
        self.assertIsNotNone(verdict)
        self.assertIn("unsupported_coverage_schema", verdict or "")

    def test_read_anomalous_shard_forensics_missing_tables_fails_closed(self) -> None:
        shard_path1 = self.root / ".coverage.test_no_schema_tbl"
        conn = sqlite3.connect(shard_path1)
        conn.execute("CREATE TABLE other (id INT)")
        conn.close()

        valid, count, info, verdict = read_anomalous_shard_forensics(
            shard_path1, self.root
        )
        self.assertFalse(valid)
        self.assertEqual(verdict, "missing_coverage_schema_table")

        shard_path2 = self.root / ".coverage.test_no_file_tbl"
        conn2 = sqlite3.connect(shard_path2)
        conn2.execute("CREATE TABLE coverage_schema (version INTEGER)")
        conn2.execute("INSERT INTO coverage_schema VALUES (7)")
        conn2.commit()
        conn2.close()

        valid2, count2, info2, verdict2 = read_anomalous_shard_forensics(
            shard_path2, self.root
        )
        self.assertFalse(valid2)
        self.assertEqual(verdict2, "missing_file_table")

    def test_read_anomalous_shard_forensics_path_containment_fails_closed(self) -> None:
        foreign = self.temp_dir.name + "_foreign"
        foreign_path = Path(foreign) / ".coverage.foreign"
        foreign_path.parent.mkdir(parents=True, exist_ok=True)
        self._create_sample_shard(foreign_path)

        valid, count, info, verdict = read_anomalous_shard_forensics(
            foreign_path, self.root
        )
        self.assertFalse(valid)
        self.assertEqual(verdict, "unauthorized_shard_location")

    def test_schema_introspection_failure_fails_closed(self) -> None:
        shard_path = self.root / ".coverage.test_schema_fail"
        self._create_sample_shard(shard_path)
        with mock.patch(
            "runner_coverage_forensics._get_expected_schema_version",
            return_value=None,
        ):
            valid, count, info, verdict = read_anomalous_shard_forensics(
                shard_path, self.root
            )
            self.assertFalse(valid)
            self.assertIsNone(count)
            self.assertEqual(verdict, "coverage_schema_introspection_failed")

    def test_close_sqlite_error_does_not_mask_verdict(self) -> None:
        shard_path = self.root / ".coverage.test_close_err"
        self._create_sample_shard(shard_path)

        real_connect = sqlite3.connect

        class ConnProxy:
            def __init__(self, target: sqlite3.Connection) -> None:
                self._target = target

            def close(self) -> None:
                self._target.close()
                raise sqlite3.OperationalError("simulated close error")

            def __getattr__(self, name: str) -> Any:
                return getattr(self._target, name)

        with mock.patch("sqlite3.connect", side_effect=lambda *a, **kw: ConnProxy(real_connect(*a, **kw))):
            valid, count, info, verdict = read_anomalous_shard_forensics(
                shard_path, self.root
            )
            self.assertTrue(valid)
            self.assertEqual(count, 1)
            self.assertIsNone(verdict)


if __name__ == "__main__":
    unittest.main()
