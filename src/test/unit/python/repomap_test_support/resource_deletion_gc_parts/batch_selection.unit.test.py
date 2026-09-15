"""TTL deletion CLI recovery, candidate isolation, and batch selection contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

import test_hygiene_maintenance as maintenance_tool
from repomap_test_support.resource_deletion_gc import (
    DELETION_MAX_BYTES,
    DELETION_MAX_RUNS,
    DeletionAuthorityMode,
    DeletionBatchSelection,
    DeletionCandidate,
    DeletionGcError,
    PhysicalMutationState,
    discover_quarantine_deletions,
    select_deletion_batch,
)
from repomap_test_support.resource_index import AdvisoryIndex
from repomap_test_support.resource_deletion_records import (
    DeletionRecordStore,
    DeletionRecoveryState,
)
from repomap_test_support.resource_gc_ledger import GcLedger
from repomap_test_support.resource_deletion_gc_test_support import (
    NOW,
    PHASE,
    delete as _delete,
    empty_provider as _empty_provider,
    ledger as _ledger,
    owners as _owners,
    quarantine as _quarantine,
    root as _root,
)


def test_cli_recovers_deleted_index_before_selecting_new_candidates(
    tmp_path: Path, monkeypatch
) -> None:
    root = _root(tmp_path)
    AdvisoryIndex.initialize_empty(
        root / ".index" / "repo-map_dev",
        scratch_root=root,
        requesting_run_id=None,
        initialized_at_seconds=1,
    )
    monkeypatch.setenv("REPOMAP_TEST_SCRATCH_ROOT", str(root))
    order = []

    monkeypatch.setattr(
        maintenance_tool,
        "recover_deleted_index_reconciliations",
        lambda *args, **kwargs: order.append("recover"),
    )

    def no_delete(*args, **kwargs):
        order.append("select")
        return type(
            "Result",
            (),
            {
                "outcomes": (),
                "deleted": 0,
                "protected_restored": 0,
                "protected_restore_collision": 0,
                "ttl_held": 0,
                "ambiguous": 0,
                "operator_attention_required": 0,
                "claim_unavailable": 0,
                "partial_in_progress": 0,
                "stop_reason": "candidate_exhausted",
                "physical_mutation_state": PhysicalMutationState.NONE,
                "removed_allocated_bytes": 0,
                "removed_inode_count": 0,
            },
        )()

    monkeypatch.setattr(maintenance_tool, "delete_quarantine_batch", no_delete)

    result = maintenance_tool.main(
        ["delete-quarantine"],
        protection_provider_factory=lambda scratch, project: _empty_provider,
    )

    assert result == 0
    assert order == ["recover", "select"]


def test_corrupt_candidate_isolated_while_valid_candidate_deletes(tmp_path: Path) -> None:
    root = _root(tmp_path)
    registry, maintenance = _owners(root)
    corrupt, corrupt_ledger = _quarantine(root, registry, maintenance, "corrupt")
    _quarantine(root, registry, maintenance, "valid")
    path = corrupt_ledger.quarantine_record_path("corrupt")
    path.write_text("{not-json")
    path.chmod(0o600)

    result = _delete(root, registry, maintenance)

    assert result.deleted == 1
    assert result.ambiguous == 1
    assert corrupt.is_dir()


def test_invalid_physical_entry_name_isolated_while_valid_candidate_deletes(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    registry, maintenance = _owners(root)
    _quarantine(root, registry, maintenance, "valid")
    invalid = root / ".quarantine" / "repo-map_dev" / "invalid name"
    invalid.mkdir(mode=0o700)

    result = _delete(root, registry, maintenance)

    assert result.deleted == 1
    assert result.ambiguous == 1
    assert result.operator_attention_required == 1
    assert invalid.is_dir()


def test_duplicate_quarantine_record_identity_refuses_whole_pass(tmp_path: Path) -> None:
    root = _root(tmp_path)
    registry, maintenance = _owners(root)
    _, origin = _quarantine(root, registry, maintenance, "duplicate")
    duplicate = _ledger(root, maintenance.owner_token, "duplicate-pass")
    duplicate.quarantine_record_path("duplicate").write_bytes(
        origin.quarantine_record_path("duplicate").read_bytes()
    )
    duplicate.quarantine_record_path("duplicate").chmod(0o600)
    with pytest.raises(DeletionGcError, match="duplicate"):
        discover_quarantine_deletions(
            root,
            registry=registry,
            store=DeletionRecordStore(root),
            now_seconds=NOW,
        )


def _candidate(run_id: str, size: int, at: int, over: bool, state=DeletionRecoveryState.NO_DELETION):
    return DeletionCandidate(
        run_id,
        PHASE,
        Path("/unused") / run_id,
        {"quarantined_at_seconds": at},
        object.__new__(GcLedger),
        size,
        1,
        999_999,
        over,
        state,
        (
            DeletionAuthorityMode.COMMITTED_RECOVERY
            if state is DeletionRecoveryState.COMMITTED_DELETE_REQUIRED
            else DeletionAuthorityMode.ORDINARY_QUARANTINE
        ),
    )


def test_batch_order_limits_and_single_oversized_exception() -> None:
    candidates = tuple(
        _candidate(f"run{number:02d}", 1, 100 - number, number % 2 == 0)
        for number in range(30)
    )
    selected = select_deletion_batch(candidates)
    assert len(selected.candidates) == DELETION_MAX_RUNS
    assert all(item.over_retention for item in selected.candidates[:15])
    committed = _candidate(
        "committed", 1, 999, False, DeletionRecoveryState.COMMITTED_DELETE_REQUIRED
    )
    assert select_deletion_batch(candidates + (committed,)).candidates[0] == committed
    oversized = select_deletion_batch(
        (_candidate("huge", DELETION_MAX_BYTES + 1, 1, False),)
    )
    assert oversized.candidates[0].run_id == "huge"
    assert oversized.allocated_bytes == DELETION_MAX_BYTES + 1
    byte_limited = select_deletion_batch(
        (
            _candidate("a", DELETION_MAX_BYTES, 1, False),
            _candidate("b", 1, 2, False),
        )
    )
    assert byte_limited.limit_reason == "byte_limit"


def test_facade_patch_seams_reach_batch_implementation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import repomap_test_support.resource_deletion_gc as deletion_gc

    root = _root(tmp_path)
    registry, maintenance = _owners(root)
    _quarantine(root, registry, maintenance, "facade-seams")
    discovered = []
    original_discovery = deletion_gc.discover_quarantine_deletions

    def discovery(*args, **kwargs):
        discovered.append(True)
        return original_discovery(*args, **kwargs)

    with monkeypatch.context() as seams:
        seams.setattr(deletion_gc, "discover_quarantine_deletions", discovery)
        seams.setattr(
            deletion_gc,
            "select_deletion_batch",
            lambda candidates: DeletionBatchSelection((), 0, "facade_selection"),
        )
        selected = _delete(root, registry, maintenance)

    assert discovered == [True]
    assert selected.stop_reason == "facade_selection"

    monkeypatch.setattr(
        "repomap_test_support.resource_deletion_gc.DELETION_MAX_SECONDS", 0
    )
    limited = _delete(root, registry, maintenance)
    assert limited.stop_reason == "wall_time_limit"


def test_below_soft_stops_after_first_sufficient_deletion(tmp_path: Path) -> None:
    root = _root(tmp_path)
    registry, maintenance = _owners(root)
    _quarantine(root, registry, maintenance, "first")
    second, _ = _quarantine(root, registry, maintenance, "second")
    checks = iter([False, True])
    result = _delete(root, registry, maintenance, below_soft=lambda: next(checks))
    assert result.deleted == 1
    assert result.stop_reason == "below_soft"
    assert second.is_dir()
