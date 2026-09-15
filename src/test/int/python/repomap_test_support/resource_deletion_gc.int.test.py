"""One isolated TEST-HYGIENE3B2 irreversible synthetic deletion proof."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from repomap_test_support.resource_deletion_gc import (
    DeletionAuthorityMode,
    delete_quarantine_batch,
    discover_quarantine_deletions,
)
from repomap_test_support.resource_deletion_records import (
    DeletionRecordStore,
    DeletionRecoveryState,
)
from repomap_test_support.resource_gc_ledger import GcLedger
from repomap_test_support.resource_lifecycle_claim import (
    ClaimError,
    ClaimPurpose,
    ClaimRegistry,
    ProcessLiveness,
    register_protection,
)
from repomap_test_support.resource_protection_authority import observe_protections
from repomap_test_support.resource_safe_tree_delete import delete_quarantine_tree


from src.test.int.python.repomap_test_support.resource_deletion_gc_fixtures import (
    ELIGIBLE_NOW, BASE, _quarantine, _monitor, cli_deletion_proof, verify_cli_deletion,
)


def test_one_isolated_ttl_gated_physical_deletion_proof(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "proof"
    root.mkdir(mode=0o700)
    (root / "r").mkdir(mode=0o700)
    assert tuple(root.iterdir()) == (root / "r",)
    registry = ClaimRegistry(root)
    maintenance = registry.acquire_maintenance("proof", now_seconds=ELIGIBLE_NOW)
    pass_number = 0

    def new_ledger(prefix: str) -> GcLedger:
        nonlocal pass_number
        pass_number += 1
        return GcLedger.create(
            root,
            project="repo-map_dev",
            pass_id=f"{prefix}-{pass_number}",
            trigger="operator_requested",
            configuration_digest="d" * 64,
            maintenance_owner_token=maintenance.owner_token,
            now_seconds=ELIGIBLE_NOW,
        )

    def run_delete(*, safe_delete=delete_quarantine_tree, now=ELIGIBLE_NOW, **hooks):
        protection_provider = hooks.pop(
            "protection_provider",
            lambda observed: observe_protections(
                root,
                project="repo-map_dev",
                now_seconds=observed,
                include_quarantine=True,
            ),
        )
        process_is_live = hooks.pop(
            "process_is_live", lambda pid: ProcessLiveness.DEAD
        )
        return delete_quarantine_batch(
            root,
            registry,
            maintenance,
            new_ledger("delete"),
            now_seconds=now,
            protection_provider=protection_provider,
            process_is_live=process_is_live,
            aggregate_below_soft=lambda: False,
            safe_delete=safe_delete,
            **hooks,
        )

    ttl_held, _ = _quarantine(
        root, registry, maintenance, new_ledger, "ttl-held", ELIGIBLE_NOW
    )
    report, _ = _quarantine(root, registry, maintenance, new_ledger, "report", BASE)
    monitored, _ = _quarantine(root, registry, maintenance, new_ledger, "monitored", BASE)
    pinned, _ = _quarantine(root, registry, maintenance, new_ledger, "pinned", BASE)
    collision, _ = _quarantine(
        root, registry, maintenance, new_ledger, "zz-collision", BASE
    )
    simple, _ = _quarantine(root, registry, maintenance, new_ledger, "simple", BASE)
    nested, _ = _quarantine(
        root, registry, maintenance, new_ledger, "nested", BASE, nested=True
    )
    linked, _ = _quarantine(root, registry, maintenance, new_ledger, "linked", BASE)
    corrupt, corrupt_ledger = _quarantine(
        root, registry, maintenance, new_ledger, "corrupt", BASE
    )
    sentinel = root / "external-sentinel.txt"
    sentinel.write_text("unchanged")
    (linked / "external-link").symlink_to(sentinel)
    report_record = register_protection(
        root,
        "repo-map_dev",
        "report",
        ClaimPurpose.REPORT_SOURCE_REGISTRATION,
        now_seconds=ELIGIBLE_NOW,
    )
    monitoring_record = register_protection(
        root,
        "repo-map_dev",
        "monitored",
        ClaimPurpose.MONITORING_REGISTRATION,
        now_seconds=ELIGIBLE_NOW,
    )
    pin_record = register_protection(
        root,
        "repo-map_dev",
        "pinned",
        ClaimPurpose.OPERATOR_PIN_REGISTRATION,
        now_seconds=ELIGIBLE_NOW,
    )
    collision_record = register_protection(
        root,
        "repo-map_dev",
        "zz-collision",
        ClaimPurpose.OPERATOR_PIN_REGISTRATION,
        now_seconds=ELIGIBLE_NOW,
    )
    monitoring_link = _monitor(root, "monitored")
    corrupt_record = corrupt_ledger.quarantine_record_path("corrupt")
    corrupt_record.write_text("{not-json")
    corrupt_record.chmod(0o600)

    initial = run_delete(
        now=ELIGIBLE_NOW,
        before_protected_restore=lambda candidate: (
            (root / "r" / "zz-collision").mkdir(mode=0o700)
            if candidate.run_id == "zz-collision"
            else None
        ),
    )

    assert initial.deleted == 3
    assert initial.protected_restored == 3
    assert initial.protected_restore_collision == 1
    assert initial.ttl_held == 1
    assert initial.ambiguous == 1
    assert not simple.exists() and not nested.exists() and not linked.exists()
    assert report.is_dir() is False and (root / "r" / "report").is_dir()
    assert monitored.is_dir() is False and (root / "r" / "monitored").is_dir()
    assert pinned.is_dir() is False and (root / "r" / "pinned").is_dir()
    assert collision.is_dir() and corrupt.is_dir() and ttl_held.is_dir()
    assert sentinel.read_text() == "unchanged"
    collision_destination = root / "r" / "zz-collision"
    assert not tuple(collision_destination.iterdir())
    collision_destination.rmdir()
    collision_guard = registry.acquire(
        "zz-collision",
        ClaimPurpose.OPERATOR_PIN_REGISTRATION,
        now_seconds=ELIGIBLE_NOW,
    )

    prepared, _ = _quarantine(
        root, registry, maintenance, new_ledger, "prepared", BASE
    )
    with pytest.raises(RuntimeError, match="prepared crash"):
        run_delete(
            after_prepare=lambda candidate: (
                (_ for _ in ()).throw(RuntimeError("prepared crash"))
                if candidate.run_id == "prepared"
                else None
            )
        )
    assert prepared.is_dir()
    assert run_delete().deleted == 1

    committed, _ = _quarantine(
        root, registry, maintenance, new_ledger, "committed", BASE
    )
    with pytest.raises(RuntimeError, match="committed crash"):
        run_delete(
            after_barrier=lambda candidate: (
                (_ for _ in ()).throw(RuntimeError("committed crash"))
                if candidate.run_id == "committed"
                else None
            )
        )
    assert committed.is_dir()
    assert run_delete().deleted == 1

    partial, _ = _quarantine(
        root,
        registry,
        maintenance,
        new_ledger,
        "partial",
        BASE,
        nested=True,
    )
    first_nested_file = partial / "nested" / "deeper" / "file-0.txt"
    partial_manifest = partial / "manifest.json"
    partial_resource_ledger = partial / "resource-ledger.json"
    partial_payload = partial / "payload.txt"

    def partial_delete(scratch_root, **kwargs):
        return delete_quarantine_tree(
            scratch_root,
            **{
                key: value
                for key, value in kwargs.items()
                if key not in {"deadline", "monotonic"}
            },
            deadline=60.0,
            monotonic=lambda: (
                60.0
                if all(
                    not path.exists()
                    for path in (
                        first_nested_file,
                        partial_manifest,
                        partial_resource_ledger,
                        partial_payload,
                    )
                )
                else 0.0
            ),
        )

    partial_result = run_delete(safe_delete=partial_delete)
    assert partial_result.partial_in_progress == 1
    assert partial.is_dir()
    assert not first_nested_file.exists()
    assert not partial_manifest.exists()
    assert not partial_resource_ledger.exists()
    assert not partial_payload.exists()
    store = DeletionRecordStore(root)
    assert store.registration_state("partial") == "deletion_in_progress"
    partial_discovery = discover_quarantine_deletions(
        root,
        registry=registry,
        store=store,
        now_seconds=ELIGIBLE_NOW,
    )
    partial_candidate = next(
        candidate
        for candidate in partial_discovery.candidates
        if candidate.run_id == "partial"
    )
    assert partial_candidate.recovery_state is (
        DeletionRecoveryState.COMMITTED_DELETE_REQUIRED
    )
    assert partial_candidate.authority_mode is (
        DeletionAuthorityMode.COMMITTED_RECOVERY
    )
    intent_paths = tuple(store.intent_root.iterdir())
    barrier_paths = tuple(store.barrier_root.iterdir())
    acquired = []
    original_acquire = registry.acquire

    def observe_acquire(run_id, purpose, **kwargs):
        if run_id == "partial":
            acquired.append(purpose)
        return original_acquire(run_id, purpose, **kwargs)

    def forbidden_provider(*args, **kwargs):
        raise AssertionError("COMMITTED recovery called mutable authority")

    with monkeypatch.context() as recovery_patch:
        recovery_patch.setattr(registry, "acquire", observe_acquire)
        resumed = run_delete(
            protection_provider=forbidden_provider,
            process_is_live=forbidden_provider,
        )
    assert resumed.deleted == 1
    assert acquired == [ClaimPurpose.PHYSICAL_DELETE]
    assert not partial.exists()
    quarantine_record_id = partial_candidate.record["quarantine_record_id"]
    assert isinstance(quarantine_record_id, str)
    evidence = store.evidence("partial", quarantine_record_id)
    assert evidence.completion is not None
    assert evidence.completion["completion_mode"] == "resumed"
    assert evidence.tombstone is not None
    assert store.registration_state("partial") == "deleted"
    assert tuple(store.intent_root.iterdir()) == intent_paths
    assert tuple(store.barrier_root.iterdir()) == barrier_paths
    assert run_delete().deleted == 0

    absent, _ = _quarantine(root, registry, maintenance, new_ledger, "root-absent", BASE)

    def remove_root_then_crash(candidate):
        if candidate.run_id != "root-absent":
            return
        record = candidate.record
        result = delete_quarantine_tree(
            root,
            project="repo-map_dev",
            run_id=candidate.run_id,
            expected_device=record["quarantine_device"],
            expected_inode=record["quarantine_inode"],
            deadline=time.monotonic() + 60,
        )
        assert result.completed is True
        raise RuntimeError("root absent crash")

    with pytest.raises(RuntimeError, match="root absent crash"):
        run_delete(after_barrier=remove_root_then_crash)
    assert not absent.exists()
    assert run_delete().deleted == 1

    missing_tombstone, _ = _quarantine(
        root, registry, maintenance, new_ledger, "missing-tombstone", BASE
    )
    original_finalize = DeletionRecordStore.finalize_tombstone
    monkeypatch.setattr(
        DeletionRecordStore,
        "finalize_tombstone",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("tombstone crash")
        ),
    )
    with pytest.raises(RuntimeError, match="tombstone crash"):
        run_delete()
    assert not missing_tombstone.exists()
    monkeypatch.setattr(DeletionRecordStore, "finalize_tombstone", original_finalize)
    assert run_delete().deleted == 1

    cli_root, index, cli_a, cli_b = cli_deletion_proof(
        tmp_path, monkeypatch, registry, maintenance
    )
    registry.release(collision_guard)

    deleted_run_ids = {
        "simple", "nested", "linked", "prepared", "committed", "partial",
        "root-absent", "missing-tombstone",
    }
    store = DeletionRecordStore(root)
    for run_id in deleted_run_ids:
        assert store.registration_state(run_id) == "deleted"
        with pytest.raises(ClaimError, match="deleted"):
            register_protection(
                root,
                "repo-map_dev",
                run_id,
                ClaimPurpose.OPERATOR_PIN_REGISTRATION,
                now_seconds=int(time.time()),
            )
    assert not tuple(ClaimRegistry(root).root.glob("*.claim.json"))
    assert {path.name for path in (root / "r").iterdir()} == {
        "report",
        "monitored",
        "pinned",
    }
    assert {
        path.name
        for path in (root / ".quarantine" / "repo-map_dev").iterdir()
    } == {"ttl-held", "zz-collision", "corrupt"}
    assert all(record.is_file() for record in (
        report_record,
        monitoring_record,
        pin_record,
        collision_record,
    ))
    assert len(
        tuple((root / ".protections" / "repo-map_dev").rglob("*.json"))
    ) == 4
    assert monitoring_link.is_symlink()
    for record in (
        report_record,
        monitoring_record,
        pin_record,
        collision_record,
    ):
        record.unlink()
    monitoring_link.unlink()
    assert not tuple((root / ".protections" / "repo-map_dev").rglob("*.json"))
    assert not tuple(monitoring_link.parent.iterdir())
    assert sentinel.read_text() == "unchanged"
    assert collision.is_dir() and corrupt.is_dir() and ttl_held.is_dir()
    verify_cli_deletion(cli_root, index, cli_a, cli_b)
    assert not tuple(ClaimRegistry(root).root.glob("*.claim.json"))
