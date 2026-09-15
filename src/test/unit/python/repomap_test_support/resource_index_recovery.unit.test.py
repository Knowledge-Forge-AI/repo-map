"""TEST-HYGIENE-MAINT1 recovery binding, inventory, and CLI contracts."""

from __future__ import annotations

import json
from pathlib import Path

from typing import cast

import pytest

import test_hygiene_maintenance as maintenance_tool
from repomap_test_support.resource_hygiene_policy import GIB, HygieneProfile
from repomap_test_support.resource_index import AdvisoryIndex, HostAdmissionRefused
from repomap_test_support.resource_index_maintenance import (
    rebuild_inventory,
)
from repomap_test_support.resource_ledger import ResourceLedger, RunIdentity
from repomap_test_support.resource_ledger_io import (
    read_private_json,
    write_private_json,
    write_private_json_exclusive,
)
from repomap_test_support.resource_lifecycle_claim import ClaimRegistry, MaintenanceHandle
from repomap_test_support import resource_index_recovery as recovery_owner


OWNER = "b" * 32


def _private_root(tmp_path: Path) -> Path:
    tmp_path.chmod(0o700)
    return tmp_path


def _invalid_index(tmp_path: Path, summary: dict | None = None) -> Path:
    root = _private_root(tmp_path)
    index_root = root / ".index" / "repo-map_dev"
    records = index_root / "runs"
    records.mkdir(mode=0o700, parents=True)
    (root / ".index").chmod(0o700)
    index_root.chmod(0o700)
    if summary is not None:
        write_private_json_exclusive(index_root / "summary.json", summary)
    return index_root


def _valid_index(tmp_path: Path) -> AdvisoryIndex:
    root = _private_root(tmp_path)
    return AdvisoryIndex.initialize_empty(
        root / ".index" / "repo-map_dev",
        scratch_root=root,
        requesting_run_id=None,
        initialized_at_seconds=1,
    )


def _maintenance(tmp_path: Path, purpose: str = "recover-index"):
    registry = ClaimRegistry(tmp_path)
    handle = registry.acquire_maintenance(purpose, now_seconds=10)
    return registry, handle


def _legacy_summary() -> dict[str, object]:
    return {
        "schema": "repomap-test-hygiene-index-summary-v1",
        "generation": 4,
        "allocated_bytes": 0,
        "inode_count": 0,
    }


def _synthetic_run(root: Path, run_id: str, *, valid: bool) -> Path:
    run = root / "r" / run_id
    run.mkdir(mode=0o700, parents=True)
    (run / "payload.bin").write_bytes(b"bounded-payload")
    if not valid:
        manifest_path = run / "manifest.json"
        manifest_path.write_text("{}\n", encoding="utf-8")
        manifest_path.chmod(0o600)
        return run
    manifest = {
        "schema": "repomap-test-scratch-manifest-v1",
        "project": "repo-map_dev",
        "phase": "TEST-HYGIENE-MAINT1",
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
    manifest_path = run / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_path.chmod(0o600)
    ledger = ResourceLedger.create(
        run / "resource-ledger.json",
        RunIdentity("repo-map_dev", "TEST-HYGIENE-MAINT1", run_id),
        now_seconds=1,
    )
    ledger.stamp_terminal("passed", 2)
    return run


def _bind(tmp_path: Path):
    recovery = recovery_owner
    registry, maintenance = _maintenance(tmp_path)
    binding = recovery.MaintenanceIndexBinding.bind(
        tmp_path, registry, maintenance
    )
    return recovery, registry, maintenance, binding


def test_r1_inventory_command_cannot_repair_invalid_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _invalid_index(tmp_path, _legacy_summary())
    monkeypatch.setenv("REPOMAP_TEST_SCRATCH_ROOT", str(tmp_path))

    with pytest.raises(HostAdmissionRefused, match="index summary is invalid"):
        maintenance_tool.main(["inventory"])


def test_r2_rebuild_inventory_requires_invalid_summary(tmp_path: Path) -> None:
    index_root = _invalid_index(tmp_path, _legacy_summary())
    index = AdvisoryIndex(index_root, tmp_path)
    registry, maintenance = _maintenance(tmp_path, "inventory")

    with pytest.raises(HostAdmissionRefused, match="index summary is invalid"):
        rebuild_inventory(
            index,
            registry,
            maintenance,
            now_seconds=20,
            operator_requested=True,
        )


def test_r3_missing_summary_real_inventory_command_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _invalid_index(tmp_path)
    monkeypatch.setenv("REPOMAP_TEST_SCRATCH_ROOT", str(tmp_path))

    with pytest.raises(HostAdmissionRefused, match="index summary is invalid"):
        maintenance_tool.main(["inventory"])


def test_r4_provenance_mismatch_cannot_be_rebuilt_by_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index = _valid_index(tmp_path)
    summary = read_private_json(index.summary_path)
    summary["provenance_record_id"] = "0" * 64
    write_private_json(index.summary_path, summary)
    monkeypatch.setenv("REPOMAP_TEST_SCRATCH_ROOT", str(tmp_path))

    with pytest.raises(HostAdmissionRefused, match="index summary is invalid"):
        maintenance_tool.main(["inventory"])


def test_r5_ambiguous_physical_root_contributes_bytes_and_inodes(
    tmp_path: Path,
) -> None:
    index = _valid_index(tmp_path)
    _synthetic_run(tmp_path, "ambiguous", valid=False)
    registry, maintenance = _maintenance(tmp_path, "inventory")

    result = rebuild_inventory(
        index,
        registry,
        maintenance,
        now_seconds=20,
        operator_requested=True,
    )

    assert result.ambiguous_count == 1
    assert result.allocated_bytes > 0
    assert result.inode_count >= 3
    reopened = AdvisoryIndex.open(index.root, scratch_root=tmp_path).reconcile()
    assert reopened.allocated_bytes == result.allocated_bytes
    assert reopened.inode_count == result.inode_count


def test_r6_immediate_symlink_refuses_without_new_summary(tmp_path: Path) -> None:
    _invalid_index(tmp_path, _legacy_summary())
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    runs = tmp_path / "r"
    runs.mkdir(mode=0o700)
    (runs / "linked").symlink_to(outside, target_is_directory=True)
    original = (tmp_path / ".index/repo-map_dev/summary.json").read_bytes()
    recovery, registry, maintenance, binding = _bind(tmp_path)

    with pytest.raises(recovery.IndexRecoveryError, match="unsafe"):
        recovery.recover_index(
            binding, registry, maintenance, now_seconds=20
        )

    assert (tmp_path / ".index/repo-map_dev/summary.json").read_bytes() == original


def test_r7_ordinary_open_remains_fail_closed_before_recovery(tmp_path: Path) -> None:
    index_root = _invalid_index(tmp_path, _legacy_summary())
    with pytest.raises(HostAdmissionRefused, match="maintenance_required"):
        AdvisoryIndex.open(index_root, scratch_root=tmp_path)


def test_r8_binding_requires_exact_maintenance_handle(tmp_path: Path) -> None:
    def _invalid_maintenance_handle() -> MaintenanceHandle:
        """Narrow runtime-invalid MaintenanceHandle builder for negative controls."""
        return cast(MaintenanceHandle, object())

    _invalid_index(tmp_path, _legacy_summary())
    recovery = recovery_owner
    registry = ClaimRegistry(tmp_path)

    with pytest.raises(Exception, match="maintenance"):
        recovery.MaintenanceIndexBinding.bind(
            tmp_path, registry, _invalid_maintenance_handle()
        )


@pytest.mark.parametrize(
    "mutation",
    ["wrong_project", "symlink_index", "symlink_records", "unsafe_mode"],
)
def test_r9_binding_refuses_path_and_authority_mismatch(
    tmp_path: Path, mutation: str
) -> None:
    index_root = _invalid_index(tmp_path, _legacy_summary())
    recovery = recovery_owner
    registry, maintenance = _maintenance(tmp_path)
    if mutation == "wrong_project":
        other = ClaimRegistry(tmp_path, "other")
        other_handle = other.acquire_maintenance("recover-index", now_seconds=11)
        with pytest.raises(Exception):
            recovery.MaintenanceIndexBinding.bind(
                tmp_path, other, other_handle
            )
        return
    if mutation == "unsafe_mode":
        index_root.chmod(0o755)
    else:
        target = tmp_path / ("index-target" if mutation == "symlink_index" else "runs-target")
        selected = index_root if mutation == "symlink_index" else index_root / "runs"
        if mutation == "symlink_index":
            selected.rename(target)
        else:
            selected.rmdir()
            target.mkdir(mode=0o700)
        selected.symlink_to(target, target_is_directory=True)

    with pytest.raises(Exception):
        recovery.MaintenanceIndexBinding.bind(tmp_path, registry, maintenance)


def test_r11_recovery_audit_binds_old_authority_without_paths_or_content(
    tmp_path: Path,
) -> None:
    index_root = _invalid_index(tmp_path, _legacy_summary())
    old_summary_inode = index_root.joinpath("summary.json").lstat().st_ino
    _synthetic_run(tmp_path, "ambiguous", valid=False)
    recovery, registry, maintenance, binding = _bind(tmp_path)

    result = recovery.recover_index(
        binding, registry, maintenance, now_seconds=20
    )
    audit = read_private_json(result.recovery_intent_path)
    encoded = json.dumps(audit, sort_keys=True)

    assert audit["summary_sha256"]
    assert audit["summary_inode"] == old_summary_inode
    assert str(tmp_path) not in encoded
    assert "allocated_bytes" not in audit
    with pytest.raises(FileExistsError):
        write_private_json_exclusive(result.recovery_intent_path, audit)


@pytest.mark.parametrize(
    ("summary", "basis", "generation"),
    [
        (_legacy_summary(), "preserved_increment", 5),
        (None, "recovery_epoch", 0),
        ({"schema": "broken", "generation": "bad"}, "recovery_epoch", 0),
    ],
)
def test_r12_generation_rule_is_explicit(
    tmp_path: Path,
    summary: dict[str, object] | None,
    basis: str,
    generation: int,
) -> None:
    _invalid_index(tmp_path, summary)
    _synthetic_run(tmp_path, "ambiguous", valid=False)
    recovery, registry, maintenance, binding = _bind(tmp_path)

    result = recovery.recover_index(
        binding, registry, maintenance, now_seconds=20
    )

    assert result.generation_basis == basis
    assert result.generation == generation
    assert AdvisoryIndex.open(
        tmp_path / ".index/repo-map_dev", scratch_root=tmp_path
    ).reconcile().generation == generation


def test_r12_repeated_recovery_increments_without_reset(tmp_path: Path) -> None:
    _invalid_index(tmp_path, _legacy_summary())
    _synthetic_run(tmp_path, "ambiguous", valid=False)
    recovery, registry, maintenance, binding = _bind(tmp_path)
    first = recovery.recover_index(
        binding, registry, maintenance, now_seconds=20
    )
    registry.release_maintenance(maintenance)
    second_handle = registry.acquire_maintenance("recover-index", now_seconds=21)
    second_binding = recovery.MaintenanceIndexBinding.bind(
        tmp_path, registry, second_handle
    )

    second = recovery.recover_index(
        second_binding, registry, second_handle, now_seconds=21
    )

    assert second.generation == first.generation + 1
    assert second.generation_basis == "preserved_increment"
    assert second.prior_generation == first.generation
    assert second.allocated_bytes == first.allocated_bytes
    assert second.recovery_intent_path != first.recovery_intent_path


def test_r19_real_cli_recovery_is_counts_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _invalid_index(tmp_path, _legacy_summary())
    _synthetic_run(tmp_path, "ambiguous", valid=False)
    monkeypatch.setenv("REPOMAP_TEST_SCRATCH_ROOT", str(tmp_path))

    assert maintenance_tool.main(["recover-index"]) == 0
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert set(payload) == {
        "ambiguous_runs",
        "allocated_bytes",
        "generation",
        "inode_count",
        "index_parent_hardening_count",
        "index_parent_mode_action",
        "internal_unsafe_links",
        "records_remaining",
        "run_roots",
        "terminal_pairs_reconciled",
        "valid_runs",
    }
    assert str(tmp_path) not in output
    assert AdvisoryIndex.open(
        tmp_path / ".index/repo-map_dev", scratch_root=tmp_path
    ).reconcile().allocated_bytes > 0


def test_r20_recovery_cli_requires_explicit_root_and_has_no_path_argument(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("REPOMAP_TEST_SCRATCH_ROOT", raising=False)
    assert maintenance_tool.main(["recover-index"]) == 2
    assert "explicit_scratch_root_required" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        maintenance_tool.parser().parse_args(["recover-index", "/tmp/other"])

    help_text = maintenance_tool.parser().format_help()
    assert not any(word in help_text for word in ("prune", "physical-delete"))
    assert "operator-reclaim" in help_text


def test_recovery_profile_headroom_is_reported_without_general_admission_claim(
    tmp_path: Path,
) -> None:
    _invalid_index(tmp_path, _legacy_summary())
    _synthetic_run(tmp_path, "ambiguous", valid=False)
    recovery, registry, maintenance, binding = _bind(tmp_path)
    recovery.recover_index(binding, registry, maintenance, now_seconds=20)

    headroom = recovery.profile_headroom(
        AdvisoryIndex.open(
            tmp_path / ".index/repo-map_dev", scratch_root=tmp_path
        ).reconcile(),
        soft_watermark_bytes=40 * GIB,
        soft_watermark_inodes=1_500_000,
        hard_watermark_bytes=80 * GIB,
        hard_watermark_inodes=3_000_000,
    )

    assert set(headroom) == {profile.value for profile in HygieneProfile}
    assert all("hard_admissible" in value for value in headroom.values())
