"""Closed setup-owned administrator fallback for local lifecycle consumers."""

from __future__ import annotations

import os
from pathlib import Path

from repomap_kg.coordinator.configured_refresh import _read_private_password
from repomap_kg.ops.config_records import OpsConfig
from repomap_kg.runtime._home_authority import read_private_runtime_env
from repomap_kg.runtime.postgres_route import effective_postgres_route

DEFAULT_ADMIN_ENV = "REPOMAP_PG_PASSWORD"


def local_admin_password(config: OpsConfig, home: Path) -> str:
    """Literal, explicit file, present environment, then eligible local secret."""
    postgres = config.postgres
    try:
        if postgres.password is not None:
            value = postgres.password
        elif postgres.password_file is not None:
            path = Path(postgres.password_file).expanduser()
            value = _read_private_password(path if path.is_absolute() else home / path)
        elif postgres.password_env is not None and postgres.password_env in os.environ:
            value = os.environ[postgres.password_env]
        elif (
            config.config_home is not None
            and Path(config.config_home) == home
            and postgres.password_env == DEFAULT_ADMIN_ENV
            and effective_postgres_route(config).kind == "local-native"
        ):
            return _generated_password(home)
        else:
            raise ValueError("local-admin-credential-unavailable")
        return _checked_value(value, generated=False)
    except (OSError, ValueError):
        raise ValueError("local-admin-credential-unavailable-or-unsafe") from None


def _checked_value(value: str, *, generated: bool = True) -> str:
    if not 1 <= len(value) <= 256 or (
        generated and any(c in value for c in "\x00\r\n")
    ):
        raise ValueError("local-admin-credential-unavailable")
    return value


def _generated_password(home: Path) -> str:
    values = [
        line.partition("=")[2]
        for line in read_private_runtime_env(home).split("\n")
        if line.partition("=")[0] == DEFAULT_ADMIN_ENV
    ]
    if len(values) != 1:
        raise ValueError("generated-local-admin-credential-ambiguous")
    return _checked_value(values[0])
