"""Committed deletion authority, resumption, and crash-recovery contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from repomap_test_support.resource_deletion_gc import (
    DeletionGcError,
)
from repomap_test_support.resource_deletion_records import (
    DeletionRecordStore,
    DeletionRecoveryState,
)
from repomap_test_support.resource_deletion_gc_test_support import (
    NOW,
    assert_one_ambiguous as _assert_one_ambiguous,
    committed_fixture as _committed_fixture,
    delete as _delete,
    discovery as _discovery,
    owners as _owners,
    partial_committed as _partial_committed,
    quarantine as _quarantine,
    remove_ordinary_files as _remove_ordinary_files,
    rewrite_barrier as _rewrite_barrier,
    root as _root,
)
from repomap_test_support.resource_lifecycle_claim import (
    ClaimError,
    ClaimPurpose,
    register_protection,
)


@pytest.mark.parametrize(
    "removed",
    [
        pytest.param(
            ("manifest.json", "resource-ledger.json", "payload.txt"),
            id="real-failure-shape",
        ),
        pytest.param(("manifest.json",), id="manifest-only"),
        pytest.param(("resource-ledger.json",), id="resource-ledger-only"),
        pytest.param(
            ("manifest.json", "resource-ledger.json"),
            id="both-authority-files",
        ),
    ],
)
def test_fix1_committed_discovery_does_not_require_ordinary_files(
    tmp_path: Path, removed: tuple[str, ...]
) -> None:
    root = _root(tmp_path)
    registry, maintenance = _owners(root)
    quarantine, _, store, _, _ = _committed_fixture(
        root, registry, maintenance, "partial"
    )
    _remove_ordinary_files(quarantine, *removed)

    discovery = _discovery(root, registry, store)

    assert discovery.ambiguous == 0
    assert len(discovery.candidates) == 1
    candidate = discovery.candidates[0]
    assert candidate.recovery_state is DeletionRecoveryState.COMMITTED_DELETE_REQUIRED
    assert candidate.manifest_process_id is None
    assert candidate.authority_mode.value == "committed_recovery"


@pytest.mark.parametrize("removed", ["manifest.json", "resource-ledger.json"])
def test_fix1_no_deletion_missing_ordinary_evidence_remains_ambiguous(
    tmp_path: Path, removed: str
) -> None:
    root = _root(tmp_path)
    registry, maintenance = _owners(root)
    quarantine, _ = _quarantine(root, registry, maintenance, "ordinary")
    (quarantine / removed).unlink()

    _assert_one_ambiguous(root, registry)


def test_fix1_prepared_missing_ordinary_evidence_remains_reversible(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    registry, maintenance = _owners(root)
    quarantine, _ = _quarantine(root, registry, maintenance, "prepared-missing")

    def stop_after_prepare(candidate):
        raise RuntimeError("fixture prepared")

    with pytest.raises(RuntimeError, match="fixture prepared"):
        _delete(
            root,
            registry,
            maintenance,
            after_prepare=stop_after_prepare,
        )
    _remove_ordinary_files(quarantine, "manifest.json")

    _assert_one_ambiguous(root, registry)
    assert DeletionRecordStore(root).registration_state("prepared-missing") is None


def test_fix1_barrier_without_matching_intent_is_evidence_conflict(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    registry, maintenance = _owners(root)
    quarantine, _, store, _, _ = _committed_fixture(
        root, registry, maintenance, "missing-intent"
    )
    next(store.intent_root.iterdir()).unlink()

    _assert_one_ambiguous(root, registry, store)
    assert quarantine.is_dir()


@pytest.mark.parametrize(
    "field",
    [
        "run_id",
        "phase",
        "project",
        "quarantine_record_id",
        "deletion_intent_record_id",
        "quarantine_device",
        "quarantine_inode",
        "barrier_digest",
        "barrier_record_id",
    ],
)
def test_fix1_barrier_cross_link_mismatch_refuses_resumption(
    tmp_path: Path, field: str
) -> None:
    root = _root(tmp_path)
    registry, maintenance = _owners(root)
    quarantine, _, store, _, _ = _committed_fixture(
        root, registry, maintenance, "cross-link"
    )
    _rewrite_barrier(store, field)

    try:
        discovery = _discovery(root, registry, store)
    except DeletionGcError:
        pass
    else:
        assert discovery.candidates == ()
        assert discovery.operator_attention_required == 1
    assert quarantine.is_dir()


def test_fix1_corrupt_deletion_record_isolated_while_valid_candidate_resumes(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    registry, maintenance = _owners(root)
    valid, _, store, _, _ = _partial_committed(
        root, registry, maintenance, "valid-record"
    )
    valid_guard = registry.acquire(
        "valid-record",
        ClaimPurpose.REPORT_SOURCE_REGISTRATION,
        now_seconds=NOW,
    )
    corrupt, _, _, _, _ = _partial_committed(
        root, registry, maintenance, "corrupt-record"
    )
    registry.release(valid_guard)
    _rewrite_barrier(store, "barrier_record_id", run_id="corrupt-record")

    result = _delete(root, registry, maintenance)
    assert result.deleted == 1
    assert result.ambiguous == 1
    assert corrupt.is_dir()
    assert not valid.exists()


@pytest.mark.parametrize("replacement", ["directory", "symlink"])
def test_fix1_committed_root_identity_replacement_refuses_resumption(
    tmp_path: Path, replacement: str
) -> None:
    root = _root(tmp_path)
    registry, maintenance = _owners(root)
    quarantine, _, store, _, _ = _committed_fixture(
        root, registry, maintenance, "replaced"
    )
    displaced = root / "displaced"
    quarantine.rename(displaced)
    if replacement == "directory":
        quarantine.mkdir(mode=0o700)
    else:
        quarantine.symlink_to(displaced, target_is_directory=True)

    discovery = _discovery(root, registry, store)
    assert discovery.candidates == ()
    assert discovery.operator_attention_required == 1


def test_fix1_committed_resume_does_not_call_mutable_providers(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    registry, maintenance = _owners(root)
    _, _, store, record, _ = _partial_committed(
        root,
        registry,
        maintenance,
        "provider-free",
        ("manifest.json", "resource-ledger.json", "payload.txt"),
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("committed recovery called a mutable provider")

    result = _delete(
        root,
        registry,
        maintenance,
        provider=forbidden,
        process_is_live=forbidden,
    )
    assert result.deleted == 1
    completion = store.evidence(
        "provider-free", record["quarantine_record_id"]
    ).completion
    assert completion is not None
    assert completion["completion_mode"] == "resumed"


@pytest.mark.parametrize("changed", ["root", "barrier"])
def test_fix1_committed_claim_time_revalidation_refuses_changed_authority(
    tmp_path: Path, monkeypatch, changed: str
) -> None:
    root = _root(tmp_path)
    registry, maintenance = _owners(root)
    quarantine, _, store, _, _ = _partial_committed(
        root, registry, maintenance, "claim-race"
    )
    original_require = registry.require_claim
    changed_once: list[bool] = []

    def require_then_change(handle, *, purpose):
        result = original_require(handle, purpose=purpose)
        if not changed_once and purpose is ClaimPurpose.PHYSICAL_DELETE:
            if changed == "root":
                displaced = root / "claim-race-displaced"
                quarantine.rename(displaced)
                quarantine.mkdir(mode=0o700)
            else:
                _rewrite_barrier(store, "barrier_record_id")
            changed_once.append(True)
        return result

    monkeypatch.setattr(registry, "require_claim", require_then_change)
    delete_calls: list[bool] = []
    with pytest.raises(DeletionGcError, match="committed"):
        _delete(
            root,
            registry,
            maintenance,
            safe_delete=lambda *args, **kwargs: delete_calls.append(True),
        )
    assert changed_once == [True]
    assert delete_calls == []


def test_fix1_barrier_blocks_registration_after_ordinary_files_are_gone(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    registry, maintenance = _owners(root)
    _partial_committed(root, registry, maintenance, "registration-blocked")

    for purpose in (
        ClaimPurpose.OPERATOR_PIN_REGISTRATION,
        ClaimPurpose.REPORT_SOURCE_REGISTRATION,
        ClaimPurpose.MONITORING_REGISTRATION,
    ):
        with pytest.raises(ClaimError, match="deletion_in_progress"):
            register_protection(
                root,
                "repo-map_dev",
                "registration-blocked",
                purpose,
                now_seconds=NOW,
            )


def test_fix1_committed_candidate_uses_intent_original_accounting(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    registry, maintenance = _owners(root)
    quarantine, _, store, _, evidence = _committed_fixture(
        root, registry, maintenance, "accounting"
    )
    (quarantine / "payload.txt").unlink()

    candidate = _discovery(root, registry, store).candidates[0]
    assert candidate.allocated_bytes == evidence.intent[
        "measured_target_allocated_bytes"
    ]
    assert candidate.inode_count == evidence.intent["measured_target_inode_count"]
