"""FIX3 physical-membership and ambiguous-name compatibility contracts."""

from __future__ import annotations

import hashlib as hashlib_owner

import os
import json
from pathlib import Path

import pytest

from repomap_test_support import resource_index_physical_membership as records
from repomap_test_support import resource_index_recovery as recovery
from repomap_test_support.resource_index import AdvisoryIndex
from repomap_test_support.resource_index_bootstrap import filesystem_identity
from repomap_test_support.resource_index_maintenance import _snapshot_entries
from repomap_test_support.resource_index_records import (
    ADMISSION_SCHEMA,
    CLOSE_SCHEMA,
    INVENTORY_MEMBERSHIP_SCHEMA,
    RECOVERY_INVENTORY_MEMBERSHIP_SCHEMA,
    validate_inventory_membership,
    validate_recovery_inventory_membership,
)
from repomap_test_support.resource_index_recovery_records import (
    IndexRecoveryError,
    plan_recovery_records,
)
from repomap_test_support.resource_ledger import ResourceLedger, RunIdentity
from repomap_test_support.resource_ledger_io import write_private_json
from repomap_test_support.resource_retention import RetentionClass, TerminalOutcome
from typing import TypedDict
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


def _write_pair(records_path: Path, run_id: str) -> None:
    write_private_json(
        records_path / f"{run_id}.admitted.json",
        {
            "schema": ADMISSION_SCHEMA,
            "run_id": run_id,
            "phase": "TEST-HYGIENE-MAINT1-FIX3",
            "profile": "ordinary",
            "byte_quota": 1,
            "inode_quota": 1,
            "process_id": 1,
            "process_start_evidence": "a" * 64,
            "owner_token": "b" * 32,
            "configuration_sha256": "c" * 64,
            "admitted_at_seconds": 1,
        },
    )
    write_private_json(
        records_path / f"{run_id}.closed.json",
        {
            "schema": CLOSE_SCHEMA,
            "run_id": run_id,
            "phase": "TEST-HYGIENE-MAINT1-FIX3",
            "terminal_outcome": TerminalOutcome.PASSED.value,
            "retention_class": RetentionClass.SUCCESSFUL_EVIDENCE.value,
            "allocated_bytes": 1,
            "inode_count": 1,
            "retained_evidence_bytes": 1,
            "closed_at_seconds": 2,
        },
    )


def test_d1_safe_invalid_name_is_measured_as_ambiguous(tmp_path: Path) -> None:
    root = _private_root(tmp_path)
    entry = root / "r" / "historical entry"
    entry.mkdir(mode=0o700)
    (entry / "payload").write_bytes(b"physical")

    scan = recovery.scan_run_population(root, "repo-map_dev")

    assert scan.entry_count == 1
    assert scan.valid_run_count == 0
    assert scan.ambiguous_run_count == 1
    assert scan.allocated_bytes > 0
    assert scan.inode_count == 2
    assert scan.measured_names == frozenset()
    assert scan.identities[0][1] is None


def test_d2_new_schema_represents_null_run_id_without_fake_name() -> None:
    schema = records.PHYSICAL_INVENTORY_SCHEMA
    validator = records.validate_physical_inventory
    entry_key = hashlib_owner.sha256(
        b"repomap-physical-entry-v1\0" + os.fsencode("historical entry")
    ).hexdigest()

    assert schema == "repomap-test-hygiene-index-inventory-v3"
    payload = validator(
        {
            "schema": schema,
            "scratch_filesystem_id": "a" * 64,
            "initialization_mode": "maintenance_inventory",
            "inventory_at_seconds": 1,
            "allocated_bytes": 1,
            "inode_count": 1,
            "measured_physical_entries": [
                {
                    "entry_key": entry_key,
                    "valid_run_id": None,
                    "device": 1,
                    "inode": 2,
                }
            ],
            "provenance_record_id": "b" * 64,
        }
    )
    assert payload["measured_physical_entries"][0]["valid_run_id"] is None


def test_d3_regular_file_is_measured_before_name_classification(
    tmp_path: Path,
) -> None:
    root = _private_root(tmp_path)
    entry = root / "r" / "historical entry"
    entry.write_bytes(b"physical-file")

    scan = recovery.scan_run_population(root, "repo-map_dev")

    assert scan.entry_count == scan.ambiguous_run_count == 1
    assert scan.valid_run_count == 0
    assert scan.inode_count == 1
    assert scan.allocated_bytes > 0
    assert scan.identities[0][1] is None


def test_d3_valid_name_regular_file_is_not_record_cleanup_authority(
    tmp_path: Path,
) -> None:
    root = _private_root(tmp_path)
    (root / "r/apparent-run").write_bytes(b"physical-file")
    scan = recovery.scan_run_population(root, "repo-map_dev")

    assert scan.measured_names == frozenset()
    assert scan.valid_run_count == 0
    assert scan.ambiguous_run_count == 1
    assert scan.identities[0][1] == "apparent-run"
    records_path = tmp_path / "records"
    records_path.mkdir()
    _write_pair(records_path, "apparent-run")
    with pytest.raises(IndexRecoveryError, match="not redundant"):
        plan_recovery_records(records_path, scan.measured_names)


def test_d4_valid_run_keeps_exact_name_and_managed_classification(
    tmp_path: Path,
) -> None:
    root = _private_root(tmp_path)
    run = _valid_run(root, "managed-run")

    scan = recovery.scan_run_population(root, "repo-map_dev")

    assert scan.valid_run_count == 1
    assert scan.ambiguous_run_count == 0
    assert scan.measured_names == frozenset({"managed-run"})
    assert scan.identities == (
        (
            records.physical_entry_key("managed-run"),
            "managed-run",
            run.stat().st_dev,
            run.stat().st_ino,
        ),
    )


def test_d5_null_member_cannot_make_record_pair_redundant(
    tmp_path: Path,
) -> None:
    records_path = tmp_path / "records"
    records_path.mkdir()
    _write_pair(records_path, "managed-run")

    with pytest.raises(IndexRecoveryError, match="not redundant"):
        plan_recovery_records(records_path, frozenset())


def test_d6_d7_snapshot_projection_excludes_null_and_keeps_valid(
    tmp_path: Path,
) -> None:
    root = _private_root(tmp_path)
    index_root = root / ".index/repo-map_dev"
    (index_root / "runs").mkdir(mode=0o700, parents=True)
    (root / ".index").chmod(0o700)
    index_root.chmod(0o700)
    valid = root / "r/managed-run"
    valid.mkdir(mode=0o700)
    invalid = root / "r/historical entry"
    invalid.mkdir(mode=0o700)
    entry_list: list[PhysicalEntryDict] = [
        {
            "entry_key": records.physical_entry_key(invalid.name),
            "valid_run_id": None,
            "device": invalid.stat().st_dev,
            "inode": invalid.stat().st_ino,
        },
        {
            "entry_key": records.physical_entry_key(valid.name),
            "valid_run_id": valid.name,
            "device": valid.stat().st_dev,
            "inode": valid.stat().st_ino,
        },
    ]
    entries = sorted(entry_list, key=lambda item: item["entry_key"])
    write_private_json(
        index_root / "inventory.json",
        {
            "schema": records.PHYSICAL_INVENTORY_SCHEMA,
            "scratch_filesystem_id": filesystem_identity(root),
            "initialization_mode": "maintenance_inventory",
            "inventory_at_seconds": 3,
            "allocated_bytes": 0,
            "inode_count": 0,
            "measured_physical_entries": entries,
            "provenance_record_id": "d" * 64,
        },
    )
    projected = _snapshot_entries(
        AdvisoryIndex(index_root, root), {"inventory_at_seconds": 3}
    )

    assert projected == {
        "managed-run": (valid.stat().st_dev, valid.stat().st_ino)
    }


def test_d8_old_and_new_membership_schemas_remain_strictly_readable() -> None:
    old = {
        "schema": INVENTORY_MEMBERSHIP_SCHEMA,
        "scratch_filesystem_id": "a" * 64,
        "initialization_mode": "maintenance_inventory",
        "inventory_at_seconds": 1,
        "allocated_bytes": 1,
        "inode_count": 1,
        "measured_run_entries": [{"run_id": "run", "device": 1, "inode": 1}],
        "provenance_record_id": "b" * 64,
    }
    recovery_old = {
        **old,
        "schema": RECOVERY_INVENTORY_MEMBERSHIP_SCHEMA,
        "population_entry_count": 1,
        "valid_run_count": 1,
        "ambiguous_run_count": 0,
        "internal_unsafe_link_count": 0,
        "recovery_record_id": "c" * 64,
        "generation_basis": "recovery_epoch",
        "prior_generation": None,
    }
    assert validate_inventory_membership(old) == old
    assert validate_recovery_inventory_membership(recovery_old) == recovery_old
    with pytest.raises(HygieneValidationError, match="run id"):
        validate_inventory_membership(
            {**old, "measured_run_entries": [{"run_id": "bad name", "device": 1, "inode": 1}]}
        )


def test_d9_symlink_refuses_whole_inventory(tmp_path: Path) -> None:
    root = _private_root(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "r/linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(IndexRecoveryError, match="unsafe"):
        recovery.scan_run_population(root, "repo-map_dev")
