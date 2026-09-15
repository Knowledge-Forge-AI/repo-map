"""FIX3 physical boundary and noncanonical member rejection tests."""

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import TypedDict

import pytest

from repomap_test_support import resource_index_physical_membership as records
from repomap_test_support import resource_index_recovery as recovery
from repomap_test_support.resource_index_recovery_records import IndexRecoveryError
from repomap_test_support.resource_ledger import ResourceLedger, RunIdentity
from repomap_test_support.resource_scratch import ScratchAccountingError, measure_scratch
from repomap_test_support.resource_validation import HygieneValidationError


class PhysicalEntryDict(TypedDict):
    entry_key: str
    valid_run_id: str | None
    device: int | bool
    inode: int


def _private_root(tmp_path: Path) -> Path:
    tmp_path.chmod(0o700)
    (tmp_path / "r").mkdir(mode=0o700)
    return tmp_path


def _valid_run(root: Path, run_id: str) -> Path:
    run = root / "r" / run_id
    run.mkdir(mode=0o700, exist_ok=True)
    manifest = {
        "schema": "repomap-test-scratch-manifest-v1",
        "project": "repo-map_dev",
        "phase": "TEST-HYGIENE-MAINT1-FIX3",
        "run_kind": "test",
        "run_id": run_id,
        "pid": 999_999,
        "physical_run_root": str(run),
        "monitoring_index_path": str(root / "monitoring" / run_id),
        "state": "passed",
        "retention_policy": "operator_review",
        "exit_status": 0,
        "live_runtime_residue": False,
    }
    manifest_path = run / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_path.chmod(0o600)
    ledger = ResourceLedger.create(
        run / "resource-ledger.json",
        RunIdentity("repo-map_dev", "TEST-HYGIENE-MAINT1-FIX3", run_id),
        now_seconds=1,
    )
    ledger.stamp_terminal("passed", 2)
    return run


@pytest.mark.parametrize("boundary", ["owner", "device", "unreadable"])
def test_d10_unsafe_physical_boundaries_refuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    root = _private_root(tmp_path)
    entry = root / "r/entry"
    entry.mkdir()
    if boundary == "owner":
        current_uid = os.getuid()
        monkeypatch.setattr(recovery.os, "getuid", lambda: current_uid + 1)
        metadata = entry.lstat()
        with pytest.raises(IndexRecoveryError, match="immediate run entry"):
            recovery._measurable_immediate(
                entry,
                metadata.st_dev,
                metadata.st_ino,
                expected_device=metadata.st_dev,
            )
        return
    elif boundary == "device":
        original = recovery._measurable_immediate

        def wrong_device(path, device, inode, *, expected_device):
            return original(path, device, inode, expected_device=expected_device + 1)

        monkeypatch.setattr(recovery, "_measurable_immediate", wrong_device)
    else:
        def unreadable(*_args, **_kwargs):
            raise ScratchAccountingError("fixture unreadable")

        monkeypatch.setattr(recovery, "measure_scratch", unreadable)

    with pytest.raises(IndexRecoveryError) as observed:
        recovery.scan_run_population(root, "repo-map_dev")
    if boundary == "unreadable":
        assert observed.value.category == "physical_entry_unmeasurable"


def test_d11_casefold_aliases_refuse_before_hashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _private_root(tmp_path)
    entry = root / "r/Run"
    entry.mkdir()
    metadata = entry.lstat()
    monkeypatch.setattr(
        recovery,
        "_population_snapshot",
        lambda _root: (
            ("Run", metadata.st_dev, metadata.st_ino),
            ("run", metadata.st_dev, metadata.st_ino),
        ),
    )

    with pytest.raises(IndexRecoveryError, match="ambiguous"):
        recovery.scan_run_population(root, "repo-map_dev")


def test_d12_entry_key_is_deterministic_domain_separated_and_private() -> None:
    first = records.physical_entry_key("historical entry")
    second = records.physical_entry_key("historical entry")

    assert first == second
    assert first == "1b7c7295756b32ee28a1ed43c7535e1a41b23721af78455e28459613c5cc52fe"
    assert len(first) == 64 and first == first.lower()
    assert "/" not in first and "historical entry" not in first
    assert first != records.physical_entry_key("different entry")


def test_d13_population_and_aggregate_reconcile_for_mixed_entries(
    tmp_path: Path,
) -> None:
    root = _private_root(tmp_path)
    valid = _valid_run(root, "managed")
    invalid_name = root / "r/historical entry"
    invalid_name.mkdir()
    malformed = root / "r/malformed"
    malformed.mkdir()
    (malformed / "manifest.json").write_text("{}", encoding="utf-8")
    physical = [
        measure_scratch(item, reject_unsafe_links=False)
        for item in (valid, invalid_name, malformed)
    ]

    scan = recovery.scan_run_population(root, "repo-map_dev")

    assert scan.entry_count == len(scan.identities) == 3
    assert scan.valid_run_count == 1
    assert scan.ambiguous_run_count == 2
    assert scan.valid_run_count + scan.ambiguous_run_count == scan.entry_count
    assert scan.allocated_bytes == sum(item.allocated_bytes for item in physical)
    assert scan.inode_count == sum(item.inode_count for item in physical)
    assert len([item for item in scan.identities if item[1] is not None]) == 2


def test_d14_replacement_during_measurement_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _private_root(tmp_path)
    entry = root / "r/entry"
    entry.mkdir()
    original_measure = recovery.measure_scratch

    def replacing(path: Path, *, reject_unsafe_links: bool):
        measured = original_measure(path, reject_unsafe_links=reject_unsafe_links)
        path.rename(root / "r/replaced")
        path.mkdir()
        return measured

    monkeypatch.setattr(recovery, "measure_scratch", replacing)
    with pytest.raises(recovery.SharedStateChanged):
        recovery.scan_run_population(root, "repo-map_dev")


def test_d16_null_member_schema_rejects_mutation_authority_fields() -> None:
    entry = {
        "entry_key": records.physical_entry_key("historical entry"),
        "valid_run_id": None,
        "device": 1,
        "inode": 1,
    }
    forbidden = {
        "quarantine", "delete", "restore", "rename", "admit", "close",
        "claim", "protection",
    }
    base = {
        "schema": records.PHYSICAL_INVENTORY_SCHEMA,
        "scratch_filesystem_id": "a" * 64,
        "initialization_mode": "maintenance_inventory",
        "inventory_at_seconds": 1,
        "allocated_bytes": 1,
        "inode_count": 1,
        "provenance_record_id": "b" * 64,
    }
    for field in forbidden:
        with pytest.raises(HygieneValidationError, match="object keys"):
            records.validate_physical_inventory(
                {**base, "measured_physical_entries": [{**entry, field: True}]}
            )


@pytest.mark.parametrize(
    "mutation",
    ["boolean_device", "duplicate_key", "unsorted", "mismatched_valid_key"],
)
def test_fix3_physical_schema_rejects_noncanonical_members(
    mutation: str,
) -> None:
    one: PhysicalEntryDict = {
        "entry_key": records.physical_entry_key("one"),
        "valid_run_id": "one",
        "device": 1,
        "inode": 1,
    }
    two: PhysicalEntryDict = {
        "entry_key": records.physical_entry_key("two"),
        "valid_run_id": "two",
        "device": 2,
        "inode": 2,
    }
    entry_list: list[PhysicalEntryDict] = [one, two]
    entries = sorted(entry_list, key=lambda item: item["entry_key"])
    if mutation == "boolean_device":
        entries[0] = {**entries[0], "device": True}
    elif mutation == "duplicate_key":
        entries[1] = {**entries[1], "entry_key": entries[0]["entry_key"], "valid_run_id": None}
    elif mutation == "unsorted":
        entries.reverse()
    else:
        entries[0] = {**entries[0], "entry_key": "f" * 64}
    payload = {
        "schema": records.PHYSICAL_INVENTORY_SCHEMA,
        "scratch_filesystem_id": "a" * 64,
        "initialization_mode": "maintenance_inventory",
        "inventory_at_seconds": 1,
        "allocated_bytes": 1,
        "inode_count": 1,
        "measured_physical_entries": entries,
        "provenance_record_id": "b" * 64,
    }
    with pytest.raises(HygieneValidationError):
        records.validate_physical_inventory(payload)
