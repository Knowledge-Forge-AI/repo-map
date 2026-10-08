"""Unit tests for evidence-safe conftest scratch cleanup and ownership guards.

Verifies:
1. Success cleanup: reclaimed test-owned scratch directories for passing settled tests.
2. Failed-test retention: preserved evidence when tests fail, error, or do not settle.
3. Cleanup failure: attributable failure reporting and evidence logging when deletion fails.
4. Ownership guard: refusing deletion of arbitrary user, root, or non-test paths.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from repomap_test_support.test_scratch import TestScratchLayout
from repomap_test_support.test_scratch_cleanup import (
    OwnershipGuardError,
    ScratchOwnershipError,
    TestScratchCleanupError,
    clean_test_node_scratch,
    is_test_settled_and_passed,
    record_cleanup_failure_evidence,
    record_test_report,
    validate_scratch_path_ownership,
)


@pytest.fixture
def test_layout(tmp_path: Path) -> TestScratchLayout:
    """An isolated, fully initialized TestScratchLayout under tmp_path."""
    scratch_root = tmp_path / "scratch"
    run_root = scratch_root / "r" / "tunitcleanup0"
    layout = TestScratchLayout(
        run_root=run_root,
        scratch_root=scratch_root,
        allocated=True,
        project="repo-map_dev",
        phase="test-cleanup-unit",
    ).create()
    layout.apply()
    return layout


def _make_report(when: str, outcome: str = "passed") -> SimpleNamespace:
    return SimpleNamespace(
        when=when, outcome=outcome,
        passed=(outcome == "passed"),
        failed=(outcome == "failed"),
        skipped=(outcome == "skipped"),
    )


def _make_node(
    funcargs: dict | None = None,
    setup: str = "passed",
    call: str | None = "passed",
    teardown: str | None = "passed",
) -> SimpleNamespace:
    node = SimpleNamespace(funcargs=funcargs or {})
    for when, outcome in (("setup", setup), ("call", call), ("teardown", teardown)):
        if outcome is not None:
            record_test_report(node, _make_report(when, outcome))
    return node


# --- 1. Direct units: success cleanup ---
def test_success_cleanup_reclaims_tmp_path(test_layout: TestScratchLayout) -> None:
    test_dir = test_layout.pytest_basetemp / "test_success_tmp_path0"
    test_dir.mkdir(parents=True)
    (test_dir / "sample_output.txt").write_text("temporary data")
    subdir = test_dir / "sub"
    subdir.mkdir()
    (subdir / "nested.bin").write_bytes(b"nested")

    node = _make_node(funcargs={"tmp_path": test_dir}, setup="passed", call="passed")
    cleaned = clean_test_node_scratch(node, layout=test_layout)

    assert not test_dir.exists()
    assert test_dir in cleaned


def test_success_cleanup_reclaims_tmpdir(test_layout: TestScratchLayout) -> None:
    test_dir = test_layout.tmp / "pytest-operator" / "test_success_tmpdir0"
    test_dir.mkdir(parents=True)
    (test_dir / "file.txt").write_text("data")

    node = _make_node(funcargs={"tmpdir": str(test_dir)}, setup="passed", call="passed")
    cleaned = clean_test_node_scratch(node, layout=test_layout)

    assert not test_dir.exists()
    assert Path(test_dir) in cleaned


def test_success_cleanup_deduplicates_same_path_in_tmp_path_and_tmpdir(
    test_layout: TestScratchLayout,
) -> None:
    test_dir = test_layout.pytest_basetemp / "test_both0"
    test_dir.mkdir(parents=True)
    (test_dir / "marker.txt").write_text("marker")

    node = _make_node(
        funcargs={"tmp_path": test_dir, "tmpdir": str(test_dir)},
        setup="passed",
        call="passed",
    )
    cleaned = clean_test_node_scratch(node, layout=test_layout)

    assert not test_dir.exists()
    assert len(cleaned) == 1
    assert cleaned[0] == test_dir


def test_success_cleanup_noop_when_no_tmp_fixtures(
    test_layout: TestScratchLayout,
) -> None:
    node = _make_node(funcargs={"pure_arg": 42}, setup="passed", call="passed")
    cleaned = clean_test_node_scratch(node, layout=test_layout)
    assert cleaned == []


def test_success_cleanup_noop_when_scratch_path_already_deleted(
    test_layout: TestScratchLayout,
) -> None:
    test_dir = test_layout.pytest_basetemp / "test_already_gone0"
    assert not test_dir.exists()

    node = _make_node(funcargs={"tmp_path": test_dir}, setup="passed", call="passed")
    cleaned = clean_test_node_scratch(node, layout=test_layout)
    assert cleaned == []


def test_success_cleanup_reanchors_layout_environment(
    test_layout: TestScratchLayout,
) -> None:
    test_dir = test_layout.pytest_basetemp / "test_reanchor0"
    test_dir.mkdir(parents=True)

    os.environ["TMPDIR"] = "/tmp/polluted_by_test"
    node = _make_node(funcargs={"tmp_path": test_dir}, setup="passed", call="passed")
    clean_test_node_scratch(node, layout=test_layout)

    assert os.environ["TMPDIR"] == str(test_layout.tmp)


# --- 2. Direct units: failed-test retention ---
def test_failed_call_retains_scratch(test_layout: TestScratchLayout) -> None:
    test_dir = test_layout.pytest_basetemp / "test_failed_call0"
    test_dir.mkdir(parents=True)
    evidence_file = test_dir / "failure_state.json"
    evidence_file.write_text('{"failure": "exact failure evidence"}')

    node = _make_node(funcargs={"tmp_path": test_dir}, setup="passed", call="failed")
    cleaned = clean_test_node_scratch(node, layout=test_layout)

    assert cleaned == []
    assert test_dir.exists()
    assert evidence_file.exists()
    assert evidence_file.read_text() == '{"failure": "exact failure evidence"}'


def test_failed_setup_retains_scratch(test_layout: TestScratchLayout) -> None:
    test_dir = test_layout.pytest_basetemp / "test_failed_setup0"
    test_dir.mkdir(parents=True)
    (test_dir / "setup_evidence.log").write_text("setup partial state")

    node = _make_node(funcargs={"tmp_path": test_dir}, setup="failed", call=None)
    cleaned = clean_test_node_scratch(node, layout=test_layout)

    assert cleaned == []
    assert test_dir.exists()
    assert (test_dir / "setup_evidence.log").exists()


def test_skipped_setup_retains_scratch(test_layout: TestScratchLayout) -> None:
    test_dir = test_layout.pytest_basetemp / "test_skipped_setup0"
    test_dir.mkdir(parents=True)

    node = _make_node(funcargs={"tmp_path": test_dir}, setup="skipped", call=None)
    cleaned = clean_test_node_scratch(node, layout=test_layout)

    assert cleaned == []
    assert test_dir.exists()


def test_skipped_call_retains_scratch(test_layout: TestScratchLayout) -> None:
    test_dir = test_layout.pytest_basetemp / "test_skipped_call0"
    test_dir.mkdir(parents=True)

    node = _make_node(funcargs={"tmp_path": test_dir}, setup="passed", call="skipped")
    cleaned = clean_test_node_scratch(node, layout=test_layout)

    assert cleaned == []
    assert test_dir.exists()


def test_failed_teardown_retains_scratch(test_layout: TestScratchLayout) -> None:
    test_dir = test_layout.pytest_basetemp / "test_failed_teardown0"
    test_dir.mkdir(parents=True)

    node = _make_node(
        funcargs={"tmp_path": test_dir},
        setup="passed",
        call="passed",
        teardown="failed",
    )
    cleaned = clean_test_node_scratch(node, layout=test_layout)

    assert cleaned == []
    assert test_dir.exists()


def test_unsettled_node_without_reports_retains_scratch(
    test_layout: TestScratchLayout,
) -> None:
    test_dir = test_layout.pytest_basetemp / "test_unsettled0"
    test_dir.mkdir(parents=True)

    node = SimpleNamespace(funcargs={"tmp_path": test_dir})
    cleaned = clean_test_node_scratch(node, layout=test_layout)

    assert cleaned == []
    assert test_dir.exists()
    assert not is_test_settled_and_passed(node)


def test_none_node_retains_scratch(test_layout: TestScratchLayout) -> None:
    assert not is_test_settled_and_passed(None)
    cleaned = clean_test_node_scratch(None, layout=test_layout)
    assert cleaned == []


# --- 3. Direct units: cleanup failure ---
def test_cleanup_failure_raises_attributable_error_on_oserror(
    test_layout: TestScratchLayout,
) -> None:
    test_dir = test_layout.pytest_basetemp / "test_fail_oserror0"
    test_dir.mkdir(parents=True)
    node = _make_node(funcargs={"tmp_path": test_dir}, setup="passed", call="passed")

    with patch("shutil.rmtree", side_effect=OSError("Permission denied (EACCES)")):
        with pytest.raises(TestScratchCleanupError) as excinfo:
            clean_test_node_scratch(node, layout=test_layout)

    assert "hygiene cleanup failed" in str(excinfo.value)
    assert str(test_dir) in str(excinfo.value)
    assert "Permission denied" in str(excinfo.value)


def test_cleanup_failure_records_evidence_to_logs_channel(
    test_layout: TestScratchLayout,
) -> None:
    test_dir = test_layout.pytest_basetemp / "test_fail_evidence0"
    test_dir.mkdir(parents=True)
    node = _make_node(funcargs={"tmp_path": test_dir}, setup="passed", call="passed")

    with patch("shutil.rmtree", side_effect=OSError("I/O failure on unlink")):
        with pytest.raises(TestScratchCleanupError):
            clean_test_node_scratch(node, layout=test_layout)

    evidence_file = test_layout.logs / "test_scratch_cleanup_failures.jsonl"
    assert evidence_file.exists()

    lines = [json.loads(line) for line in evidence_file.read_text().splitlines() if line]
    assert len(lines) == 1
    record = lines[0]
    assert record["schema"] == "repomap-test-scratch-cleanup-failure-v1"
    assert record["path"] == str(test_dir)
    assert "I/O failure" in record["error"]
    assert record["error_type"] == "TestScratchCleanupError"
    assert "timestamp_seconds" in record


def test_cleanup_failure_reanchors_layout_even_on_exception(
    test_layout: TestScratchLayout,
) -> None:
    test_dir = test_layout.pytest_basetemp / "test_fail_reanchor0"
    test_dir.mkdir(parents=True)
    node = _make_node(funcargs={"tmp_path": test_dir}, setup="passed", call="passed")

    os.environ["TMPDIR"] = "/tmp/polluted_before_failure"
    with patch("shutil.rmtree", side_effect=OSError("Disk failure")):
        with pytest.raises(TestScratchCleanupError):
            clean_test_node_scratch(node, layout=test_layout)

    assert os.environ["TMPDIR"] == str(test_layout.tmp)


def test_cleanup_failure_when_path_is_not_a_directory(
    test_layout: TestScratchLayout,
) -> None:
    file_path = test_layout.pytest_basetemp / "regular_file.txt"
    file_path.write_text("not a directory")
    node = _make_node(funcargs={"tmp_path": file_path}, setup="passed", call="passed")

    with pytest.raises(TestScratchCleanupError) as excinfo:
        clean_test_node_scratch(node, layout=test_layout)

    assert "not a directory" in str(excinfo.value)
    assert file_path.exists()


# --- 4. Direct units: ownership guard ---
def test_ownership_guard_rejects_external_user_directory(
    test_layout: TestScratchLayout,
    tmp_path: Path,
) -> None:
    external_dir = tmp_path / "outside_run_root"
    external_dir.mkdir()

    with pytest.raises(ScratchOwnershipError) as excinfo:
        validate_scratch_path_ownership(external_dir, test_layout)

    assert "outside test run root" in str(excinfo.value)


def test_ownership_guard_rejects_root_directory(
    test_layout: TestScratchLayout,
) -> None:
    with pytest.raises(ScratchOwnershipError):
        validate_scratch_path_ownership(Path("/"), test_layout)


def test_ownership_guard_rejects_run_root_itself(
    test_layout: TestScratchLayout,
) -> None:
    with pytest.raises(ScratchOwnershipError) as excinfo:
        validate_scratch_path_ownership(test_layout.run_root, test_layout)

    assert "run root itself" in str(excinfo.value)


def test_ownership_guard_rejects_top_level_directories(
    test_layout: TestScratchLayout,
) -> None:
    for directory in test_layout.directories():
        with pytest.raises(ScratchOwnershipError) as excinfo:
            validate_scratch_path_ownership(directory, test_layout)
        assert "top-level run directory" in str(excinfo.value)


def test_ownership_guard_rejects_symlink(
    test_layout: TestScratchLayout,
) -> None:
    target = test_layout.pytest_basetemp / "real_dir"
    target.mkdir()
    link = test_layout.pytest_basetemp / "symlink_dir"
    link.symlink_to(target)

    with pytest.raises(ScratchOwnershipError) as excinfo:
        validate_scratch_path_ownership(link, test_layout)

    assert "symlink" in str(excinfo.value)


@pytest.mark.parametrize("empty_val", [None, "", "   \t\n"])
def test_ownership_guard_rejects_none_and_empty_paths(
    test_layout: TestScratchLayout, empty_val: str | None
) -> None:
    with pytest.raises(ScratchOwnershipError):
        validate_scratch_path_ownership(empty_val, test_layout)


def test_ownership_guard_in_clean_test_node_scratch_refuses_deletion_of_external_path(
    test_layout: TestScratchLayout,
    tmp_path: Path,
) -> None:
    external_dir = tmp_path / "protected_user_code"
    external_dir.mkdir()
    source_file = external_dir / "important_source.py"
    source_file.write_text("def keep_me(): pass\n")

    node = _make_node(
        funcargs={"tmp_path": external_dir},
        setup="passed",
        call="passed",
    )

    with pytest.raises(OwnershipGuardError):
        clean_test_node_scratch(node, layout=test_layout)

    assert external_dir.exists()
    assert source_file.exists()
    assert source_file.read_text() == "def keep_me(): pass\n"


def test_record_cleanup_failure_evidence_noop_when_layout_is_none() -> None:
    record_cleanup_failure_evidence(Path("/some/path"), RuntimeError("err"), layout=None)
