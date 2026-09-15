"""Filesystem and endpoint credential lifecycle for CoordinatorService."""

from __future__ import annotations

import os
from pathlib import Path
import secrets
import stat

from repomap_kg.coordinator.endpoint import load_endpoint_descriptor
from repomap_kg.coordinator.windows_security import (
    WindowsSecurityError,
    reject_reparse_path,
    validate_owner_private_acl,
)


def _validate_runtime_directory(path: Path) -> None:
    try:
        if os.name == "nt":  # pragma: no cover - native Windows runner
            reject_reparse_path(path)
        details = path.lstat()
    except (OSError, WindowsSecurityError):
        raise ValueError("runtime directory is invalid") from None
    if os.name == "nt":  # pragma: no cover - native Windows runner
        try:
            if not stat.S_ISDIR(details.st_mode):
                raise ValueError("runtime directory is invalid")
            validate_owner_private_acl(path)
            return
        except WindowsSecurityError:
            raise ValueError("runtime directory is invalid") from None
    if (
        not stat.S_ISDIR(details.st_mode)
        or details.st_uid != os.getuid()
        or stat.S_IMODE(details.st_mode) & 0o077
    ):
        raise ValueError("runtime directory is invalid")


def _endpoint_names(platform_name: str | None = None) -> tuple[str, str]:
    if (platform_name or os.name) == "nt":  # pragma: no cover - native Windows runner
        return "coordinator.endpoint.json", "coordinator.endpoint.json"
    return "coordinator.sock", "coordinator.token"


def _create_private_token(path: Path) -> str:
    token = secrets.token_urlsafe(32)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, token.encode("ascii"))
    finally:
        os.close(descriptor)
    return token


def _remove_stale_endpoint(
    path: Path,
    *,
    socket_expected: bool = False,
    descriptor_expected: bool = False,
    expected_instance_id: str | None = None,
    expected_fencing_epoch: int | None = None,
) -> None:
    try:
        details = path.lstat()
    except FileNotFoundError:
        return
    except OSError:
        raise RuntimeError("coordinator endpoint cleanup failed") from None
    expected_type = (
        stat.S_ISSOCK(details.st_mode)
        if socket_expected
        else stat.S_ISREG(details.st_mode)
    )
    if descriptor_expected:
        try:
            load_endpoint_descriptor(
                path,
                expected_instance_id=expected_instance_id,
                expected_fencing_epoch=expected_fencing_epoch,
            )
        except ValueError:
            raise RuntimeError("coordinator endpoint cleanup refused") from None
    if (
        not expected_type
        or (
            os.name != "nt"
            and (
                details.st_uid != os.getuid()
                or (not socket_expected and stat.S_IMODE(details.st_mode) != 0o600)
            )
        )
    ):
        raise RuntimeError("coordinator endpoint cleanup refused")
    path.unlink()
