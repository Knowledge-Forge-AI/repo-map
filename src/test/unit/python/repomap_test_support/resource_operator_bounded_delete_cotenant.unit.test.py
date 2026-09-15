"""TEST-HYGIENE3B3-FIX4 bounded delete contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast
import pytest

from repomap_test_support.resource_operator_reclamation import (
    CONFIRMATION_LITERAL,
    OPERATOR_DELETION_MAX_SECONDS,
    OperatorReclamationRequest,
    reclaim_run_population,
)
import repomap_test_support.resource_operator_reclamation as reclamation
from repomap_test_support.resource_operator_records import (
    read_operation_record,
)
from repomap_test_support.resource_operator_reclamation_test_support import (
    add_run,
    dead,
    private_root,
)
from repomap_test_support.resource_safe_tree_delete import (
    SafeTreeDeleteError,
    SafeTreeDeleteResult,
    delete_run_entry,
    inspect_run_entry,
)
import test_hygiene_maintenance as maintenance_tool


def approved() -> OperatorReclamationRequest:
    return OperatorReclamationRequest(CONFIRMATION_LITERAL, False, False)


def test_b1_delete_run_entry_accepts_finite_absolute_deadline(
    tmp_path: Path,
) -> None:
    root = private_root(tmp_path)
    entry = root / "r" / "bounded-file"
    entry.write_bytes(b"payload")
    inspection = inspect_run_entry(root, entry.name)

    result = delete_run_entry(
        root,
        name=entry.name,
        expected_device=inspection.device,
        expected_inode=inspection.inode,
        expected_mode=inspection.mode,
        deadline=101.0,
        monotonic=lambda: 100.0,
    )

    assert result.completed is True
    assert not entry.exists()


@pytest.mark.parametrize("deadline", [float("inf"), float("nan"), None, True])
def test_b1_delete_run_entry_rejects_nonfinite_or_non_numeric_deadline(
    tmp_path: Path, deadline: float | None
) -> None:
    def _invalid_deadline(value: float | None) -> float:
        """Narrow runtime-invalid deadline builder for negative controls."""
        return cast(float, value)

    root = private_root(tmp_path)
    entry = root / "r" / "invalid-deadline"
    entry.write_bytes(b"preserve")
    inspection = inspect_run_entry(root, entry.name)

    with pytest.raises(SafeTreeDeleteError, match="deletion deadline is invalid"):
        delete_run_entry(
            root,
            name=entry.name,
            expected_device=inspection.device,
            expected_inode=inspection.inode,
            expected_mode=inspection.mode,
            deadline=_invalid_deadline(deadline),
        )
    assert entry.exists()


def test_b2_b3_recursive_deadline_preserves_partial_directory_with_exact_progress(
    tmp_path: Path,
) -> None:
    root = private_root(tmp_path)
    entry = root / "r" / "partial-tree"
    entry.mkdir(mode=0o700)
    first = entry / "a.bin"
    first.write_bytes(b"a" * 4096)
    second = entry / "b.bin"
    second.write_bytes(b"b" * 4096)
    first_bytes = first.stat(follow_symlinks=False).st_blocks * 512
    inspection = inspect_run_entry(root, entry.name)
    ticks = iter((0.0, 61.0))

    result = delete_run_entry(
        root,
        name=entry.name,
        expected_device=inspection.device,
        expected_inode=inspection.inode,
        expected_mode=inspection.mode,
        deadline=60.0,
        monotonic=lambda: next(ticks),
    )

    assert result == SafeTreeDeleteResult(
        completed=False,
        removed_allocated_bytes=first_bytes,
        removed_inode_count=1,
        stop_reason="wall_time_limit",
    )
    assert entry.is_dir()
    assert not first.exists()
    assert second.exists()


@pytest.mark.parametrize("kind", ["file", "directory"])
def test_b4_expired_deadline_before_top_level_remove_deletes_nothing(
    tmp_path: Path, kind: str
) -> None:
    root = private_root(tmp_path)
    entry = root / "r" / f"expired-{kind}"
    if kind == "file":
        entry.write_bytes(b"preserve")
    else:
        entry.mkdir(mode=0o700)
    inspection = inspect_run_entry(root, entry.name)

    result = delete_run_entry(
        root,
        name=entry.name,
        expected_device=inspection.device,
        expected_inode=inspection.inode,
        expected_mode=inspection.mode,
        deadline=60.0,
        monotonic=lambda: 60.0,
    )

    assert result == SafeTreeDeleteResult(False, 0, 0, "wall_time_limit")
    assert entry.exists()


def test_b5_b6_operation_deadline_is_shared_and_stops_before_later_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = private_root(tmp_path)
    for name in ("a-first", "b-partial", "c-later"):
        add_run(root, name)
    calls: list[tuple[str, float]] = []

    def bounded_delete(_root: Path, *, name: str, deadline: float, **_kwargs):
        calls.append((name, deadline))
        if name == "a-first":
            return SafeTreeDeleteResult(True, 20, 2, "deleted")
        return SafeTreeDeleteResult(False, 10, 1, "wall_time_limit")

    monkeypatch.setattr(reclamation, "delete_run_entry", bounded_delete)
    result = reclaim_run_population(
        root,
        approved(),
        now_seconds=100,
        process_is_live=dead,
        monotonic=lambda: 5.0,
    )

    assert calls == [
        ("a-first", 5.0 + OPERATOR_DELETION_MAX_SECONDS),
        ("b-partial", 5.0 + OPERATOR_DELETION_MAX_SECONDS),
    ]
    assert result.removed_entry_count == 1
    assert result.removed_allocated_bytes == 30
    assert result.removed_inode_count == 3
    assert (root / "r" / "c-later").exists()


def test_b7_b8_b9_b10_b11_partial_is_durable_and_defers_reconciliation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = private_root(tmp_path)
    add_run(root, "partial-entry")
    calls: list[str] = []

    monkeypatch.setattr(
        reclamation,
        "delete_run_entry",
        lambda *_args, **_kwargs: SafeTreeDeleteResult(
            False, 512, 1, "wall_time_limit"
        ),
    )
    monkeypatch.setattr(
        reclamation,
        "unlink_owned",
        lambda *_args: calls.append("unlink_owned"),
    )
    monkeypatch.setattr(
        reclamation,
        "recover_index",
        lambda *_args, **_kwargs: calls.append("recover_index"),
    )
    result = reclaim_run_population(
        root,
        approved(),
        now_seconds=100,
        process_is_live=dead,
        monotonic=lambda: 0.0,
    )
    record = read_operation_record(result.operation_path)

    assert result.outcome == "partial"
    assert result.partial_reason == "wall_time_limit"
    assert result.point_of_no_return is True
    assert result.physical_mutation_performed is True
    assert result.removed_entry_count == 0
    assert record["state"] == "partial"
    assert record["partial_reason"] == "wall_time_limit"
    assert record["removed_allocated_bytes"] == 512
    assert record["removed_inode_count"] == 1
    assert calls == []
    assert result.barrier_released is False
    assert (root / ".index" / "repo-map_dev" / "admission.lock").exists()
    maintenance = root / ".maintenance" / "repo-map_dev"
    assert not tuple(maintenance.iterdir())


def test_b14_completed_before_deadline_preserves_completed_semantics(
    tmp_path: Path,
) -> None:
    root = private_root(tmp_path)
    add_run(root, "complete")

    result = reclaim_run_population(
        root,
        approved(),
        now_seconds=100,
        process_is_live=dead,
        monotonic=lambda: 0.0,
    )

    assert result.outcome == "completed"
    assert result.partial_reason is None
    assert result.removed_entry_count == 1
    assert result.barrier_released is True


def test_l5_cli_projects_wall_time_partial_and_returns_two(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = private_root(tmp_path)
    add_run(root, "partial")
    monkeypatch.setenv("REPOMAP_TEST_SCRATCH_ROOT", str(root))
    monkeypatch.setattr(
        reclamation,
        "delete_run_entry",
        lambda *_args, **_kwargs: SafeTreeDeleteResult(
            False, 1, 1, "wall_time_limit"
        ),
    )

    exit_code = maintenance_tool.main(
        ["operator-reclaim", "--confirm", CONFIRMATION_LITERAL]
    )
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert output["outcome"] == "partial"
    assert output["partial_reason"] == "wall_time_limit"
