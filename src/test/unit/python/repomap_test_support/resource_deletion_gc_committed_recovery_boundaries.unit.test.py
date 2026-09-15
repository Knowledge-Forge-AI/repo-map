from __future__ import annotations

from pathlib import Path

import pytest

from repomap_test_support.resource_deletion_gc import (
    select_deletion_batch,
)
from repomap_test_support.resource_deletion_records import (
    DeletionRecordStore,
)
from repomap_test_support.resource_deletion_gc_test_support import (
    delete as _delete,
    discovery as _discovery,
    owners as _owners,
    partial_committed as _partial_committed,
    quarantine as _quarantine,
    remove_ordinary_files as _remove_ordinary_files,
    root as _root,
)
from repomap_test_support.resource_safe_tree_delete import SafeTreeDeleteResult

def test_fix1_partial_committed_work_precedes_new_ordinary_work(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    registry, maintenance = _owners(root)
    _, _, store, _, _ = _partial_committed(
        root, registry, maintenance, "zz-committed"
    )
    _quarantine(root, registry, maintenance, "aa-ordinary")

    discovery = _discovery(root, registry, store)
    selection = select_deletion_batch(discovery.candidates)
    assert selection.candidates[0].run_id == "zz-committed"


def test_fix1_below_soft_does_not_strand_partial_committed_work(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    registry, maintenance = _owners(root)
    _partial_committed(root, registry, maintenance, "below-soft")

    result = _delete(root, registry, maintenance, below_soft=lambda: True)
    assert result.deleted == 1


def test_fix1_repeated_partial_resume_is_idempotent(tmp_path: Path) -> None:
    root = _root(tmp_path)
    registry, maintenance = _owners(root)
    quarantine, _ = _quarantine(root, registry, maintenance, "repeat-partial")

    def partial(*args, **kwargs):
        return SafeTreeDeleteResult(False, 0, 0, "wall_time_limit")

    first = _delete(root, registry, maintenance, safe_delete=partial)
    assert first.partial_in_progress == 1
    store = DeletionRecordStore(root)
    intent_paths = tuple(store.intent_root.iterdir())
    barrier_paths = tuple(store.barrier_root.iterdir())
    _remove_ordinary_files(
        quarantine, "manifest.json", "resource-ledger.json", "payload.txt"
    )

    second = _delete(root, registry, maintenance, safe_delete=partial)
    assert second.partial_in_progress == 1
    assert tuple(store.intent_root.iterdir()) == intent_paths
    assert tuple(store.barrier_root.iterdir()) == barrier_paths
    assert _delete(root, registry, maintenance).deleted == 1


def test_root_absent_before_completion_is_finalized(tmp_path: Path) -> None:
    root = _root(tmp_path)
    registry, maintenance = _owners(root)
    _quarantine(root, registry, maintenance, "absent")

    def move_then_crash(candidate):
        holding = root / ".unit-delete-hold"
        holding.mkdir(mode=0o700)
        candidate.root.rename(holding / candidate.run_id)
        raise RuntimeError("crash after root removal")

    with pytest.raises(RuntimeError, match="root removal"):
        _delete(root, registry, maintenance, after_barrier=move_then_crash)
    result = _delete(root, registry, maintenance)
    assert result.deleted == 1
    assert DeletionRecordStore(root).registration_state("absent") == "deleted"


def test_completion_without_tombstone_is_finalized(
    tmp_path: Path, monkeypatch
) -> None:
    root = _root(tmp_path)
    registry, maintenance = _owners(root)
    _quarantine(root, registry, maintenance, "tombstone")
    original = DeletionRecordStore.finalize_tombstone
    monkeypatch.setattr(
        DeletionRecordStore,
        "finalize_tombstone",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("crash before tombstone")
        ),
    )
    with pytest.raises(RuntimeError, match="before tombstone"):
        _delete(root, registry, maintenance)
    monkeypatch.setattr(DeletionRecordStore, "finalize_tombstone", original)
    assert _delete(root, registry, maintenance).deleted == 1


def test_completed_recovery_is_idempotent(tmp_path: Path) -> None:
    root = _root(tmp_path)
    registry, maintenance = _owners(root)
    _quarantine(root, registry, maintenance, "done")
    assert _delete(root, registry, maintenance).deleted == 1
    second = _delete(root, registry, maintenance)
    assert second.deleted == 0
    assert second.outcomes == ()
