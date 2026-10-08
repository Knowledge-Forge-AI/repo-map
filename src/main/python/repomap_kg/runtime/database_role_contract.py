"""Cycle-free database role names, secrets, and config projections."""

from __future__ import annotations

import os
import re
import secrets
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

from repomap_kg.ops.config_records import OpsConfig
from repomap_kg.runtime._home_authority import (
    read_private_runtime_env,
    validate_private_file,
)


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
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


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


def read_read_status_password(home: Path) -> str:
    """Read the setup-owned read/status secret without changing runtime state."""

    try:
        text = read_private_runtime_env(home)
        values: list[str] = []
        for line in text.splitlines():
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise ValueError("malformed runtime credential authority")
            key, value = line.split("=", 1)
            if _ENV_NAME.fullmatch(key) is None:
                raise ValueError("malformed runtime credential authority")
            if key == READ_STATUS_PASSWORD_ENV:
                values.append(value)
        if len(values) != 1:
            raise ValueError("read/status credential authority is ambiguous")
        if not values[0].strip():
            raise ValueError("read/status credential authority is empty")
        return _validate_credential(values[0])
    except (OSError, UnicodeError, ValueError):
        raise ValueError("read/status credential unavailable or unsafe") from None


def read_configured_postgres_password(config: OpsConfig) -> str | None:
    """Resolve explicit PostgreSQL credential authority without environment mutation."""

    postgres = config.postgres
    try:
        if postgres.password is not None:
            return _validate_credential(postgres.password)
        if postgres.password_env is not None:
            if _ENV_NAME.fullmatch(postgres.password_env) is None:
                raise ValueError("malformed configured password environment")
            value = os.environ.get(postgres.password_env)
            if value is None:
                return None
            return _validate_credential(value)
        if postgres.password_file is not None:
            path = Path(postgres.password_file).expanduser()
            if not path.is_absolute():
                base = Path(config.config_home or config.config_path)
                path = base if base.is_dir() else base.parent
                path /= postgres.password_file
            return _read_private_credential_file(path)
        return None
    except (OSError, UnicodeError, ValueError):
        raise ValueError("configured PostgreSQL credential unavailable or unsafe") from None


def _validate_credential(value: str) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 256
        or any(character in value for character in ("\x00", "\r", "\n"))
    ):
        raise ValueError("database role credential is invalid")
    return value


def _read_private_credential_file(path: Path) -> str:
    validate_private_file(path)
    before = path.lstat()
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        opened = os.fstat(stream.fileno())
        validate_private_file(path, opened)
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError("changed credential authority")
        data = stream.read(4097)
    if len(data) > 4096:
        raise ValueError("oversized credential authority")
    return _validate_credential(data.decode("utf-8").strip())


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
    "read_configured_postgres_password",
    "read_read_status_password",
    "project_database_role_config",
    "project_read_status_config",
    "read_role_secrets",
]
