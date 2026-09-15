"""TEST-HYGIENE3A-FIX1 append and close-receipt authority regressions."""

from __future__ import annotations

from pathlib import Path

import pytest

from repomap_test_support import resource_receipts
from repomap_test_support.resource_retention import RetentionError


def test_early_close_receipt_cannot_release_report_source(tmp_path: Path):
    append = resource_receipts.AppendRecord(
        tmp_path / "append.json",
        "TEST-HYGIENE3A-FIX1",
        "run1",
        "OPERATIONAL-REPORT-" + "a" * 64,
        "b" * 64,
        100,
        True,
        "d" * 64,
    )
    with pytest.raises(RetentionError, match="ordering"):
        resource_receipts.write_close_receipt(
            tmp_path / "close.json",
            phase="TEST-HYGIENE3A-FIX1",
            run_id="run1",
            commit="c" * 40,
            commit_verified_at_seconds=75,
            append=append,
            closed_at_seconds=50,
        )


def test_caller_assertions_cannot_create_append_authority(tmp_path: Path):
    with pytest.raises(RetentionError, match="packet"):
        resource_receipts.write_append_record(
            tmp_path / "append.json",
            phase="TEST-HYGIENE3A-FIX1",
            run_id="run1",
            report_id="OPERATIONAL-REPORT-" + "a" * 64,
            report_sha256="b" * 64,
            verified_at_seconds=100,
            record_complete=True,
        )
