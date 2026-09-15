"""TEST-HYGIENE3B1-FIX1 closed process-liveness authority contracts."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import psutil
import pytest

import test_hygiene_maintenance as maintenance_tool
from repomap_test_support.resource_gc_ledger import GcLedger
from repomap_test_support.resource_index import AdvisoryIndex
from repomap_test_support.resource_index_maintenance import (
    IndexMaintenanceError,
    recover_stale_admission_lock,
)
from repomap_test_support.resource_lifecycle_claim import (
    CLAIM_LEASE_SECONDS,
    ClaimError,
    ClaimPurpose,
    ClaimRegistry,
    process_owner_matches,
)


def _name(result: object) -> str:
    value = getattr(result, "value", result)
    return str(value).lower()


def _root(tmp_path: Path) -> Path:
    tmp_path.chmod(0o700)
    return tmp_path


@pytest.mark.parametrize("error", [PermissionError(), OSError("transient")])
def test_r8_os_kill_ambiguity_is_unknown(monkeypatch, error: OSError):
    monkeypatch.setattr(os, "kill", lambda pid, signal: (_ for _ in ()).throw(error))

    assert _name(process_owner_matches(123, "a" * 64)) == "unknown"
    assert _name(maintenance_tool._process_is_live(123)) == "unknown"


def test_r8_psutil_access_denial_is_unknown(monkeypatch):
    monkeypatch.setattr(os, "kill", lambda pid, signal: None)
    monkeypatch.setattr(
        psutil,
        "Process",
        lambda pid: (_ for _ in ()).throw(psutil.AccessDenied(pid=pid)),
    )

    assert _name(process_owner_matches(123, "a" * 64)) == "unknown"


def test_r8_process_start_read_denial_is_unknown(monkeypatch):
    class DeniedProcess:
        def create_time(self):
            raise PermissionError("denied")

    monkeypatch.setattr(os, "kill", lambda pid, signal: None)
    monkeypatch.setattr(psutil, "Process", lambda pid: DeniedProcess())

    assert _name(process_owner_matches(123, "a" * 64)) == "unknown"


def test_r8_unknown_liveness_does_not_recover_stale_claim(monkeypatch, tmp_path: Path):
    root = _root(tmp_path)
    registry = ClaimRegistry(root)
    claim = registry.acquire(
        "run1",
        ClaimPurpose.GC_QUARANTINE,
        now_seconds=1,
        process_id=123,
        process_start="a" * 64,
    )
    maintenance = registry.acquire_maintenance("recover", now_seconds=2)
    monkeypatch.setattr(
        os,
        "kill",
        lambda pid, signal: (_ for _ in ()).throw(PermissionError()),
    )

    with pytest.raises(ClaimError, match="unknown|not provably dead"):
        registry.recover_stale_claim(
            maintenance,
            "run1",
            now_seconds=1 + CLAIM_LEASE_SECONDS,
            tombstone_path=root / ".gc" / "repo-map_dev" / "p" / "claim.json",
        )

    assert claim.path.is_file()


def test_r8_unknown_liveness_does_not_recover_stale_admission_lock(
    monkeypatch, tmp_path: Path
):
    root = _root(tmp_path)
    index = AdvisoryIndex.initialize_empty(
        root / ".index" / "repo-map_dev",
        scratch_root=root,
        requesting_run_id=None,
        initialized_at_seconds=0,
    )
    index._acquire_lock(1, owner_token="a" * 32)
    registry = ClaimRegistry(root)
    maintenance = registry.acquire_maintenance("recover", now_seconds=2)
    ledger = GcLedger.create(
        root,
        project="repo-map_dev",
        pass_id="p",
        trigger="operator_requested",
        configuration_digest="d" * 64,
        maintenance_owner_token=maintenance.owner_token,
        now_seconds=2,
    )
    monkeypatch.setattr(
        os,
        "kill",
        lambda pid, signal: (_ for _ in ()).throw(PermissionError()),
    )

    with pytest.raises(IndexMaintenanceError, match="unknown|not provably dead"):
        recover_stale_admission_lock(
            index,
            registry,
            maintenance,
            ledger,
            now_seconds=1 + CLAIM_LEASE_SECONDS,
        )

    assert index.lock_path.is_file()


def test_r9_exact_process_lookup_error_proves_dead(monkeypatch):
    monkeypatch.setattr(
        os,
        "kill",
        lambda pid, signal: (_ for _ in ()).throw(ProcessLookupError()),
    )

    assert _name(process_owner_matches(123, "a" * 64)) == "dead"
    assert _name(maintenance_tool._process_is_live(123)) == "dead"


def test_r9_process_start_match_is_live_and_mismatch_is_dead(monkeypatch):
    started = 1234.5

    class ExactProcess:
        def create_time(self):
            return started

    monkeypatch.setattr(os, "kill", lambda pid, signal: None)
    monkeypatch.setattr(psutil, "Process", lambda pid: ExactProcess())
    expected = hashlib.sha256(
        f"repomap-process-start-v1\0{123}\0{started:.6f}".encode()
    ).hexdigest()

    assert _name(process_owner_matches(123, expected)) == "live"
    assert _name(process_owner_matches(123, "a" * 64)) == "dead"
