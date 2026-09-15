"""FIX4 classifier parity and mutation-authority refusal guards."""

from __future__ import annotations

import errno
import stat
from pathlib import Path
from types import SimpleNamespace

from typing import cast

import pytest

import test_hygiene_maintenance as maintenance_tool
from repomap_test_support import resource_index_mode_migration as mode
from repomap_test_support.resource_index_recovery_records import IndexRecoveryError
from repomap_test_support.resource_ledger_io import write_private_json_exclusive
from repomap_test_support.resource_lifecycle_claim import (
    ClaimRegistry,
    MaintenanceHandle,
)


def _authority(root: Path, parent_mode: int = 0o755) -> Path:
    root.mkdir(mode=0o700, exist_ok=True)
    root.chmod(0o700)
    project = root / ".index/repo-map_dev"
    (project / "runs").mkdir(mode=0o700, parents=True)
    project.chmod(0o700)
    write_private_json_exclusive(
        project / "summary.json",
        {
            "schema": "repomap-test-hygiene-index-summary-v1",
            "generation": 1,
            "allocated_bytes": 0,
            "inode_count": 0,
        },
    )
    (root / ".index").chmod(parent_mode)
    return project


def _maintenance(root: Path):
    registry = ClaimRegistry(root)
    return registry, registry.acquire_maintenance("recover-index", now_seconds=10)


def _parent_mode(root: Path) -> int:
    return stat.S_IMODE((root / ".index").lstat().st_mode)


@pytest.mark.parametrize(
    ("case", "expected", "changed"),
    [
        ("private", mode.IndexParentModeState.PRIVATE_READY, 0),
        ("legacy", mode.IndexParentModeState.LEGACY_0755_HARDENABLE, 1),
        ("unsafe_mode", mode.IndexParentModeState.UNSAFE_MODE, None),
        ("symlink", mode.IndexParentModeState.UNSAFE_SYMLINK, None),
        (
            "surrounding",
            mode.IndexParentModeState.SURROUNDING_AUTHORITY_UNSAFE,
            None,
        ),
    ],
)
def test_e13_classifier_and_mutation_decisions_agree(
    tmp_path: Path, case: str, expected, changed: int | None
) -> None:
    project = _authority(tmp_path, 0o700 if case == "private" else 0o755)
    observed_parent = tmp_path / ".index"
    if case == "unsafe_mode":
        observed_parent.chmod(0o750)
    elif case == "symlink":
        target = tmp_path / "index-target"
        observed_parent.rename(target)
        observed_parent.symlink_to(target, target_is_directory=True)
        observed_parent = target
    elif case == "surrounding":
        project.chmod(0o755)
    assessment = mode.assess_index_parent_mode(tmp_path)
    registry, handle = _maintenance(tmp_path)
    before = stat.S_IMODE(observed_parent.lstat().st_mode)

    assert assessment.state is expected
    if changed is None:
        with pytest.raises(mode.IndexParentModeError) as raised:
            mode.harden_legacy_index_parent_mode(assessment, registry, handle)
        assert raised.value.state is assessment.state
        assert stat.S_IMODE(observed_parent.lstat().st_mode) == before
    else:
        result = mode.harden_legacy_index_parent_mode(
            assessment, registry, handle
        )
        assert result.before_state is assessment.state
        assert result.changed_count == changed


def test_assessment_refuses_unsafe_type_and_relative_path(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    (tmp_path / ".index").write_bytes(b"not-a-directory")

    assert mode.assess_index_parent_mode(tmp_path).state is mode.IndexParentModeState.UNSAFE_TYPE
    assert mode.assess_index_parent_mode(Path("relative")).state is mode.IndexParentModeState.UNSAFE_PATH


def test_assessment_detects_reread_identity_change(tmp_path: Path, monkeypatch) -> None:
    _authority(tmp_path)
    actual = mode._lstat
    parent_reads = 0

    def changed(path: Path):
        nonlocal parent_reads
        value = actual(path)
        if path == tmp_path / ".index":
            parent_reads += 1
            if parent_reads == 2:
                return SimpleNamespace(
                    st_mode=value.st_mode,
                    st_uid=value.st_uid,
                    st_dev=value.st_dev,
                    st_ino=value.st_ino + 1,
                )
        return value

    monkeypatch.setattr(mode, "_lstat", changed)
    assert mode.assess_index_parent_mode(tmp_path).state is mode.IndexParentModeState.IDENTITY_CHANGED


def test_hardener_refuses_unheld_and_mismatched_authority(tmp_path: Path) -> None:
    def _invalid_maintenance_handle() -> MaintenanceHandle:
        """Narrow runtime-invalid MaintenanceHandle builder for negative controls."""
        return cast(MaintenanceHandle, object())

    first = tmp_path / "first"
    second = tmp_path / "second"
    _authority(first)
    _authority(second, 0o700)
    assessment = mode.assess_index_parent_mode(first)
    registry, handle = _maintenance(first)

    with pytest.raises(Exception):
        mode.harden_legacy_index_parent_mode(
            assessment, registry, _invalid_maintenance_handle()
        )
    other, other_handle = _maintenance(second)
    with pytest.raises(mode.IndexParentModeError) as raised:
        mode.harden_legacy_index_parent_mode(
            assessment, other, other_handle
        )
    assert raised.value.state is mode.IndexParentModeState.UNSAFE_PATH
    assert _parent_mode(first) == 0o755


def test_os_failure_keeps_private_diagnosis_and_target_mode(
    tmp_path: Path, monkeypatch
) -> None:
    _authority(tmp_path)
    assessment = mode.assess_index_parent_mode(tmp_path)
    registry, handle = _maintenance(tmp_path)

    def refused(_descriptor: int, _mode: int) -> None:
        raise PermissionError(errno.EPERM, "refused")

    monkeypatch.setattr(mode.os, "fchmod", refused)
    with pytest.raises(mode.IndexParentModeError) as raised:
        mode.harden_legacy_index_parent_mode(
            assessment, registry, handle
        )

    assert raised.value.state is mode.IndexParentModeState.SURROUNDING_AUTHORITY_UNSAFE
    assert raised.value.failure_stage == "fchmod"
    assert raised.value.failure_errno == errno.EPERM
    assert raised.value.hardening_performed is False
    assert _parent_mode(tmp_path) == 0o755


def test_cli_reports_failure_after_successful_hardening(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _authority(tmp_path)
    monkeypatch.setenv("REPOMAP_TEST_SCRATCH_ROOT", str(tmp_path))
    monkeypatch.setattr(
        maintenance_tool,
        "recover_index",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            IndexRecoveryError("injected")
        ),
    )

    assert maintenance_tool.main(["recover-index"]) == 2
    output = capsys.readouterr().out
    assert "'index_parent_mode_action': 'legacy_0755_hardened'" in output
    assert "'index_parent_hardening_count': 1" in output
    assert str(tmp_path) not in output
    assert _parent_mode(tmp_path) == 0o700
