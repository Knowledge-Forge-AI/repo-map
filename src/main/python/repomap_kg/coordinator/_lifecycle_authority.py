"""Connection authority and database-level maintenance for coordinator control."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, ExitStack, contextmanager
from pathlib import Path
from typing import Protocol, runtime_checkable

import psycopg
from psycopg import sql

from repomap_kg.coordinator._refresh_capability_io import validate_config_file
from repomap_kg.coordinator.configured_refresh import _postgres_password
from repomap_kg.coordinator.storage import ControlStore
from repomap_kg.ops.config import load_ops_config_home
from repomap_kg.ops.resolved_config import control_database_for, resolve_ops_config
from repomap_kg.runtime.backup_commands import validate_database_name
from repomap_kg.runtime.database_role_contract import (
    COORDINATOR_CONTROL_ROLE,
    REFRESH_PUBLICATION_ROLE,
    read_role_secrets,
)
from repomap_kg.runtime.database_roles import (
    render_database_role_sql,
)
from repomap_kg.runtime.maintenance import MaintenanceUnavailableError


class CoordinatorControlError(RuntimeError):
    """Bounded explicit control-database lifecycle failure."""


class _LifecycleStore(Protocol):
    def check_schema_version(self) -> int: ...

    def initialize_schema(self) -> None: ...


class _LifecycleAuthority(Protocol):
    def database_exists(self) -> bool: ...

    def create_database(self) -> bool: ...

    def drop_created_database(self) -> None: ...

    def control_store(self) -> _LifecycleStore: ...


@runtime_checkable
class _MaintenanceWindowAuthority(Protocol):
    def maintenance_window(
        self,
        *,
        graph_databases: tuple[str, ...],
    ) -> AbstractContextManager[None]: ...


def _reconcile_control_roles(authority: object) -> None:
    reconcile_roles = getattr(authority, "reconcile_control_roles", None)
    if reconcile_roles is not None:
        if not callable(reconcile_roles):
            raise TypeError("reconcile_control_roles is not callable")
        reconcile_roles()


def _maintenance_window(
    authority: object,
    *,
    graph_databases: tuple[str, ...],
) -> AbstractContextManager[None]:
    if not isinstance(authority, _MaintenanceWindowAuthority):
        raise RuntimeError("maintenance authority is unavailable")
    return authority.maintenance_window(graph_databases=graph_databases)


def derived_control_database(graph_database: str) -> str:
    """Derive the dedicated local control database without client selection."""

    try:
        return str(control_database_for(graph_database))
    except ValueError:
        raise CoordinatorControlError("coordinator_control_database_invalid")


def _validate_reference_database(database: str) -> None:
    validate_database_name(database)
    if not database.startswith("repomap_control_ref_"):
        raise CoordinatorControlError("coordinator_control_reference_invalid")


class LocalControlAuthority:
    """Private connection authority derived from one owner-controlled config home."""

    def __init__(
        self,
        repo_map_home: str | Path,
        *,
        capability: str = "lifecycle",
    ) -> None:
        home = Path(repo_map_home).expanduser()
        if capability not in {"lifecycle", "coordinator"}:
            raise ValueError("database capability is invalid")
        self._home = home
        self._capability = capability
        validate_config_file(home)
        config = load_ops_config_home(home)
        self._host = config.postgres.host
        self._port = config.postgres.port
        self._owner_user = config.postgres.user
        self._admin_password = (
            _postgres_password(config, home) if capability == "lifecycle" else None
        )
        self._role_secrets = (
            read_role_secrets(home / "runtime" / ".env")
            if capability == "coordinator"
            else None
        )
        resolved = resolve_ops_config(config)
        self._database = str(resolved.control_database)
        self._maintenance_database = str(resolved.maintenance_database)
        self._graph_databases = tuple(
            sorted({str(graph.database) for graph in resolved.graphs})
        )

    def database_exists(self) -> bool:
        return self.reference_database_exists(self._database)

    @property
    def database_name(self) -> str:
        return self._database

    def reference_database_exists(self, database: str) -> bool:
        self._validate_control_or_reference_database(database)
        with self._connect(self._maintenance_database) as connection:
            row = connection.execute(
                "SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname = %s)",
                (database,),
            ).fetchone()
        return bool(row and row[0] is True)

    def create_database(self) -> bool:
        try:
            with self._connect(
                self._maintenance_database,
                autocommit=True,
            ) as connection:
                connection.execute(
                    sql.SQL(
                        "CREATE DATABASE {} WITH TEMPLATE template0 "
                        "ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C'"
                    ).format(sql.Identifier(self._database))
                )
        except psycopg.errors.DuplicateDatabase:
            return False
        return True

    def drop_created_database(self) -> None:
        with self._connect(self._maintenance_database, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (self._database,),
            )
            connection.execute(
                sql.SQL("DROP DATABASE {}").format(sql.Identifier(self._database))
            )

    def control_store(self) -> ControlStore:
        return self.control_store_for(self._database)

    def reconcile_control_roles(self) -> None:
        """Reapply the declarative read and coordinator grant contract."""

        if self._capability != "lifecycle":
            raise CoordinatorControlError("coordinator_lifecycle_capability_required")
        role_sql = render_database_role_sql(
            database=self._database,
            owner_role=self._owner_user,
            database_kind="control",
            secrets=read_role_secrets(self._home / "runtime" / ".env"),
        )
        with self._connect(self._database) as connection:
            connection.execute(role_sql)

    def control_store_for(self, database: str) -> ControlStore:
        self._validate_store_database(database)
        return ControlStore(lambda: self._connect(database))

    @property
    def graph_databases(self) -> tuple[str, ...]:
        return self._graph_databases

    def maintenance_activity(self) -> AbstractContextManager[None]:
        return self.control_store().maintenance_activity()

    @contextmanager
    def maintenance_window(
        self,
        *,
        graph_databases: tuple[str, ...] = (),
    ) -> Iterator[None]:
        targets = tuple(sorted(set(graph_databases)))
        for database in targets:
            validate_database_name(database)
            if database not in self._graph_databases:
                raise MaintenanceUnavailableError(
                    "maintenance target is not an owned graph database"
                )
        with ExitStack() as stack:
            stack.enter_context(self.control_store().maintenance_window())
            for database in targets:
                stack.enter_context(
                    self.control_store_for(database).maintenance_window()
                )
            yield

    def create_reference_database(self, database: str) -> None:
        _validate_reference_database(database)
        with self._connect(self._maintenance_database, autocommit=True) as connection:
            connection.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database))
            )

    def drop_reference_database(self, database: str) -> None:
        _validate_reference_database(database)
        with self._connect(self._maintenance_database, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (database,),
            )
            connection.execute(
                sql.SQL("DROP DATABASE {}").format(sql.Identifier(database))
            )

    def _validate_control_or_reference_database(self, database: str) -> None:
        validate_database_name(database)
        if database == self._database or database.startswith(
            "repomap_control_ref_"
        ):
            return
        raise CoordinatorControlError("coordinator_control_database_not_owned")

    def _validate_store_database(self, database: str) -> None:
        validate_database_name(database)
        if database == self._database or database in self._graph_databases:
            return
        if database.startswith("repomap_control_ref_"):
            return
        raise CoordinatorControlError("coordinator_control_database_not_owned")

    def _connect(self, database: str, *, autocommit: bool = False):
        if self._capability == "lifecycle":
            user = self._owner_user
            password = self._admin_password
        elif database == self._database:
            assert self._role_secrets is not None
            user = COORDINATOR_CONTROL_ROLE
            password = self._role_secrets.coordinator_control
        elif database in self._graph_databases:
            assert self._role_secrets is not None
            user = REFRESH_PUBLICATION_ROLE
            password = self._role_secrets.refresh_publication
        else:
            raise CoordinatorControlError("coordinator_database_capability_denied")
        return psycopg.connect(
            host=self._host,
            port=self._port,
            user=user,
            dbname=database,
            password=password,
            autocommit=autocommit,
        )
