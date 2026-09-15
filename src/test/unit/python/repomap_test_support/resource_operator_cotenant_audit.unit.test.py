"""TEST-HYGIENE3B3-FIX4 co-tenant audit evidence contracts."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from repomap_test_support.resource_lifecycle_claim import (
    ProcessLiveness,
)
from repomap_test_support.resource_operator_reclamation import (
    CONFIRMATION_LITERAL,
    OperatorReclamationRequest,
    reclaim_run_population,
)
import repomap_test_support.resource_operator_reclamation as reclamation
from repomap_test_support.resource_operator_records import (
    create_operation_record,
    read_operation_record,
)
from repomap_test_support.resource_operator_reclamation_test_support import (
    add_run,
    private_root,
)
from repomap_test_support.resource_operator_scope import (
    classify_cotenant_activity,
    classify_liveness,
    close_scope_pins,
    inventory_operator_scope,
)
from repomap_test_support.resource_safe_tree_delete import (
    SafeTreeDeleteResult,
)

REPO_ROOT = Path(__file__).resolve().parents[5]


def approved() -> OperatorReclamationRequest:
    return OperatorReclamationRequest(CONFIRMATION_LITERAL, False, False)


def _inventory(root: Path):
    """Inventory for classification only; these tests never delete."""
    entries = inventory_operator_scope(root)
    close_scope_pins(entries)
    return entries


def _activity(root: Path, state: ProcessLiveness) -> dict[str, int]:
    return classify_cotenant_activity(_inventory(root), lambda _pid: state)


def test_c1_foreign_running_missing_pid_counts_invalid_only(tmp_path: Path) -> None:
    root = private_root(tmp_path)
    add_run(root, "foreign-missing", project="other", state="running", pid=None)
    values = _activity(root, ProcessLiveness.LIVE)

    assert values["foreign_running_manifest_count"] == 1
    assert values["foreign_invalid_or_missing_pid_count"] == 1
    assert values["foreign_positive_pid_manifest_count"] == 0
    assert values["foreign_live_observed_count"] == 0


def test_c2_foreign_live_is_private_audit_only(tmp_path: Path) -> None:
    root = private_root(tmp_path)
    add_run(root, 'foreign-live', project='other-project', state='running', pid=777)
    result = reclaim_run_population(root, approved(), now_seconds=100, process_is_live=lambda _pid: ProcessLiveness.LIVE)
    record = read_operation_record(result.operation_path)
    assert result.live_count == 0
    assert result.unknown_count == 0
    assert record['foreign_live_observed_count'] == 1


@pytest.mark.parametrize(
    ("state", "field"),
    [
        (ProcessLiveness.DEAD, "foreign_dead_observed_count"),
        (ProcessLiveness.UNKNOWN, "foreign_unknown_observed_count"),
    ],
)
def test_c3_c4_foreign_positive_pid_is_audit_only(
    tmp_path: Path, state: ProcessLiveness, field: str
) -> None:
    root = private_root(tmp_path)
    add_run(root, "foreign", project="other", state="running", pid=123)
    entries = _inventory(root)

    assert classify_liveness(entries, lambda _pid: state) == (0, 0)
    values = classify_cotenant_activity(entries, lambda _pid: state)
    assert values["foreign_positive_pid_manifest_count"] == 1
    assert values[field] == 1


@pytest.mark.parametrize("state", tuple(ProcessLiveness))
def test_c5_ambiguous_variants_are_audit_only(
    tmp_path: Path, state: ProcessLiveness
) -> None:
    root = private_root(tmp_path)
    add_run(root, "ambiguous", exact=False, state="running", pid=123)
    entries = _inventory(root)

    assert classify_liveness(entries, lambda _pid: state) == (0, 0)
    values = classify_cotenant_activity(entries, lambda _pid: state)
    assert values["ambiguous_running_manifest_count"] == 1
    assert values[f"ambiguous_{state.value}_observed_count"] == 1


def test_c5_ambiguous_missing_pid_is_invalid_audit_only(tmp_path: Path) -> None:
    root = private_root(tmp_path)
    add_run(root, "ambiguous", exact=False, state="running", pid=None)
    values = _activity(root, ProcessLiveness.LIVE)

    assert values["ambiguous_running_manifest_count"] == 1
    assert values["ambiguous_invalid_or_missing_pid_count"] == 1
    assert values["ambiguous_positive_pid_manifest_count"] == 0


def test_c5_oversized_foreign_pid_is_invalid_and_cannot_refuse(
    tmp_path: Path,
) -> None:
    root = private_root(tmp_path)
    add_run(root, "foreign", project="other", state="running", pid=2**63)

    result = reclaim_run_population(
        root,
        approved(),
        now_seconds=100,
        process_is_live=lambda _pid: (_ for _ in ()).throw(AssertionError()),
    )
    record = read_operation_record(result.operation_path)

    assert result.outcome == "completed"
    assert record["foreign_invalid_or_missing_pid_count"] == 1


def test_c5_foreign_probe_failure_degrades_to_unknown_audit(
    tmp_path: Path,
) -> None:
    root = private_root(tmp_path)
    add_run(root, "foreign", project="other", state="running", pid=123)

    result = reclaim_run_population(
        root,
        approved(),
        now_seconds=100,
        process_is_live=lambda _pid: (_ for _ in ()).throw(OverflowError()),
    )
    record = read_operation_record(result.operation_path)

    assert result.outcome == "completed"
    assert result.live_count == 0
    assert result.unknown_count == 0
    assert record["foreign_unknown_observed_count"] == 1


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (ProcessLiveness.LIVE, (1, 0)),
        (ProcessLiveness.UNKNOWN, (0, 1)),
    ],
)
def test_c6_exact_valid_liveness_is_excluded_from_cotenant_counts(
    tmp_path: Path,
    state: ProcessLiveness,
    expected: tuple[int, int],
) -> None:
    root = private_root(tmp_path)
    add_run(root, "valid", state="running", pid=123)
    entries = _inventory(root)

    assert classify_liveness(entries, lambda _pid: state) == expected
    assert sum(classify_cotenant_activity(entries, lambda _pid: state).values()) == 0
    result = reclaim_run_population(
        root,
        approved(),
        now_seconds=100,
        process_is_live=lambda _pid: state,
    )
    assert result.outcome == (
        "live_run_refused"
        if state is ProcessLiveness.LIVE
        else "unknown_liveness_refused"
    )


def test_c7_new_private_evidence_round_trips_and_writes_are_strict(
    tmp_path: Path,
) -> None:
    root = private_root(tmp_path)
    add_run(root, "foreign", project="other", state="running", pid=123)
    result = reclaim_run_population(
        root,
        approved(),
        now_seconds=100,
        process_is_live=lambda _pid: ProcessLiveness.DEAD,
    )
    record = read_operation_record(result.operation_path)

    assert record["foreign_dead_observed_count"] == 1
    incomplete = dict(record)
    incomplete.pop("foreign_dead_observed_count")
    with pytest.raises(ValueError, match="fields"):
        create_operation_record(root, incomplete)


def test_c8_old_accepted_operation_evidence_remains_readable(tmp_path: Path) -> None:
    fixture = REPO_ROOT / (
        "src/test/fixtures/test_hygiene/operator-reclamation-v1.json"
    )
    path = tmp_path / "old-operation.json"
    path.write_bytes(fixture.read_bytes())
    path.chmod(0o600)

    record = read_operation_record(path)

    assert record["schema"] == "repomap-test-operator-reclamation-v1"
    assert record["partial_failure_category"] is None
    assert record["partial_reason"] is None
    assert record["foreign_running_manifest_count"] == 0


def test_c9_public_projection_contains_only_closed_partial_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = private_root(tmp_path)
    run = add_run(root, "foreign-private", project="other-project", state="running", pid=777)
    monkeypatch.setattr(
        reclamation,
        "delete_run_entry",
        lambda *_args, **_kwargs: SafeTreeDeleteResult(
            False, 1, 1, "wall_time_limit"
        ),
    )
    result = reclaim_run_population(
        root,
        approved(),
        now_seconds=100,
        process_is_live=lambda _pid: ProcessLiveness.LIVE,
        monotonic=lambda: 0.0,
    )
    projection = reclamation.public_operator_projection(result)
    rendered = json.dumps(projection, sort_keys=True)

    assert projection["partial_reason"] == "wall_time_limit"
    assert not any("foreign_" in key or "ambiguous_" in key for key in projection)
    for private in (str(root), run.name, "777", result.operation_id):
        assert private not in rendered


def test_c10_completed_deletion_retains_predelete_cotenant_evidence(
    tmp_path: Path,
) -> None:
    root = private_root(tmp_path)
    add_run(root, "foreign", project="other", state="running", pid=123)

    result = reclaim_run_population(
        root,
        approved(),
        now_seconds=100,
        process_is_live=lambda _pid: ProcessLiveness.UNKNOWN,
    )
    record = read_operation_record(result.operation_path)

    assert result.outcome == "completed"
    assert record["marker_count"] == 0
    assert record["foreign_running_manifest_count"] == 1
    assert record["foreign_unknown_observed_count"] == 1
    assert tuple((root / "r").iterdir()) == ()
