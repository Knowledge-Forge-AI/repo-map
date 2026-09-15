"""TEST-HYGIENE-MAINT1-FIX4 exact private-parent migration contracts."""

from __future__ import annotations

import repomap_test_support.resource_index_mode_migration as resource_index_mode_migration_owner
import repomap_test_support.resource_index_recovery as resource_index_recovery_owner

import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

import test_hygiene_maintenance as maintenance_tool
from repomap_test_support.resource_index import (
    AdvisoryIndex,
    HostAdmissionRefused,
    lifecycle_record_capacity,
)
from repomap_test_support.resource_index_recovery import MaintenanceIndexBinding
from repomap_test_support.resource_ledger_io import write_private_json_exclusive
from repomap_test_support.resource_lifecycle_claim import ClaimRegistry


def _mode():
    try:
        return resource_index_mode_migration_owner
    except ModuleNotFoundError:
        pytest.fail("FIX4 mode-migration owner is absent")


def _authority(root: Path, *, parent_mode: int = 0o755) -> Path:
    root.chmod(0o700)
    project = root / ".index/repo-map_dev"
    records = project / "runs"
    records.mkdir(mode=0o700, parents=True)
    project.chmod(0o700)
    records.chmod(0o700)
    write_private_json_exclusive(
        project / "summary.json",
        {
            "schema": "repomap-test-hygiene-index-summary-v1",
            "generation": 4,
            "allocated_bytes": 0,
            "inode_count": 0,
        },
    )
    (root / ".index").chmod(parent_mode)
    return project


def _maintenance(root: Path):
    registry = ClaimRegistry(root)
    handle = registry.acquire_maintenance("recover-index", now_seconds=10)
    return registry, handle


def _identity(path: Path) -> tuple[int, int, int, int]:
    value = path.lstat()
    return value.st_dev, value.st_ino, value.st_uid, stat.S_IMODE(value.st_mode)


def _fake(value, **changes):
    fields = {
        "st_mode": value.st_mode,
        "st_uid": value.st_uid,
        "st_dev": value.st_dev,
        "st_ino": value.st_ino,
    }
    fields.update(changes)
    return SimpleNamespace(**fields)


def test_e1_strict_bind_refuses_exact_legacy_parent(tmp_path: Path) -> None:
    _authority(tmp_path)
    registry, handle = _maintenance(tmp_path)

    with pytest.raises(Exception, match="index parent is unsafe"):
        MaintenanceIndexBinding.bind(tmp_path, registry, handle)

    assert stat.S_IMODE((tmp_path / ".index").lstat().st_mode) == 0o755


def test_e2_assessment_classifies_exact_legacy_without_mutation(
    tmp_path: Path,
) -> None:
    _authority(tmp_path)
    before = _identity(tmp_path / ".index")

    assessment = _mode().assess_index_parent_mode(tmp_path)

    assert assessment.state is _mode().IndexParentModeState.LEGACY_0755_HARDENABLE
    assert _identity(tmp_path / ".index") == before


def test_e3_private_parent_is_noop(tmp_path: Path, monkeypatch) -> None:
    _authority(tmp_path, parent_mode=0o700)
    mode = _mode()
    assessment = mode.assess_index_parent_mode(tmp_path)
    registry, handle = _maintenance(tmp_path)
    before = _identity(tmp_path / ".index")
    monkeypatch.setattr(mode.os, "fchmod", lambda *_args: pytest.fail("fchmod"))

    result = mode.harden_legacy_index_parent_mode(
        assessment, registry, handle
    )

    assert assessment.state is mode.IndexParentModeState.PRIVATE_READY
    assert result.changed_count == 0
    assert _identity(tmp_path / ".index") == before


@pytest.mark.parametrize(
    "parent_mode", [0o777, 0o775, 0o770, 0o760, 0o750, 0o711, 0o705, 0o701, 0]
)
def test_e4_arbitrary_modes_refuse_without_chmod(
    tmp_path: Path, parent_mode: int, request: pytest.FixtureRequest
) -> None:
    _authority(tmp_path, parent_mode=parent_mode)
    parent = tmp_path / ".index"
    request.addfinalizer(lambda: parent.chmod(0o700))
    before = _identity(parent)

    assessment = _mode().assess_index_parent_mode(tmp_path)

    assert assessment.state is _mode().IndexParentModeState.UNSAFE_MODE
    assert _identity(parent) == before


def test_e5_wrong_owner_refuses_via_identity_seam(tmp_path: Path, monkeypatch) -> None:
    _authority(tmp_path)
    mode = _mode()
    actual = mode._lstat

    def wrong_owner(path: Path):
        value = actual(path)
        return _fake(value, st_uid=value.st_uid + 1) if path.name == ".index" else value

    monkeypatch.setattr(mode, "_lstat", wrong_owner)
    assert mode.assess_index_parent_mode(tmp_path).state is mode.IndexParentModeState.UNSAFE_OWNER
    assert stat.S_IMODE((tmp_path / ".index").lstat().st_mode) == 0o755


def test_e6_symlink_parent_refuses_without_following(tmp_path: Path) -> None:
    _authority(tmp_path)
    target = tmp_path / "index-target"
    (tmp_path / ".index").rename(target)
    (tmp_path / ".index").symlink_to(target, target_is_directory=True)

    assessment = _mode().assess_index_parent_mode(tmp_path)

    assert assessment.state is _mode().IndexParentModeState.UNSAFE_SYMLINK
    assert stat.S_IMODE(target.lstat().st_mode) == 0o755


def test_e7_wrong_device_refuses_via_identity_seam(tmp_path: Path, monkeypatch) -> None:
    _authority(tmp_path)
    mode = _mode()
    actual = mode._lstat

    def wrong_device(path: Path):
        value = actual(path)
        return _fake(value, st_dev=value.st_dev + 1) if path.name == ".index" else value

    monkeypatch.setattr(mode, "_lstat", wrong_device)
    assert mode.assess_index_parent_mode(tmp_path).state is mode.IndexParentModeState.UNSAFE_DEVICE


@pytest.mark.parametrize("mutation", ["project_mode", "records_link", "project_device", "entry"])
def test_e8_unsound_child_authority_refuses_before_chmod(
    tmp_path: Path, monkeypatch, mutation: str
) -> None:
    project = _authority(tmp_path)
    mode = _mode()
    if mutation == "project_mode":
        project.chmod(0o755)
    elif mutation == "records_link":
        records = project / "runs"
        records.rmdir()
        target = tmp_path / "records-target"
        target.mkdir(mode=0o700)
        records.symlink_to(target, target_is_directory=True)
    elif mutation == "entry":
        (project / "unexpected").write_text("x")
    else:
        actual = mode._lstat

        def wrong_device(path: Path):
            value = actual(path)
            return _fake(value, st_dev=value.st_dev + 1) if path == project else value

        monkeypatch.setattr(mode, "_lstat", wrong_device)

    assert mode.assess_index_parent_mode(tmp_path).state is mode.IndexParentModeState.SURROUNDING_AUTHORITY_UNSAFE
    assert stat.S_IMODE((tmp_path / ".index").lstat().st_mode) == 0o755


def test_e9_replacement_is_not_chmodded(tmp_path: Path) -> None:
    _authority(tmp_path)
    mode = _mode()
    assessment = mode.assess_index_parent_mode(tmp_path)
    registry, handle = _maintenance(tmp_path)
    replacement = tmp_path / ".index"

    def replace(stage: str) -> None:
        if stage != "before_open":
            return
        replacement.rename(tmp_path / "old-index")
        project = replacement / "repo-map_dev"
        (project / "runs").mkdir(mode=0o700, parents=True)
        replacement.chmod(0o755)
        project.chmod(0o700)

    with pytest.raises(mode.IndexParentModeError, match="identity"):
        mode.harden_legacy_index_parent_mode(
            assessment, registry, handle, checkpoint=replace
        )

    assert stat.S_IMODE(replacement.lstat().st_mode) == 0o755


def test_e10_fd_bound_hardening_preserves_identity(tmp_path: Path) -> None:
    _authority(tmp_path)
    mode = _mode()
    assessment = mode.assess_index_parent_mode(tmp_path)
    registry, handle = _maintenance(tmp_path)
    before = _identity(tmp_path / ".index")

    result = mode.harden_legacy_index_parent_mode(assessment, registry, handle)

    after = _identity(tmp_path / ".index")
    assert result.changed_count == 1
    assert before[:3] == after[:3]
    assert after[3] == 0o700


def test_e11_only_parent_mode_changes(tmp_path: Path) -> None:
    project = _authority(tmp_path)
    historical = tmp_path / "r/historical"
    historical.mkdir(mode=0o700, parents=True)
    payload = historical / "payload"
    payload.write_bytes(b"unchanged")
    paths = (project, project / "runs", project / "summary.json", historical, payload)
    before = {path: (_identity(path), path.read_bytes() if path.is_file() else None) for path in paths}
    mode = _mode()
    registry, handle = _maintenance(tmp_path)

    mode.harden_legacy_index_parent_mode(
        mode.assess_index_parent_mode(tmp_path), registry, handle
    )

    assert {path: (_identity(path), path.read_bytes() if path.is_file() else None) for path in paths} == before


def test_e12_failure_after_hardening_keeps_private_mode(tmp_path: Path) -> None:
    project = _authority(tmp_path)
    mode = _mode()
    registry, handle = _maintenance(tmp_path)
    old_summary = (project / "summary.json").read_bytes()
    mode.harden_legacy_index_parent_mode(
        mode.assess_index_parent_mode(tmp_path), registry, handle
    )
    binding = MaintenanceIndexBinding.bind(tmp_path, registry, handle)

    with pytest.raises(RuntimeError, match="injected"):
        resource_index_recovery_owner.recover_index(
            binding,
            registry,
            handle,
            now_seconds=20,
            checkpoint=lambda stage: (_ for _ in ()).throw(RuntimeError("injected"))
            if stage == "before_inventory_write"
            else None,
        )

    assert stat.S_IMODE((tmp_path / ".index").lstat().st_mode) == 0o700
    assert (project / "summary.json").read_bytes() == old_summary


def test_e14_fresh_bootstrap_makes_all_authority_directories_private(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    previous = os.umask(0o022)
    try:
        index = AdvisoryIndex.initialize_empty(
            tmp_path / ".index/repo-map_dev",
            scratch_root=tmp_path,
            requesting_run_id=None,
            initialized_at_seconds=1,
        )
    finally:
        os.umask(previous)

    assert [_identity(path)[3] for path in (tmp_path, tmp_path / ".index", index.root, index.records_path)] == [0o700] * 4


def test_e15_ordinary_bootstrap_does_not_migrate_legacy_parent(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    (tmp_path / ".index").mkdir(mode=0o755)
    (tmp_path / ".index").chmod(0o755)

    with pytest.raises(HostAdmissionRefused) as raised:
        AdvisoryIndex.initialize_empty(
            tmp_path / ".index/repo-map_dev",
            scratch_root=tmp_path,
            requesting_run_id=None,
            initialized_at_seconds=1,
        )

    assert raised.value.maintenance_required is True
    assert stat.S_IMODE((tmp_path / ".index").lstat().st_mode) == 0o755


def test_e16_cli_refusal_is_closed_and_private(tmp_path: Path, monkeypatch, capsys) -> None:
    _authority(tmp_path, parent_mode=0o750)
    monkeypatch.setenv("REPOMAP_TEST_SCRATCH_ROOT", str(tmp_path))

    assert maintenance_tool.main(["recover-index"]) == 2
    output = capsys.readouterr().out
    assert "index_parent_mode_refused" in output
    assert str(tmp_path) not in output
    assert "inode" not in output


def test_e17_fix3_null_physical_authority_remains_separate(tmp_path: Path) -> None:
    _authority(tmp_path, parent_mode=0o700)
    invalid = tmp_path / "r/legacy entry"
    invalid.mkdir(mode=0o700, parents=True)
    scan = resource_index_recovery_owner.scan_run_population(tmp_path, "repo-map_dev")

    assert scan.entry_count == 1
    assert scan.ambiguous_run_count == 1
    assert scan.identities[0][1] is None
    assert not scan.measured_names


def test_e18_fix2_lifecycle_reservation_still_prevents_record_513() -> None:
    assert lifecycle_record_capacity(record_count=510, active_runs=0).new_run_lifecycle_admissible
    boundary = lifecycle_record_capacity(record_count=511, active_runs=0)
    assert boundary.lifecycle_committed_records == 511
    assert not boundary.new_run_lifecycle_admissible
