"""TEST-HYGIENE3B1 lifecycle-claim and protection-writer contracts."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from repomap_test_support.resource_lifecycle_claim import (
    CLAIM_LEASE_SECONDS,
    ClaimError,
    ClaimPurpose,
    ClaimRegistry,
    ProcessLiveness,
    lifecycle_claim,
    coerce_process_liveness,
    process_owner_matches,
    register_protection,
)
from repomap_test_support.resource_ledger_io import write_private_json_exclusive
from repomap_test_support.resource_run_cleanup import process_start_evidence


def _root(tmp_path: Path) -> Path:
    tmp_path.chmod(0o700)
    return tmp_path


def test_claim_schema_o_excl_and_private_modes(tmp_path: Path):
    registry = ClaimRegistry(_root(tmp_path))
    handle = registry.acquire("run1", ClaimPurpose.GC_QUARANTINE, now_seconds=1)
    payload = json.loads(handle.path.read_text())

    assert payload["schema"] == "repomap-test-lifecycle-claim-v1"
    assert payload["claim_lease_seconds"] == CLAIM_LEASE_SECONDS
    assert handle.path.stat().st_mode & 0o777 == 0o600
    assert handle.path.parent.stat().st_mode & 0o777 == 0o700
    with pytest.raises(ClaimError, match="already held"):
        registry.acquire("run1", ClaimPurpose.MONITORING_REGISTRATION, now_seconds=2)
    registry.release(handle)


def test_claim_rejects_arbitrary_purpose(tmp_path: Path):
    registry = ClaimRegistry(_root(tmp_path))
    with pytest.raises(ClaimError, match="closed vocabulary"):
        registry.acquire("run1", "delete_everything", now_seconds=1)


def test_exact_handle_release_refuses_replacement_inode(tmp_path: Path):
    registry = ClaimRegistry(_root(tmp_path))
    handle = registry.acquire("run1", ClaimPurpose.GC_QUARANTINE, now_seconds=1)
    payload = json.loads(handle.path.read_text())
    displaced = handle.path.with_suffix(".old")
    handle.path.rename(displaced)
    write_private_json_exclusive(handle.path, payload)

    with pytest.raises(ClaimError, match="ownership changed"):
        registry.release(handle)
    assert handle.path.exists()


def test_consumer_and_gc_share_one_exclusive_registry(tmp_path: Path):
    registry = ClaimRegistry(_root(tmp_path))
    gc = registry.acquire("run1", ClaimPurpose.GC_QUARANTINE, now_seconds=1)
    with pytest.raises(ClaimError, match="already held"):
        register_protection(
            tmp_path,
            "repo-map_dev",
            "run1",
            ClaimPurpose.OPERATOR_PIN_REGISTRATION,
            now_seconds=2,
        )
    registry.release(gc)


@pytest.mark.parametrize(
    "purpose",
    [
        ClaimPurpose.OPERATOR_PIN_REGISTRATION,
        ClaimPurpose.REPORT_SOURCE_REGISTRATION,
        ClaimPurpose.MONITORING_REGISTRATION,
    ],
)
def test_each_protection_writer_commits_under_claim(tmp_path: Path, purpose):
    registry = ClaimRegistry(_root(tmp_path))
    path = register_protection(
        tmp_path, "repo-map_dev", f"run-{purpose.value}", purpose, now_seconds=4
    )
    assert path.is_file()
    assert path.stat().st_mode & 0o777 == 0o600
    assert not tuple(registry.root.glob("*.claim.json"))


def test_claim_context_preserves_primary_exception(tmp_path: Path, monkeypatch):
    ClaimRegistry(_root(tmp_path))

    def fail_release(handle):
        raise ClaimError("injected release failure")

    monkeypatch.setattr(ClaimRegistry, "release", lambda self, handle: fail_release(handle))
    with pytest.raises(RuntimeError, match="primary") as raised:
        with lifecycle_claim(
            tmp_path, "repo-map_dev", "run1", ClaimPurpose.REPORT_SOURCE_REGISTRATION
        ):
            raise RuntimeError("primary")
    assert "release also failed" in "\n".join(raised.value.__notes__)


def test_current_process_start_evidence_rejects_pid_reuse():
    assert process_owner_matches(
        os.getpid(), process_start_evidence()
    ) is ProcessLiveness.LIVE
    assert process_owner_matches(os.getpid(), "f" * 64) is ProcessLiveness.DEAD


@pytest.mark.parametrize("age", [CLAIM_LEASE_SECONDS - 1, CLAIM_LEASE_SECONDS])
def test_stale_claim_recovery_lease_boundary(tmp_path: Path, age: int):
    registry = ClaimRegistry(_root(tmp_path))
    registry.acquire(
        "run1",
        ClaimPurpose.GC_QUARANTINE,
        now_seconds=10,
        process_id=999_999,
        process_start="a" * 64,
    )
    maintenance = registry.acquire_maintenance("recover", now_seconds=20)
    tombstone = tmp_path / ".gc" / "repo-map_dev" / "pass" / "tombstones" / "claim-run1.json"
    if age < CLAIM_LEASE_SECONDS:
        with pytest.raises(ClaimError, match="has not expired"):
            registry.recover_stale_claim(
                maintenance,
                "run1",
                now_seconds=10 + age,
                tombstone_path=tombstone,
                owner_is_live=lambda pid, start: False,
            )
    else:
        assert registry.recover_stale_claim(
            maintenance,
            "run1",
            now_seconds=10 + age,
            tombstone_path=tombstone,
            owner_is_live=lambda pid, start: False,
        ) == tombstone
        assert tombstone.is_file()
        assert not (registry.root / "run1.claim.json").exists()
    registry.release_maintenance(maintenance)


def test_live_or_start_matching_claim_cannot_be_recovered(tmp_path: Path):
    registry = ClaimRegistry(_root(tmp_path))
    registry.acquire(
        "run1",
        ClaimPurpose.GC_QUARANTINE,
        now_seconds=1,
        process_id=os.getpid(),
        process_start=process_start_evidence(),
    )
    maintenance = registry.acquire_maintenance("recover", now_seconds=2)
    with pytest.raises(ClaimError, match="still live"):
        registry.recover_stale_claim(
            maintenance,
            "run1",
            now_seconds=1 + CLAIM_LEASE_SECONDS,
            tombstone_path=tmp_path / ".gc" / "repo-map_dev" / "p" / "t.json",
        )


def test_global_maintenance_lock_serializes_and_has_no_self_recovery(tmp_path: Path):
    registry = ClaimRegistry(_root(tmp_path))
    handle = registry.acquire_maintenance("compact", now_seconds=1)
    with pytest.raises(ClaimError, match="already held"):
        registry.acquire_maintenance("inventory", now_seconds=2)
    assert not hasattr(registry, "recover_maintenance_lock")
    registry.release_maintenance(handle)


@pytest.mark.parametrize("value", [None, 0, 1, "", "dead", object()])
def test_unknown_liveness_inputs_never_authorize_deletion(value: object) -> None:
    assert coerce_process_liveness(value) is ProcessLiveness.UNKNOWN


@pytest.mark.parametrize("value, expected", [(True, ProcessLiveness.LIVE), (False, ProcessLiveness.DEAD)])
def test_boolean_liveness_keeps_exact_identity(value: bool, expected: ProcessLiveness) -> None:
    assert coerce_process_liveness(value) is expected
