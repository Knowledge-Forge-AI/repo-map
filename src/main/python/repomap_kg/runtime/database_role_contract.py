"""Cycle-free database role names, secrets, and config projections."""

from __future__ import annotations

import os
import re
import secrets
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

from repomap_kg.ops.config_records import OpsConfig


READ_STATUS_ROLE = "repomap_read_status"
REFRESH_PUBLICATION_ROLE = "repomap_refresh_publication"
COORDINATOR_CONTROL_ROLE = "repomap_coordinator_control"

READ_STATUS_PASSWORD_ENV = "REPOMAP_READ_STATUS_PASSWORD"
REFRESH_PUBLICATION_PASSWORD_ENV = "REPOMAP_REFRESH_PUBLICATION_PASSWORD"
COORDINATOR_CONTROL_PASSWORD_ENV = "REPOMAP_COORDINATOR_CONTROL_PASSWORD"
ROLE_PASSWORD_ENVS = (
    READ_STATUS_PASSWORD_ENV,
    REFRESH_PUBLICATION_PASSWORD_ENV,
    COORDINATOR_CONTROL_PASSWORD_ENV,
)
_ROLE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,62}\Z")


@dataclass(frozen=True)
class RoleSecrets:
    """Private role passwords loaded from the owner-protected runtime env."""

    read_status: str
    refresh_publication: str
    coordinator_control: str

    def __post_init__(self) -> None:
        for value in (
            self.read_status,
            self.refresh_publication,
            self.coordinator_control,
        ):
            if (
                not isinstance(value, str)
                or not 1 <= len(value) <= 256
                or any(character in value for character in ("\x00", "\r", "\n"))
            ):
                raise ValueError("database role credential is invalid")


def project_database_role_config(
    config: OpsConfig,
    *,
    role: str,
    password_env: str | None = None,
    password: str | None = None,
) -> OpsConfig:
    """Project one parsed config onto an explicit database login authority."""

    if not isinstance(role, str) or _ROLE_NAME.fullmatch(role) is None:
        raise ValueError("database role is invalid")
    if (password_env is None) == (password is None):
        raise ValueError("exactly one database role credential is required")
    postgres = replace(
        config.postgres,
        user=role,
        password_env=password_env,
        password_file=None,
        password=password,
    )
    return replace(config, postgres=postgres)


def project_read_status_config(config: OpsConfig) -> OpsConfig:
    """Project a read-only service config without loading its secret."""

    return project_database_role_config(
        config,
        role=READ_STATUS_ROLE,
        password_env=READ_STATUS_PASSWORD_ENV,
    )


def ensure_role_secrets(env_file: Path) -> tuple[str, ...]:
    """Atomically add missing role secrets without replacing existing values."""

    if not env_file.parent.exists():
        env_file.parent.mkdir(parents=True, mode=0o700)
    text = env_file.read_text(encoding="utf-8") if env_file.is_file() else ""
    values = _env_values(text)
    missing = tuple(name for name in ROLE_PASSWORD_ENVS if name not in values)
    if not missing:
        env_file.chmod(0o600)
        return ()
    suffix = "" if not text or text.endswith("\n") else "\n"
    additions = "".join(f"{name}={secrets.token_urlsafe(32)}\n" for name in missing)
    _atomic_private_write(env_file, text + suffix + additions)
    return missing


def read_role_secrets(env_file: Path) -> RoleSecrets:
    """Load the complete non-administrative role secret set."""

    environment_values = {name: os.environ.get(name) for name in ROLE_PASSWORD_ENVS}
    if all(environment_values.values()):
        return RoleSecrets(
            read_status=str(environment_values[READ_STATUS_PASSWORD_ENV]),
            refresh_publication=str(
                environment_values[REFRESH_PUBLICATION_PASSWORD_ENV]
            ),
            coordinator_control=str(
                environment_values[COORDINATOR_CONTROL_PASSWORD_ENV]
            ),
        )
    ensure_role_secrets(env_file)
    values = _env_values(env_file.read_text(encoding="utf-8"))
    return RoleSecrets(
        read_status=values[READ_STATUS_PASSWORD_ENV],
        refresh_publication=values[REFRESH_PUBLICATION_PASSWORD_ENV],
        coordinator_control=values[COORDINATOR_CONTROL_PASSWORD_ENV],
    )


def _env_values(text: str) -> dict[str, str]:
    return {
        key: value
        for line in text.splitlines()
        if line and not line.startswith("#") and "=" in line
        for key, value in (line.split("=", 1),)
    }


def _atomic_private_write(path: Path, text: str) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            os.chmod(stream.name, 0o600)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        path.chmod(0o600)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


__all__ = [
    "COORDINATOR_CONTROL_PASSWORD_ENV",
    "COORDINATOR_CONTROL_ROLE",
    "READ_STATUS_PASSWORD_ENV",
    "READ_STATUS_ROLE",
    "REFRESH_PUBLICATION_PASSWORD_ENV",
    "REFRESH_PUBLICATION_ROLE",
    "ROLE_PASSWORD_ENVS",
    "RoleSecrets",
    "ensure_role_secrets",
    "project_database_role_config",
    "project_read_status_config",
    "read_role_secrets",
]
