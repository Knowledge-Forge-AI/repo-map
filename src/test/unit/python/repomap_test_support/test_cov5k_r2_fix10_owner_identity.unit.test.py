"""Logical tool owner identity survives launcher resolution topology."""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess

import pytest

from repomap_test_support.test_cov5k_r2_fix2_catalog import build_closed_catalog
from repomap_test_support.test_cov5k_r2_fix2_evidence import (
    ExecutorEvidenceError,
    verify_executor_evidence,
)
from repomap_test_support.test_cov5k_r2_fix2_runtime import execute_runtime_driver_read
from repomap_test_support.test_cov5k_r2_fix3_owner_binding import external_owner_evidence
from repomap_test_support.test_cov5k_r2_fix4_psycopg import public_expected_authority


_WRAPPER_BYTES = b"#!/bin/sh\n# launcher target\nexec /bin/true \"$@\"\n"
_DIRECT_BYTES = b"#!/bin/sh\nexec /bin/true \"$@\"\n"


class _PsqlCompletion(subprocess.CompletedProcess[str]):
    def __init__(self) -> None:
        super().__init__(args=[], returncode=0, stdout="", stderr="")


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _psql_entry():
    return next(
        entry
        for entry in build_closed_catalog()
        if entry.semantic_group == "D"
        and entry.operation_kind == "runtime_driver_read"
        and dict(entry.parameter_values)["driver"] == "psql"
        and dict(entry.parameter_values)["failure_category"] == "success"
    )


def _executable(path: Path, payload: bytes) -> Path:
    path.write_bytes(payload)
    path.chmod(0o755)
    return path


def _wrapper_shim(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    """PATH shim whose logical `psql` resolves to a different basename."""

    shim = tmp_path / "bin"
    shim.mkdir()
    target = _executable(shim / "pg_wrapper", _WRAPPER_BYTES)
    link = shim / "psql"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("host does not permit symlink creation")
    monkeypatch.setenv("PATH", str(shim))
    return link, target


def _direct_shim(tmp_path: Path, monkeypatch) -> Path:
    shim = tmp_path / "bin"
    shim.mkdir()
    executable = _executable(shim / "psql", _DIRECT_BYTES)
    monkeypatch.setenv("PATH", str(shim))
    return executable


def _observe(executable: str):
    return external_owner_evidence(
        executor=execute_runtime_driver_read,
        executable=executable,
        owner_entry_count=1,
        scenario_seam_active=True,
    )


def _enact(psql_executable: str = "psql"):
    entry = _psql_entry()
    result = execute_runtime_driver_read(
        entry,
        psql_args=(),
        expected_authority=public_expected_authority(),
        psql_executable=psql_executable,
        psql_runner=lambda *_a, **_k: _PsqlCompletion(),
    )
    return entry, result


def test_symlinked_launcher_preserves_frozen_logical_owner(tmp_path, monkeypatch) -> None:
    _link, target = _wrapper_shim(tmp_path, monkeypatch)
    assert target.name != "psql"
    assert _observe("psql").owner_source_path == "tool:psql"


def test_symlinked_launcher_binds_physical_identity_to_resolved_target(
    tmp_path, monkeypatch
) -> None:
    _link, target = _wrapper_shim(tmp_path, monkeypatch)
    evidence = _observe("psql")
    stat = target.stat()
    resolved_identity = _digest(
        f"{target.name}:{stat.st_dev}:{stat.st_ino}:{stat.st_size}".encode("utf-8")
    )
    logical_identity = _digest(
        f"psql:{stat.st_dev}:{stat.st_ino}:{stat.st_size}".encode("utf-8")
    )
    assert evidence.module_source_digest == _digest(_WRAPPER_BYTES)
    assert evidence.qualified_symbol == f"external:{target.name}"
    assert evidence.code_object_identity == resolved_identity
    assert evidence.code_object_identity != logical_identity


def test_registered_and_observed_agree_for_launcher_topology(tmp_path, monkeypatch) -> None:
    _wrapper_shim(tmp_path, monkeypatch)
    entry, result = _enact()
    assert result.owner_entry_evidence.owner_source_path == "tool:psql"
    verify_executor_evidence(entry, result)


def test_direct_executable_without_launcher_still_binds(tmp_path, monkeypatch) -> None:
    executable = _direct_shim(tmp_path, monkeypatch)
    evidence = _observe("psql")
    assert evidence.owner_source_path == "tool:psql"
    assert evidence.qualified_symbol == "external:psql"
    assert evidence.module_source_digest == _digest(executable.read_bytes())
    entry, result = _enact()
    verify_executor_evidence(entry, result)


def test_full_path_invocation_preserves_logical_owner(tmp_path, monkeypatch) -> None:
    link, target = _wrapper_shim(tmp_path, monkeypatch)
    evidence = _observe(str(link))
    assert evidence.owner_source_path == "tool:psql"
    assert evidence.module_source_digest == _digest(target.read_bytes())
    entry, result = _enact(psql_executable=str(link))
    verify_executor_evidence(entry, result)


def test_executable_substitution_still_fails_closed(tmp_path, monkeypatch) -> None:
    _link, target = _wrapper_shim(tmp_path, monkeypatch)
    entry, result = _enact()
    _executable(target, _WRAPPER_BYTES + b"# substituted payload\n")
    with pytest.raises(ExecutorEvidenceError, match="module digest"):
        verify_executor_evidence(entry, result)


def test_logical_name_substitution_still_fails_closed(tmp_path, monkeypatch) -> None:
    _link, target = _wrapper_shim(tmp_path, monkeypatch)
    evidence = _observe(target.name)
    assert evidence.owner_source_path == f"tool:{target.name}"
    assert evidence.module_source_digest == _digest(_WRAPPER_BYTES)
    with pytest.raises(ExecutorEvidenceError, match="source path"):
        _enact(psql_executable=target.name)


def test_docker_owner_semantics_are_untouched() -> None:
    catalog = build_closed_catalog()
    docker = {
        entry.owner.source_path
        for entry in catalog
        if entry.owner.source_path.startswith("tool:docker")
    }
    assert docker == {
        "tool:docker:rm",
        "tool:docker:start",
        "tool:docker:stats",
        "tool:docker:stop",
    }
    assert not any(
        entry.operation_kind == "runtime_driver_read"
        for entry in catalog
        if entry.owner.source_path.startswith("tool:docker")
    )
