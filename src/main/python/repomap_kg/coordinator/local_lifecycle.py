"""Explicit lifecycle for the derived local coordinator control database."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path

import psycopg as psycopg

from repomap_kg.coordinator._control_types import ControlSchemaError
from repomap_kg.coordinator._lifecycle_authority import (
    CoordinatorControlError,
    LocalControlAuthority,
    _LifecycleAuthority,
    _reconcile_control_roles,
    derived_control_database,
)
from repomap_kg.coordinator._lifecycle_upgrade import (
    upgrade_coordinator_control,
)
from repomap_kg.ops.config import resolve_repo_map_home
from repomap_kg.runtime.maintenance import MaintenanceUnavailableError


@contextmanager
def maintenance_activity_for_home(
    repo_map_home: str | Path | None,
) -> Iterator[None]:
    """Hold configured control-plane admission for one direct operation."""

    try:
        authority = LocalControlAuthority(resolve_repo_map_home(repo_map_home))
        with authority.maintenance_activity():
            yield
    except MaintenanceUnavailableError:
        raise
    except Exception:
        raise MaintenanceUnavailableError(
            "maintenance authority is unavailable"
        ) from None


@contextmanager
def maintenance_window_for_graph_upgrade(
    repo_map_home: str | Path | None,
    database: str,
) -> Iterator[None]:
    """Hold control then target-graph exclusivity for one schema upgrade."""

    try:
        authority = LocalControlAuthority(resolve_repo_map_home(repo_map_home))
        if database not in authority.graph_databases:
            raise MaintenanceUnavailableError(
                "maintenance target is not an owned graph database"
            )
        with authority.maintenance_window(graph_databases=(database,)):
            yield
    except MaintenanceUnavailableError:
        raise
    except Exception:
        raise MaintenanceUnavailableError(
            "maintenance authority is unavailable"
        ) from None


@contextmanager
def maintenance_window_for_coordinated_backup(
    repo_map_home: str | Path | None,
) -> Iterator[None]:
    """Hold control and every graph stable for one coordinated backup set."""

    try:
        authority = LocalControlAuthority(resolve_repo_map_home(repo_map_home))
        graph_databases = authority.graph_databases
    except MaintenanceUnavailableError:
        raise
    except Exception:
        raise MaintenanceUnavailableError(
            "maintenance authority is unavailable"
        ) from None

    with ExitStack() as stack:
        try:
            stack.enter_context(
                authority.maintenance_window(graph_databases=graph_databases)
            )
        except MaintenanceUnavailableError:
            raise
        except Exception:
            raise MaintenanceUnavailableError(
                "maintenance authority is unavailable"
            ) from None
        yield


@contextmanager
def maintenance_window_for_database_drop(
    repo_map_home: str | Path | None,
    database: str,
) -> Iterator[None]:
    """Hold exact cross-plane exclusivity for one backup-first drop."""

    try:
        authority = LocalControlAuthority(resolve_repo_map_home(repo_map_home))
        if database == authority.database_name:
            graph_databases = authority.graph_databases
        elif database in authority.graph_databases:
            graph_databases = (database,)
        else:
            raise MaintenanceUnavailableError(
                "maintenance target is not an owned database"
            )
    except MaintenanceUnavailableError:
        raise
    except Exception:
        raise MaintenanceUnavailableError(
            "maintenance authority is unavailable"
        ) from None

    with ExitStack() as stack:
        try:
            stack.enter_context(
                authority.maintenance_window(graph_databases=graph_databases)
            )
        except MaintenanceUnavailableError:
            raise
        except Exception:
            raise MaintenanceUnavailableError(
                "maintenance authority is unavailable"
            ) from None
        yield


def coordinator_control_status(
    repo_map_home: str | Path,
    *,
    authority_factory: Callable[[str | Path], _LifecycleAuthority] = LocalControlAuthority,
) -> dict[str, object]:
    """Return bounded availability and compatibility for derived control state."""

    try:
        authority = authority_factory(repo_map_home)
        if not authority.database_exists():
            return _status_payload(False, None, None)
        try:
            version = authority.control_store().check_schema_version()
        except ControlSchemaError:
            return _status_payload(True, False, None)
        return _status_payload(True, True, version)
    except CoordinatorControlError:
        raise
    except Exception:
        raise CoordinatorControlError("coordinator_control_status_failed") from None


def initialize_coordinator_control(
    repo_map_home: str | Path,
    *,
    authority_factory: Callable[[str | Path], _LifecycleAuthority] = LocalControlAuthority,
) -> dict[str, object]:
    """Create the derived database when absent and initialize its isolated schema."""

    authority: _LifecycleAuthority | None = None
    created = False
    try:
        authority = authority_factory(repo_map_home)
        if not authority.database_exists():
            created = authority.create_database()
        store = authority.control_store()
        if created:
            store.initialize_schema()
        version = store.check_schema_version()
        _reconcile_control_roles(authority)
        return {
            "command": "coordinator-control-init",
            "result": "ready",
            "database_created": created,
            "schema_version": version,
        }
    except Exception:
        if created:
            try:
                if authority is None:
                    raise CoordinatorControlError(
                        "coordinator_control_init_cleanup_failed"
                    )
                authority.drop_created_database()
            except Exception:
                raise CoordinatorControlError(
                    "coordinator_control_init_cleanup_failed"
                ) from None
        raise CoordinatorControlError("coordinator_control_init_failed") from None


def format_coordinator_control_table(payload: dict[str, object]) -> str:
    """Format one bounded control lifecycle result."""

    lines = ["RepoMap coordinator control", "field | value"]
    for field in (
        "result",
        "database_available",
        "database_created",
        "schema_compatible",
        "schema_version",
        "schema_before",
        "backup_verified",
        "rollback_available",
        "reference_cleaned",
    ):
        if field in payload:
            lines.append(f"{field} | {str(payload[field]).lower()}")
    return "\n".join(lines)


def _status_payload(
    database_available: bool,
    schema_compatible: bool | None,
    schema_version: int | None,
) -> dict[str, object]:
    result = (
        "ready"
        if schema_compatible is True
        else "incompatible"
        if database_available
        else "unavailable"
    )
    return {
        "command": "coordinator-control-status",
        "result": result,
        "database_available": database_available,
        "schema_compatible": schema_compatible,
        "schema_version": schema_version,
    }


__all__ = [
    "CoordinatorControlError",
    "LocalControlAuthority",
    "coordinator_control_status",
    "derived_control_database",
    "format_coordinator_control_table",
    "initialize_coordinator_control",
    "maintenance_activity_for_home",
    "maintenance_window_for_coordinated_backup",
    "maintenance_window_for_database_drop",
    "maintenance_window_for_graph_upgrade",
    "upgrade_coordinator_control",
]
