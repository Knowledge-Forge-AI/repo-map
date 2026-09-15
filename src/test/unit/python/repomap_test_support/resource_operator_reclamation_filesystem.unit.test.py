"""TEST-HYGIENE3B3 O7-O8 and O13-O16 filesystem boundaries."""

from __future__ import annotations

import os
import socket
import stat
from pathlib import Path

import pytest

from repomap_test_support.resource_interruption import (
    InterruptionOutcome,
    classify_interruption,
    operator_marker_path,
)
from repomap_test_support.resource_operator_reclamation import (
    CONFIRMATION_LITERAL,
    OperatorReclamationRequest,
    reclaim_run_population,
)
from repomap_test_support.resource_operator_reclamation_test_support import (
    PHASE,
    PROJECT,
    add_run,
    dead,
    live,
    private_root,
)
from repomap_test_support.resource_safe_tree_delete import (
    SafeTreeDeleteError,
    SafeTreeDeleteFailure,
    delete_run_entry,
    inspect_run_entry,
)


def approved(*, force_live: bool = False) -> OperatorReclamationRequest:
    return OperatorReclamationRequest(
        confirmation=CONFIRMATION_LITERAL,
        force_live=force_live,
        override_pins=False,
    )


def test_relative_af_unix_fixture_preflight(tmp_path: Path) -> None:
    root = private_root(tmp_path)
    socket_path = root / "r" / "co-tenant.socket"
    original_cwd = os.getcwd()
    cwd_fd = os.open(".", os.O_RDONLY)
    bound_socket = socket.socket(socket.AF_UNIX)
    try:
        try:
            os.chdir(root / "r")
            bound_socket.bind("co-tenant.socket")
        finally:
            try:
                os.fchdir(cwd_fd)
            finally:
                os.close(cwd_fd)

        assert os.getcwd() == original_cwd
        assert stat.S_ISSOCK(socket_path.lstat().st_mode)
        inspection = inspect_run_entry(root, "co-tenant.socket")
        assert stat.S_ISSOCK(inspection.mode)
    finally:
        bound_socket.close()
        socket_path.unlink(missing_ok=True)

    assert os.getcwd() == original_cwd
    assert tuple((root / "r").iterdir()) == ()


def test_o7_force_writes_durable_marker_before_point_of_no_return(
    tmp_path: Path,
) -> None:
    root = private_root(tmp_path)
    run = add_run(root, "forced-live", state="running", pid=123)
    observed = []

    def checkpoint(stage: str) -> None:
        if stage == "before_point_of_no_return":
            marker = operator_marker_path(
                root, project=PROJECT, run_id=run.name
            )
            observed.append((marker.exists(), marker.stat().st_mode & 0o777))

    result = reclaim_run_population(
        root,
        approved(force_live=True),
        now_seconds=100,
        process_is_live=live,
        checkpoint=checkpoint,
    )

    assert result.outcome == "completed"
    assert observed == [(True, 0o600)]
    assert result.markers_written == 1


def test_o8_exact_marker_classifies_operator_interrupted(tmp_path: Path) -> None:
    root = private_root(tmp_path)
    run = add_run(root, "terminal-marker")

    result = reclaim_run_population(
        root,
        approved(),
        now_seconds=100,
        process_is_live=dead,
    )

    marker = operator_marker_path(root, project=PROJECT, run_id=run.name)
    assert result.outcome == "completed"
    assert classify_interruption(
        marker,
        project=PROJECT,
        phase=PHASE,
        run_id=run.name,
        state_changed=True,
    ) is InterruptionOutcome.OPERATOR_INTERRUPTED


def test_o13_broad_retention_classes_are_inventoried_and_accounted(
    tmp_path: Path,
) -> None:
    root = private_root(tmp_path)
    add_run(root, "valid-terminal")
    add_run(root, "report-pending")
    add_run(root, "ambiguous", exact=False)
    add_run(root, "foreign", project="other-project")
    opaque = root / "r" / "opaque.bin"
    opaque.write_bytes(b"opaque")

    result = reclaim_run_population(
        root,
        approved(),
        now_seconds=100,
        process_is_live=dead,
    )

    assert result.outcome == "completed"
    assert result.entry_count == 5
    assert result.categories == {
        "valid": 2,
        "ambiguous": 1,
        "foreign": 1,
        "opaque": 1,
    }
    assert result.removed_inode_count >= 9
    assert result.removed_allocated_bytes >= 0


def test_o14_symlink_is_unlinked_without_following_external_sentinel(
    tmp_path: Path,
) -> None:
    root = private_root(tmp_path)
    sentinel = tmp_path.parent / f"{tmp_path.name}-external-sentinel"
    sentinel.write_text("preserve", encoding="utf-8")
    link = root / "r" / "outside-link"
    link.symlink_to(sentinel)

    result = reclaim_run_population(
        root,
        approved(),
        now_seconds=100,
        process_is_live=dead,
    )

    assert result.outcome == "completed"
    assert not link.exists() and not link.is_symlink()
    assert sentinel.read_text(encoding="utf-8") == "preserve"


def test_o15_cross_device_identity_refuses_before_deletion(tmp_path: Path) -> None:
    root = private_root(tmp_path)
    entry = root / "r" / "foreign-device"
    entry.write_bytes(b"preserve")
    inspection = inspect_run_entry(root, entry.name)

    with pytest.raises(SafeTreeDeleteFailure) as raised:
        delete_run_entry(
            root,
            name=entry.name,
            expected_device=inspection.device + 1,
            expected_inode=inspection.inode,
            expected_mode=inspection.mode,
            deadline=101.0,
            monotonic=lambda: 100.0,
        )

    assert raised.value.failure_category == "identity_changed"
    assert raised.value.removed_allocated_bytes == 0
    assert raised.value.removed_inode_count == 0
    assert entry.read_bytes() == b"preserve"


def test_o16_identity_replacement_race_refuses_without_deleting_replacement(
    tmp_path: Path,
) -> None:
    root = private_root(tmp_path)
    entry = root / "r" / "replace-me"
    entry.write_bytes(b"original")

    def checkpoint(stage: str) -> None:
        if stage == "before_first_delete":
            entry.unlink()
            entry.write_bytes(b"replacement")

    result = reclaim_run_population(
        root,
        approved(),
        now_seconds=100,
        process_is_live=dead,
        checkpoint=checkpoint,
    )

    evidence = (
        f"outcome={result.outcome!r} "
        f"partial_failure_category={result.partial_failure_category!r} "
        f"identity_replacement_refused={result.identity_replacement_refused!r} "
        f"entry_exists={entry.exists()!r} "
        f"entry_bytes={(entry.read_bytes() if entry.exists() else None)!r}"
    )

    assert result.outcome == "partial", evidence
    assert entry.read_bytes() == b"replacement", evidence
    assert result.identity_replacement_refused is True, evidence


def test_run_entry_api_rejects_unsafe_names(tmp_path: Path) -> None:
    root = private_root(tmp_path)
    for value in ("", ".", "..", "a/b", "a\0b"):
        with pytest.raises(SafeTreeDeleteError):
            inspect_run_entry(root, value)
    assert os.path.isdir(root / "r")
