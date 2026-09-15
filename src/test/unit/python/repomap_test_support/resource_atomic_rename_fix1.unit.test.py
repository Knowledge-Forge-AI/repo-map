"""TEST-HYGIENE3B1-FIX1 atomic no-replace quarantine/restore contracts."""

from __future__ import annotations

import repomap_test_support.resource_atomic_rename as resource_atomic_rename_owner

import json
from pathlib import Path

import pytest

from repomap_test_support.resource_gc_ledger import GcLedger
from repomap_test_support.resource_ledger import ResourceLedger, RunIdentity
from repomap_test_support.resource_lifecycle_claim import ClaimRegistry
from repomap_test_support.resource_quarantine_gc import (
    QuarantineError,
    quarantine_batch,
)
from repomap_test_support.resource_quarantine_records import restore_quarantined
from repomap_test_support.resource_scratch_history import discover_historical_gc


NOW = 2_000_000


def _root(tmp_path: Path) -> Path:
    tmp_path.chmod(0o700)
    (tmp_path / "r").mkdir(mode=0o700)
    return tmp_path


def _run(root: Path, run_id: str = "run1") -> Path:
    run = root / "r" / run_id
    run.mkdir(mode=0o700)
    manifest = {
        "schema": "repomap-test-scratch-manifest-v1",
        "project": "repo-map_dev",
        "phase": "TEST-HYGIENE3B1-FIX1",
        "run_kind": "test",
        "run_id": run_id,
        "pid": 999_999,
        "physical_run_root": str(run),
        "monitoring_index_path": str(root / "index" / run_id),
        "state": "passed",
        "retention_policy": "operator_review",
        "exit_status": 0,
        "live_runtime_residue": False,
    }
    (run / "manifest.json").write_text(json.dumps(manifest))
    (run / "manifest.json").chmod(0o600)
    ledger = ResourceLedger.create(
        run / "resource-ledger.json",
        RunIdentity("repo-map_dev", "TEST-HYGIENE3B1-FIX1", run_id),
        now_seconds=0,
    )
    ledger.stamp_terminal("passed", 1)
    return run


def _owners(root: Path):
    registry = ClaimRegistry(root)
    maintenance = registry.acquire_maintenance("quarantine", now_seconds=NOW)
    ledger = GcLedger.create(
        root,
        project="repo-map_dev",
        pass_id="pass1",
        trigger="operator_requested",
        configuration_digest="d" * 64,
        maintenance_owner_token=maintenance.owner_token,
        now_seconds=NOW,
    )
    return registry, maintenance, ledger


def _candidate(root: Path):
    return discover_historical_gc(
        root,
        current_run_id="current",
        now_seconds=NOW,
        process_is_live=lambda pid: False,
        active_report_run_ids=set(),
        active_monitoring_run_ids=set(),
    ).eligible[0]


def _quarantine(root: Path, registry, maintenance, ledger, *, before_rename=None):
    return quarantine_batch(
        root,
        registry,
        maintenance,
        ledger,
        (_candidate(root),),
        now_seconds=NOW,
        process_is_live=lambda pid: False,
        active_report_run_ids=set(),
        active_monitoring_run_ids=set(),
        before_rename=before_rename,
    )


def test_r13_quarantine_destination_race_never_replaces(tmp_path: Path):
    root = _root(tmp_path)
    source = _run(root)
    source_identity = source.stat().st_ino
    registry, maintenance, ledger = _owners(root)
    destination = root / ".quarantine" / "repo-map_dev" / "run1"
    collision_identity: list[int] = []

    def race(_candidate):
        destination.mkdir(mode=0o700)
        collision_identity.append(destination.stat().st_ino)

    with pytest.raises(QuarantineError, match="collision|already exists"):
        _quarantine(
            root,
            registry,
            maintenance,
            ledger,
            before_rename=race,
        )

    assert source.stat().st_ino == source_identity
    assert destination.stat().st_ino == collision_identity[0]
    assert not any(record.event == "rename_completion" for record in ledger.records())


def test_r14_restore_destination_race_never_replaces(tmp_path: Path):
    root = _root(tmp_path)
    _run(root)
    registry, maintenance, ledger = _owners(root)
    _quarantine(root, registry, maintenance, ledger)
    quarantine = root / ".quarantine" / "repo-map_dev" / "run1"
    quarantine_identity = quarantine.stat().st_ino
    destination = root / "r" / "run1"
    collision_identity: list[int] = []

    def race():
        destination.mkdir(mode=0o700)
        collision_identity.append(destination.stat().st_ino)

    with pytest.raises(QuarantineError, match="collision|already exists"):
        restore_quarantined(
            root,
            registry,
            maintenance,
            ledger,
            "run1",
            now_seconds=NOW + 1,
            before_rename=race,
        )

    assert quarantine.stat().st_ino == quarantine_identity
    assert destination.stat().st_ino == collision_identity[0]
    assert not any(record.event == "restore_completion" for record in ledger.records())


def test_r15_atomic_helper_success_collision_and_unsupported(tmp_path: Path, monkeypatch):
    subject = resource_atomic_rename_owner
    root = _root(tmp_path)
    source = root / "r" / "source"
    destination = root / "r" / "destination"
    source.mkdir(mode=0o700)
    source_inode = source.stat().st_ino

    result = subject.atomic_rename_no_replace(source, destination)
    assert result.destination_inode == source_inode
    assert destination.is_dir() and not source.exists()

    second = root / "r" / "second"
    second.mkdir(mode=0o700)
    second_inode = second.stat().st_ino
    platform_calls: list[tuple[Path, Path]] = []
    platform_rename = subject._platform_rename_no_replace

    def observed_platform_rename(source: Path, destination: Path):
        platform_calls.append((source, destination))
        return platform_rename(source, destination)

    monkeypatch.setattr(subject, "_platform_rename_no_replace", observed_platform_rename)
    with pytest.raises(subject.AtomicRenameCollision):
        subject.atomic_rename_no_replace(second, destination)
    assert platform_calls == [(second, destination)]
    assert second.stat().st_ino == second_inode
    assert destination.stat().st_ino == source_inode

    unsupported_source = root / "r" / "unsupported"
    unsupported_destination = root / "r" / "unsupported-destination"
    unsupported_source.mkdir(mode=0o700)
    monkeypatch.setattr(
        subject,
        "_platform_rename_no_replace",
        lambda source, destination: (_ for _ in ()).throw(
            subject.AtomicRenameUnavailable("injected unsupported platform")
        ),
    )
    with pytest.raises(subject.AtomicRenameUnavailable):
        subject.atomic_rename_no_replace(
            unsupported_source, unsupported_destination
        )
    assert unsupported_source.is_dir() and not unsupported_destination.exists()


def test_restore_accepts_existing_managed_root_with_default_public_mode(tmp_path: Path):
    root = _root(tmp_path)
    (root / "r").chmod(0o755)
    _run(root)
    registry, maintenance, ledger = _owners(root)
    _quarantine(root, registry, maintenance, ledger)

    restored = restore_quarantined(
        root,
        registry,
        maintenance,
        ledger,
        "run1",
        now_seconds=NOW + 1,
    )

    assert restored.is_dir()
    assert not ledger.quarantine_record_path("run1").exists()


def test_r15_cross_filesystem_is_refused_before_mutation(tmp_path: Path, monkeypatch):
    subject = resource_atomic_rename_owner
    root = _root(tmp_path)
    source = root / "r" / "source"
    destination = root / "r" / "destination"
    source.mkdir(mode=0o700)
    actual_identity = subject._path_identity

    def different_device(path: Path):
        identity = actual_identity(path)
        if Path(path) == destination.parent:
            return identity._replace(device=identity.device + 1)
        return identity

    monkeypatch.setattr(subject, "_path_identity", different_device)
    with pytest.raises(subject.AtomicRenameError, match="cross filesystems"):
        subject.atomic_rename_no_replace(source, destination)
    assert source.is_dir() and not destination.exists()
