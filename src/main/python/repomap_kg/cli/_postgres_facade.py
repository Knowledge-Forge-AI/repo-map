"""Deferred PostgreSQL-implementation names of the ``repomap_kg.cli`` facade.

These facade names come from modules whose import closure loads the PostgreSQL
driver (``psycopg``): the durable coordinator, the service package API,
maintenance admission, the release cluster and the PostgreSQL publishers. They
are resolved from their source module on each attribute access instead of at
CLI import, so SQLite Local commands start without the driver while
``repomap_kg.cli.X`` and ``repomap_kg.cli.main.X`` keep returning the same
objects. ``__getattr__`` itself does not cache: caching would freeze whichever
object was installed when a name was first read (for example a test double) as
the facade value. ``__getattr__`` only runs for names that are not module
globals, so any assignment of a facade name on the module (including
``monkeypatch.setattr`` and its undo, which re-assigns the recorded value)
installs a real global that shadows deferred resolution until it is deleted.

A PostgreSQL command that needs a missing driver fails with
:data:`POSTGRES_DRIVER_UNAVAILABLE`; nothing is emulated.
"""

from __future__ import annotations

from typing import Any

POSTGRES_DRIVER_UNAVAILABLE = "postgresql-driver-unavailable"
_DRIVER_MODULES = frozenset({"psycopg", "psycopg2", "psycopg_binary", "psycopg_c", "psycopg_pool"})

_JOB_CONTROL = frozenset(
    {
        "cancel_coordinator_job",
        "coordinator_health",
        "coordinator_job_status",
        "format_coordinator_health_table",
        "format_coordinator_job_table",
        "format_coordinator_jobs_table",
        "list_coordinator_jobs",
        "wait_for_coordinator_job",
    }
)
_LOCAL_LIFECYCLE = frozenset(
    {
        "CoordinatorControlError",
        "coordinator_control_status",
        "format_coordinator_control_table",
        "initialize_coordinator_control",
        "maintenance_activity_for_home",
        "maintenance_window_for_coordinated_backup",
        "maintenance_window_for_database_drop",
        "maintenance_window_for_graph_upgrade",
        "upgrade_coordinator_control",
    }
)
_LOCAL_MODE = frozenset(
    {
        "CoordinatorModeError",
        "format_coordinator_refresh_table",
        "run_coordinator_refresh",
        "serve_configured_coordinator",
    }
)
_SERVICE_API = frozenset({"format_service_action_table", "run_coordinator_service_action"})
_MAINTENANCE = frozenset({"MaintenanceUnavailableError"})
_RELEASE_CLUSTER = frozenset(
    {"ReleaseClusterError", "initialize_release_cluster", "release_cluster_status"}
)
_DIRECT_PUBLICATION = frozenset({"publish_observation_generation"})
_REFRESH = frozenset(
    {
        "OpsRefreshError",
        "baseline_prune_to_jsonable",
        "baseline_save_to_jsonable",
        "drift_check_to_jsonable",
        "format_baseline_prune_table",
        "format_baseline_save_table",
        "format_drift_check_table",
        "format_graph_summary_table",
        "format_preflight_table",
        "format_refresh_result_table",
        "format_refresh_status_table",
        "graph_baseline_to_jsonable",
        "graph_summary_to_jsonable",
        "preflight_graph",
        "preflight_to_jsonable",
        "query_drift_check",
        "query_graph_summary",
        "query_refresh_status",
        "prune_graph_baselines",
        "refresh_enabled_graphs",
        "refresh_graph",
        "refresh_result_to_jsonable",
        "refresh_status_to_jsonable",
        "save_graph_baselines",
    }
)
POSTGRES_FACADE_NAMES = (
    _JOB_CONTROL
    | _LOCAL_LIFECYCLE
    | _LOCAL_MODE
    | _SERVICE_API
    | _MAINTENANCE
    | _RELEASE_CLUSTER
    | _DIRECT_PUBLICATION
    | _REFRESH
)


def load_postgres_facade_name(name: str) -> Any:
    """Import the owning module and return its current ``name``."""
    if name in _JOB_CONTROL:
        from repomap_kg.coordinator import job_control

        return getattr(job_control, name)
    if name in _LOCAL_LIFECYCLE:
        from repomap_kg.coordinator import local_lifecycle

        return getattr(local_lifecycle, name)
    if name in _LOCAL_MODE:
        from repomap_kg.coordinator import local_mode

        return getattr(local_mode, name)
    if name in _SERVICE_API:
        from repomap_kg.service_package import api

        return getattr(api, name)
    if name in _MAINTENANCE:
        from repomap_kg.runtime import maintenance

        return getattr(maintenance, name)
    if name in _RELEASE_CLUSTER:
        from repomap_kg.runtime import release_cluster

        return getattr(release_cluster, name)
    if name in _DIRECT_PUBLICATION:
        from repomap_kg.ops import direct_publication

        return getattr(direct_publication, name)
    if name in _REFRESH:
        from repomap_kg.ops import refresh

        return getattr(refresh, name)
    raise AttributeError(name)


def is_postgres_driver_missing(error: ModuleNotFoundError) -> bool:
    """True only when the missing module is the PostgreSQL driver itself."""
    return (error.name or "").split(".", 1)[0] in _DRIVER_MODULES


__all__ = (
    "POSTGRES_DRIVER_UNAVAILABLE",
    "POSTGRES_FACADE_NAMES",
    "is_postgres_driver_missing",
    "load_postgres_facade_name",
)
