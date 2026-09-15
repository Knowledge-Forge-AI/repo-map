"""TEST-HYGIENE-MAINT1 recovery installation and record reconciliation."""

from __future__ import annotations

import repomap_test_support.resource_index_recovery as resource_index_recovery_owner

import os
from pathlib import Path

import pytest

from repomap_test_support.resource_hygiene_policy import GIB, HygieneProfile
from repomap_test_support.resource_index import AdvisoryIndex, HostAdmissionRefused
from repomap_test_support.resource_index_maintenance import (
    compact_index,
    rebuild_inventory,
)
from repomap_test_support.resource_ledger_io import (
    read_private_json,
    write_private_json_exclusive,
)
from repomap_test_support.resource_lifecycle_claim import ClaimRegistry


OWNER = "b" * 32


def _recovery():
    try:
        return resource_index_recovery_owner
    except ModuleNotFoundError:
        pytest.fail("maintenance recovery owner is absent")


def _root(tmp_path: Path) -> Path:
    tmp_path.chmod(0o700)
    index = tmp_path / ".index" / "repo-map_dev"
    (index / "runs").mkdir(mode=0o700, parents=True)
    (tmp_path / ".index").chmod(0o700)
    index.chmod(0o700)
    write_private_json_exclusive(
        index / "summary.json",
        {
            "schema": "repomap-test-hygiene-index-summary-v1",
            "generation": 0,
            "allocated_bytes": 0,
            "inode_count": 0,
        },
    )
    return tmp_path


def _maintenance(root: Path):
    registry = ClaimRegistry(root)
    handle = registry.acquire_maintenance("recover-index", now_seconds=10)
    return registry, handle


def _bind(root: Path):
    recovery = _recovery()
    registry, maintenance = _maintenance(root)
    binding = recovery.MaintenanceIndexBinding.bind(
        root, registry, maintenance
    )
    return recovery, registry, maintenance, binding


def _physical(root: Path, run_id: str, payload: bytes = b"physical") -> Path:
    path = root / "r" / run_id
    path.mkdir(mode=0o700, parents=True)
    (path / "payload").write_bytes(payload)
    return path


def _v1_admission(run_id: str) -> dict[str, object]:
    return {
        "schema": "repomap-test-hygiene-admission-v1",
        "run_id": run_id,
        "phase": "TEST-HYGIENE1",
        "profile": "ordinary",
        "byte_quota": 2 * GIB,
        "inode_quota": 50_000,
        "admitted_at_seconds": 1,
    }


def _v1_close(run_id: str) -> dict[str, object]:
    return {
        "schema": "repomap-test-hygiene-close-v1",
        "run_id": run_id,
        "phase": "TEST-HYGIENE1",
        "retention_class": "successful-evidence",
        "allocated_bytes": 8_192,
        "inode_count": 2,
        "closed_at_seconds": 2,
    }


def _v2_admission(run_id: str) -> dict[str, object]:
    return {
        "schema": "repomap-test-hygiene-admission-v2",
        "run_id": run_id,
        "phase": "TEST-HYGIENE-MAINT1",
        "profile": "ordinary",
        "byte_quota": 2 * GIB,
        "inode_quota": 50_000,
        "process_id": os.getpid(),
        "process_start_evidence": "a" * 64,
        "owner_token": OWNER,
        "configuration_sha256": "c" * 64,
        "admitted_at_seconds": 1,
    }


def _v2_close(run_id: str) -> dict[str, object]:
    return {
        "schema": "repomap-test-hygiene-close-v2",
        "run_id": run_id,
        "phase": "TEST-HYGIENE-MAINT1",
        "terminal_outcome": "passed",
        "retention_class": "successful-evidence",
        "allocated_bytes": 8_192,
        "inode_count": 2,
        "retained_evidence_bytes": 0,
        "closed_at_seconds": 2,
    }


def _write_pair(root: Path, run_id: str, *, legacy: bool) -> None:
    records = root / ".index/repo-map_dev/runs"
    admission = _v1_admission(run_id) if legacy else _v2_admission(run_id)
    closed = _v1_close(run_id) if legacy else _v2_close(run_id)
    write_private_json_exclusive(records / f"{run_id}.admitted.json", admission)
    write_private_json_exclusive(records / f"{run_id}.closed.json", closed)


@pytest.mark.parametrize(
    "stage",
    [
        "before_inventory_write",
        "after_inventory_write",
        "before_summary_replace",
        "after_summary_replace",
    ],
)
def test_r10_partial_installation_never_allows_admission(
    tmp_path: Path, stage: str
) -> None:
    root = _root(tmp_path)
    _physical(root, "ambiguous")
    recovery, registry, maintenance, binding = _bind(root)

    def fail(selected: str) -> None:
        if selected == stage:
            raise RuntimeError("injected installation failure")

    with pytest.raises(RuntimeError, match="injected"):
        recovery.recover_index(
            binding,
            registry,
            maintenance,
            now_seconds=20,
            checkpoint=fail,
        )

    assert (root / ".index/repo-map_dev/admission.lock").exists() is (
        stage != "before_inventory_write"
    )

    try:
        index = AdvisoryIndex.open(
            root / ".index/repo-map_dev", scratch_root=root
        )
    except HostAdmissionRefused:
        return
    with pytest.raises(HostAdmissionRefused, match="lock"):
        index.admit(
            run_id="proof",
            phase="TEST-HYGIENE-MAINT1",
            profile=HygieneProfile.ORDINARY,
            hard_watermark_bytes=80 * GIB,
            hard_watermark_inodes=3_000_000,
            admitted_at_seconds=21,
            process_id=os.getpid(),
            process_start_evidence="a" * 64,
            owner_token="d" * 32,
            configuration_sha256="e" * 64,
        )


def test_r13_maintenance_inventory_compaction_removes_present_pair_without_fold(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    _physical(root, "closed")
    recovery, registry, maintenance, binding = _bind(root)
    recovery.recover_index(binding, registry, maintenance, now_seconds=20)
    registry.release_maintenance(maintenance)
    _write_pair(root, "closed", legacy=False)
    second = registry.acquire_maintenance("compact", now_seconds=30)
    index = AdvisoryIndex.open(root / ".index/repo-map_dev", scratch_root=root)

    before = index._read_summary()
    result = compact_index(index, registry, second)

    assert result.folded_runs == 1
    assert result.allocated_bytes == before["allocated_bytes"]
    assert result.inode_count == before["inode_count"]
    assert result.records_remaining == 0


def test_r14_active_admission_remains_at_full_quota(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _physical(root, "active")
    records = root / ".index/repo-map_dev/runs"
    write_private_json_exclusive(
        records / "active.admitted.json", _v2_admission("active")
    )
    recovery, registry, maintenance, binding = _bind(root)

    result = recovery.recover_index(
        binding, registry, maintenance, now_seconds=20
    )
    bound = AdvisoryIndex.open(
        root / ".index/repo-map_dev", scratch_root=root
    ).reconcile()

    assert bound.active_runs == 1
    assert bound.allocated_bytes >= result.allocated_bytes + 2 * GIB


@pytest.mark.parametrize("legacy", [False, True])
def test_r15_redundant_terminal_pair_cleanup_is_idempotent(
    tmp_path: Path, legacy: bool
) -> None:
    root = _root(tmp_path)
    _physical(root, "closed")
    _write_pair(root, "closed", legacy=legacy)
    recovery, registry, maintenance, binding = _bind(root)

    result = recovery.recover_index(
        binding, registry, maintenance, now_seconds=20
    )
    bound = AdvisoryIndex.open(
        root / ".index/repo-map_dev", scratch_root=root
    ).reconcile()

    assert result.redundant_terminal_pairs_reconciled == 1
    assert result.records_remaining == 0
    assert bound.allocated_bytes == result.allocated_bytes


def test_r16_record_cleanup_failure_never_undercounts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    _physical(root, "closed")
    _write_pair(root, "closed", legacy=False)
    recovery, registry, maintenance, binding = _bind(root)
    original = Path.unlink

    def refuse(path: Path, *args, **kwargs):
        if path.name == "closed.closed.json":
            raise OSError("injected unlink refusal")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", refuse)
    with pytest.raises(recovery.IndexRecoveryError, match="cleanup"):
        recovery.recover_index(
            binding, registry, maintenance, now_seconds=20
        )

    index = AdvisoryIndex.open(root / ".index/repo-map_dev", scratch_root=root)
    bound = index.reconcile()
    assert bound.allocated_bytes > read_private_json(index.summary_path)["allocated_bytes"]


def test_r17_record_cap_is_reduced_before_final_reconcile(tmp_path: Path) -> None:
    root = _root(tmp_path)
    for number in range(257):
        run_id = f"closed{number}"
        _physical(root, run_id, b"x")
        _write_pair(root, run_id, legacy=False)
    recovery, registry, maintenance, binding = _bind(root)

    result = recovery.recover_index(
        binding, registry, maintenance, now_seconds=20
    )

    assert result.records_remaining == 0
    assert result.redundant_terminal_pairs_reconciled == 257
    assert AdvisoryIndex.open(
        root / ".index/repo-map_dev", scratch_root=root
    ).reconcile().record_count == 0


def test_r17_unreducible_record_cap_stops_without_admission(tmp_path: Path) -> None:
    root = _root(tmp_path)
    records = root / ".index/repo-map_dev/runs"
    for number in range(513):
        run_id = f"active{number}"
        write_private_json_exclusive(
            records / f"{run_id}.admitted.json", _v2_admission(run_id)
        )
    recovery, registry, maintenance, binding = _bind(root)

    with pytest.raises(recovery.RecordCapUnresolved):
        recovery.recover_index(
            binding, registry, maintenance, now_seconds=20
        )

    assert not (root / ".index/repo-map_dev/admission.lock").exists()
    with pytest.raises(HostAdmissionRefused):
        AdvisoryIndex.open(
            root / ".index/repo-map_dev", scratch_root=root
        )


def test_r18_recovery_does_not_mutate_run_roots(tmp_path: Path) -> None:
    root = _root(tmp_path)
    run = _physical(root, "ambiguous")
    before = _tree_identity(run)
    recovery, registry, maintenance, binding = _bind(root)

    recovery.recover_index(binding, registry, maintenance, now_seconds=20)

    assert _tree_identity(run) == before


def test_inventory_after_recovery_cannot_regress_physical_aggregate(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    _physical(root, "ambiguous")
    recovery, registry, maintenance, binding = _bind(root)
    recovered = recovery.recover_index(
        binding, registry, maintenance, now_seconds=20
    )
    registry.release_maintenance(maintenance)
    next_handle = registry.acquire_maintenance("inventory", now_seconds=30)
    index = AdvisoryIndex.open(root / ".index/repo-map_dev", scratch_root=root)

    rebuilt = rebuild_inventory(
        index,
        registry,
        next_handle,
        now_seconds=30,
        operator_requested=True,
    )

    assert rebuilt.allocated_bytes >= recovered.allocated_bytes
    assert rebuilt.inode_count >= recovered.inode_count


def test_inventory_v1_provenance_still_validates_after_recovery_schema_added(
    tmp_path: Path,
) -> None:
    root = tmp_path
    root.chmod(0o700)
    index = AdvisoryIndex.initialize_empty(
        root / ".index/repo-map_dev",
        scratch_root=root,
        requesting_run_id=None,
        initialized_at_seconds=1,
    )
    registry, maintenance = _maintenance(root)

    rebuild_inventory(
        index,
        registry,
        maintenance,
        now_seconds=20,
        operator_requested=True,
    )

    assert AdvisoryIndex.open(
        root / ".index/repo-map_dev", scratch_root=root
    ).reconcile().generation == 1


def _tree_identity(root: Path) -> tuple[tuple[str, int, int, int], ...]:
    entries = []
    for path in sorted((root, *root.rglob("*")), key=lambda item: str(item)):
        metadata = path.lstat()
        entries.append(
            (
                str(path.relative_to(root)),
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_size,
            )
        )
    return tuple(entries)
