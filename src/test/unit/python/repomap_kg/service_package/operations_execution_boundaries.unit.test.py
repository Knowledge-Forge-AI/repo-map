"""Focused negative, error, and boundary tests for service operations and execution."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from repomap_kg.service_package._artifacts_io import (
    _absolute_path,
    _safe_file_details,
    _validate_new_content,
)
from repomap_kg.service_package._artifacts_locking import _safe_lock_details
from repomap_kg.service_package._operations_execution import (
    ServicePackageError,
    _CoordinatorExecutionBase,
    _return_code,
)
from repomap_kg.service_package.artifacts import ServiceArtifactError


def test_return_code_parsing() -> None:
    assert _return_code(0) == 0
    assert _return_code(1) == 1

    class Result:
        returncode = 42

    assert _return_code(Result()) == 42

    with pytest.raises(TypeError, match="invalid result"):
        _return_code("not_an_int")

    with pytest.raises(TypeError, match="invalid result"):
        _return_code(True)  # bool is not accepted as returncode int


def test_absolute_path_checks() -> None:
    assert _absolute_path(Path("/var/run/test.service")) == Path("/var/run/test.service")

    with pytest.raises(ServiceArtifactError, match="service_definition_unsafe"):
        _absolute_path(Path("relative/path/service"))

    with pytest.raises(ServiceArtifactError, match="service_definition_unsafe"):
        _absolute_path(Path("/var/run/" + chr(0) + "nullbyte"))


def test_validate_new_content_rejections() -> None:
    # Non-bytes
    with pytest.raises(ServiceArtifactError, match="service_definition_invalid"):
        _validate_new_content(cast(bytes, "string not bytes"), lambda b: True)

    # Exceeds max bytes (1MB)
    too_large = b"x" * (1024 * 1024 + 1)
    with pytest.raises(ServiceArtifactError, match="service_definition_invalid"):
        _validate_new_content(too_large, lambda b: True)

    # Validator fails
    with pytest.raises(ServiceArtifactError, match="service_definition_invalid"):
        _validate_new_content(b"content", lambda b: False)


def test_execution_base_probe_error() -> None:
    base = _CoordinatorExecutionBase()
    base.runner = lambda argv: 127  # returns code 127
    with pytest.raises(ServicePackageError, match="native_service_probe_failed"):
        base._probe(("probe", "argv"), false_return_codes=frozenset({1, 2}))


def test_execution_base_run_commands_error() -> None:
    base = _CoordinatorExecutionBase()
    base.runner = lambda argv: 1
    with pytest.raises(ServicePackageError, match="native_service_command_failed"):
        base._run_commands((("failing", "cmd"),))


def test_safe_details_helpers(tmp_path: Path) -> None:
    test_file = tmp_path / "test.file"
    test_file.write_bytes(b"content")
    test_file.chmod(0o600)
    details = test_file.stat()
    assert _safe_file_details(details, details.st_uid) is True
    assert _safe_lock_details(details, details.st_uid) is True
    assert _safe_lock_details(details, details.st_uid + 999) is False
