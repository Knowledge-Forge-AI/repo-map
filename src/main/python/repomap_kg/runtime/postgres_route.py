"""Execution-only PostgreSQL routing; configuration and generation inputs stay intact."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

from repomap_kg.ops.config_records import OpsConfig, OpsPostgresConfig
from repomap_kg.runtime.database_role_contract import (
    project_read_status_config,
    read_configured_postgres_password,
    read_read_status_password,
)

CONTAINER_INTERNAL_MARKER = Path("/etc/repomap-release-container")
DEFAULT_POSTGRES_HOST_PORT = 55432
DEFAULT_SETUP_POSTGRES_HOST = "postgres"
DEFAULT_SETUP_POSTGRES_PORT = 5432
DEFAULT_SETUP_POSTGRES_USER = "repomap"
DEFAULT_SETUP_POSTGRES_PASSWORD_ENV = "REPOMAP_PG_PASSWORD"
PostgresRouteKind = Literal["configured", "local-native", "container-internal"]


@dataclass(frozen=True)
class PostgresRoute:
    host: str
    port: int
    kind: PostgresRouteKind

    def apply(self, postgres: OpsPostgresConfig) -> OpsPostgresConfig:
        return replace(postgres, host=self.host, port=self.port)


@dataclass(frozen=True)
class ReadbackPostgresAuthority:
    postgres: OpsPostgresConfig
    password: str | None = field(repr=False, compare=False)
    projected_read_status: bool


def select_postgres_route(config: OpsConfig, *, release_container: bool) -> PostgresRoute:
    """Select a route without IO or changing configured identity."""
    postgres = config.postgres
    if release_container:
        return PostgresRoute(postgres.host, postgres.port, "container-internal")
    if (config.config_home and config.runtime.postgres.direct_host_port_enabled
            and postgres.host == DEFAULT_SETUP_POSTGRES_HOST
            and postgres.port == DEFAULT_SETUP_POSTGRES_PORT):
        return PostgresRoute(
            "127.0.0.1", config.runtime.postgres.host_port or DEFAULT_POSTGRES_HOST_PORT,
            "local-native",
        )
    return PostgresRoute(postgres.host, postgres.port, "configured")


def effective_postgres_route(config: OpsConfig) -> PostgresRoute:
    """A release marker alone denies host projection; it grants no authority."""
    return select_postgres_route(config, release_container=CONTAINER_INTERNAL_MARKER.is_file())


def execution_postgres(config: OpsConfig) -> OpsPostgresConfig:
    """Project only connection arguments, never inputs to generation hashing."""
    return effective_postgres_route(config).apply(config.postgres)


def readback_postgres_authority(config: OpsConfig) -> ReadbackPostgresAuthority:
    """Select readback credentials without changing process environment state."""

    readback_password: str | None
    if _eligible_local_read_status_projection(config):
        home = Path(config.config_home or "")
        readback_password = read_read_status_password(home)
        projected = project_read_status_config(config)
        return ReadbackPostgresAuthority(
            postgres=execution_postgres(projected),
            password=readback_password,
            projected_read_status=True,
        )
    readback_password = read_configured_postgres_password(config)
    sanitized = replace(
        config,
        postgres=replace(
            config.postgres,
            password_env=None,
            password_file=None,
            password=None,
        ),
    )
    return ReadbackPostgresAuthority(
        postgres=execution_postgres(sanitized),
        password=readback_password,
        projected_read_status=False,
    )


def _eligible_local_read_status_projection(config: OpsConfig) -> bool:
    if not config.config_home or not config.config_files:
        return False
    try:
        home = Path(config.config_home).expanduser().resolve()
        parsed_from_home = Path(config.config_path).expanduser().resolve() == home
    except OSError:
        return False
    postgres = config.postgres
    return (
        parsed_from_home
        and postgres.host == DEFAULT_SETUP_POSTGRES_HOST
        and postgres.port == DEFAULT_SETUP_POSTGRES_PORT
        and postgres.user == DEFAULT_SETUP_POSTGRES_USER
        and postgres.password_env == DEFAULT_SETUP_POSTGRES_PASSWORD_ENV
        and postgres.password_file is None
        and postgres.password is None
        and effective_postgres_route(config).kind == "local-native"
    )
