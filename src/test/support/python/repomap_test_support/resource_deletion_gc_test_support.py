"""Synthetic, non-destructive fixtures for deletion-GC unit modules."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from repomap_test_support.resource_deletion_gc import (
    delete_quarantine_batch,
    discover_quarantine_deletions,
)
from repomap_test_support.resource_deletion_records import DeletionRecordStore
from repomap_test_support.resource_gc_ledger import GcLedger
from repomap_test_support.resource_ledger import ResourceLedger, RunIdentity
from repomap_test_support.resource_lifecycle_claim import (
    ClaimRegistry,
    ProcessLiveness,
)
from repomap_test_support.resource_protection_authority import (
    ProtectionObservation,
    observe_protections,
)
from repomap_test_support.resource_quarantine_gc import quarantine_batch
from repomap_test_support.resource_safe_tree_delete import SafeTreeDeleteResult
from repomap_test_support.resource_scratch_history import discover_historical_gc


QUARANTINED_AT = 2_000_000
NOW = QUARANTINED_AT + 604_800
PHASE = "TEST-HYGIENE3B2"


def root(tmp_path: Path) -> Path:
    tmp_path.chmod(0o700)
    (tmp_path / "r").mkdir(mode=0o700)
    return tmp_path


def run(root_path: Path, run_id: str) -> Path:
    run_root = root_path / "r" / run_id
    run_root.mkdir(mode=0o700)
    manifest = {
        "schema": "repomap-test-scratch-manifest-v1",
        "project": "repo-map_dev",
        "phase": PHASE,
        "run_kind": "test",
        "run_id": run_id,
        "pid": 999_999,
        "physical_run_root": str(run_root),
        "monitoring_index_path": str(
            root_path / "index" / "repo-map_dev" / PHASE / run_id
        ),
        "state": "passed",
        "retention_policy": "operator_review",
        "exit_status": 0,
        "live_runtime_residue": False,
    }
    (run_root / "manifest.json").write_text(json.dumps(manifest))
    (run_root / "manifest.json").chmod(0o600)
    resource_ledger = ResourceLedger.create(
        run_root / "resource-ledger.json",
        RunIdentity("repo-map_dev", PHASE, run_id),
        now_seconds=0,
    )
    resource_ledger.stamp_terminal("passed", 1)
    (run_root / "payload.txt").write_text("public-safe")
    return run_root


def owners(root_path: Path):
    registry = ClaimRegistry(root_path)
    maintenance = registry.acquire_maintenance(
        "delete-quarantine", now_seconds=NOW
    )
    return registry, maintenance


def ledger(root_path: Path, owner_token: str, pass_id: str) -> GcLedger:
    return GcLedger.create(
        root_path,
        project="repo-map_dev",
        pass_id=pass_id,
        trigger="operator_requested",
        configuration_digest="d" * 64,
        maintenance_owner_token=owner_token,
        now_seconds=NOW,
    )


def quarantine(
    root_path: Path,
    registry: ClaimRegistry,
    maintenance,
    run_id: str,
) -> tuple[Path, GcLedger]:
    run(root_path, run_id)
    candidate = discover_historical_gc(
        root_path,
        current_run_id="current",
        now_seconds=QUARANTINED_AT,
        process_is_live=lambda pid: ProcessLiveness.DEAD,
        active_report_run_ids=set(),
        active_monitoring_run_ids=set(),
    ).eligible[0]
    gc_ledger = ledger(root_path, maintenance.owner_token, f"q-{run_id}")
    result = quarantine_batch(
        root_path,
        registry,
        maintenance,
        gc_ledger,
        (candidate,),
        now_seconds=QUARANTINED_AT,
        process_is_live=lambda pid: ProcessLiveness.DEAD,
        active_report_run_ids=set(),
        active_monitoring_run_ids=set(),
    )
    assert result.quarantined == (run_id,)
    return root_path / ".quarantine" / "repo-map_dev" / run_id, gc_ledger


def protection_provider(root_path: Path):
    return lambda now: observe_protections(
        root_path,
        project="repo-map_dev",
        now_seconds=now,
        include_quarantine=True,
    )


def empty_provider(now: int) -> ProtectionObservation:
    return ProtectionObservation.create(
        project="repo-map_dev",
        observed_at_seconds=now,
        report_run_ids=(),
        monitoring_run_ids=(),
        pin_run_ids=(),
    )


def move_delete(root_path: Path):
    def move(
        scratch_root,
        *,
        project,
        run_id,
        expected_device,
        expected_inode,
        **kwargs,
    ):
        source = Path(scratch_root) / ".quarantine" / project / run_id
        metadata = source.stat(follow_symlinks=False)
        assert (metadata.st_dev, metadata.st_ino) == (
            expected_device,
            expected_inode,
        )
        holding = Path(scratch_root) / ".unit-delete-hold"
        holding.mkdir(mode=0o700, exist_ok=True)
        source.rename(holding / run_id)
        return SafeTreeDeleteResult(True, 4096, 3, "deleted")

    return move


def delete(
    root_path: Path,
    registry: ClaimRegistry,
    maintenance,
    *,
    provider=None,
    process_is_live=lambda pid: ProcessLiveness.DEAD,
    below_soft=lambda: False,
    safe_delete=None,
    **kwargs,
):
    gc_root = root_path / ".gc" / "repo-map_dev"
    gc_ledger = ledger(
        root_path,
        maintenance.owner_token,
        f"d-{len(tuple(gc_root.iterdir()))}",
    )
    return delete_quarantine_batch(
        root_path,
        registry,
        maintenance,
        gc_ledger,
        now_seconds=NOW,
        protection_provider=provider or protection_provider(root_path),
        process_is_live=process_is_live,
        aggregate_below_soft=below_soft,
        monotonic=lambda: 0.0,
        safe_delete=safe_delete or move_delete(root_path),
        **kwargs,
    )


def committed_fixture(root_path: Path, registry, maintenance, run_id: str):
    quarantine_root, quarantine_ledger = quarantine(
        root_path, registry, maintenance, run_id
    )

    def stop_after_barrier(candidate):
        raise RuntimeError("fixture committed")

    with pytest.raises(RuntimeError, match="fixture committed"):
        delete(
            root_path,
            registry,
            maintenance,
            after_barrier=stop_after_barrier,
        )
    record = json.loads(
        quarantine_ledger.quarantine_record_path(run_id).read_text()
    )
    store = DeletionRecordStore(root_path)
    evidence = store.evidence(run_id, record["quarantine_record_id"])
    assert evidence.intent is not None and evidence.barrier is not None
    return quarantine_root, quarantine_ledger, store, record, evidence


def remove_ordinary_files(quarantine_root: Path, *names: str) -> None:
    for name in names:
        (quarantine_root / name).unlink()


def partial_committed(
    root_path: Path,
    registry,
    maintenance,
    run_id: str,
    names: tuple[str, ...] = ("manifest.json", "resource-ledger.json"),
):
    result = committed_fixture(root_path, registry, maintenance, run_id)
    remove_ordinary_files(result[0], *names)
    return result


def discovery(root_path: Path, registry, store=None):
    return discover_quarantine_deletions(
        root_path,
        registry=registry,
        store=store or DeletionRecordStore(root_path),
        now_seconds=NOW,
    )


def assert_one_ambiguous(root_path: Path, registry, store=None) -> None:
    result = discovery(root_path, registry, store)
    assert result.candidates == ()
    assert result.ambiguous == 1


def rewrite_barrier(
    store: DeletionRecordStore, field: str, *, run_id: str | None = None
) -> None:
    path = next(
        candidate
        for candidate in store.barrier_root.iterdir()
        if run_id is None or candidate.name.startswith(f"{run_id}--")
    )
    payload = json.loads(path.read_text())
    replacements = {
        "run_id": "other-run",
        "phase": "OTHER-PHASE",
        "project": "other-project",
        "quarantine_record_id": "a" * 64,
        "deletion_intent_record_id": "b" * 64,
        "quarantine_device": payload["quarantine_device"] + 1,
        "quarantine_inode": payload["quarantine_inode"] + 1,
    }
    if field in {"barrier_digest", "barrier_record_id"}:
        payload[field] = "0" * 64
    else:
        payload[field] = replacements[field]
        seed = dict(payload)
        seed.pop("barrier_record_id")
        seed.pop("barrier_digest")
        digest = hashlib.sha256(
            json.dumps(seed, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        identified = {**seed, "barrier_digest": digest}
        payload = {
            **identified,
            "barrier_record_id": hashlib.sha256(
                json.dumps(
                    identified,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest(),
        }
    path.write_text(json.dumps(payload))
    path.chmod(0o600)


__all__ = [
    "NOW",
    "PHASE",
    "QUARANTINED_AT",
    "assert_one_ambiguous",
    "committed_fixture",
    "delete",
    "discovery",
    "empty_provider",
    "ledger",
    "move_delete",
    "owners",
    "partial_committed",
    "protection_provider",
    "quarantine",
    "remove_ordinary_files",
    "rewrite_barrier",
    "root",
    "run",
]
