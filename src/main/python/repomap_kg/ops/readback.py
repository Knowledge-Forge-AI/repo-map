"""Topology-preserving JSON readback for operational PostgreSQL queries."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from repomap_kg.ops.config_records import OpsConfig
from repomap_kg.ops.report_records import OpsPsqlExecution
from repomap_kg.ops.resolved_config import MAINTENANCE_DATABASE
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.readback_driver import (
    ExpectedJsonShape,
    JsonReadbackPayload,
    diagnose_psycopg_database_presence,
    execute_json_readback_with_driver,
    selected_json_readback_driver,
)

OpsJsonReadbackMode = Literal["host_only", "host_then_container"]
MISSING_DATABASE_MESSAGE = (
    "Postgres server is reachable, but the requested graph database is "
    "missing or not initialized. Initialize or restore the graph database "
    "before running MCP/ops readback."
)


class MissingDatabaseReadbackError(StorageSchemaError):
    """The selected server is reachable but the graph database is absent."""


@dataclass(frozen=True)
class _OpsContainerReadbackPlan:
    execution: OpsPsqlExecution | None
    unavailable_hint: str


def execute_ops_json_readback(
    config: OpsConfig,
    *,
    database: str,
    sql: str,
    label: str,
    expected_shape: ExpectedJsonShape,
    mode: OpsJsonReadbackMode,
    psql_command: str | None = None,
) -> JsonReadbackPayload:
    """Execute one operational JSON query with bounded topology fallback."""
    if mode not in ("host_only", "host_then_container"):
        raise StorageSchemaError(f"unsupported operational readback mode: {mode}")

    psql_args = config.postgres.psql_args_for_database(database)
    if psql_command is not None:
        try:
            return execute_json_readback_with_driver(
                sql,
                driver="psql",
                psql_args=psql_args,
                psql_command=psql_command,
                label=label,
                expected_shape=expected_shape,
            )
        except (OSError, StorageSchemaError) as error:
            raise _augment_host_error(
                error,
                driver="psql",
                label=label,
            ) from error

    driver = selected_json_readback_driver()
    try:
        return execute_json_readback_with_driver(
            sql,
            driver=driver,
            psql_args=psql_args,
            psql_command="psql",
            label=label,
            expected_shape=expected_shape,
        )
    except (OSError, StorageSchemaError) as error:
        if driver == "psycopg":
            topology_hint = (
                _psycopg_topology_hint(config)
                if _host_error_supports_container_fallback(error, driver=driver)
                else ""
            )
            raise _augment_host_error(
                error,
                driver=driver,
                label=label,
                topology_hint=topology_hint,
                config=config,
                database=database,
            ) from error
        if mode == "host_only" or not _host_error_supports_container_fallback(
            error,
            driver=driver,
        ):
            raise _augment_host_error(
                error,
                driver=driver,
                label=label,
                config=config,
                database=database,
            ) from error

        container_plan = _resolve_container_readback_plan(
            config,
            allow_loopback_host=True,
        )
        if container_plan.execution is None:
            raise _augment_host_error(
                error,
                driver=driver,
                label=label,
                topology_hint=container_plan.unavailable_hint,
            ) from error
        try:
            return execute_json_readback_with_driver(
                sql,
                driver="psql",
                psql_args=(*container_plan.execution.args_prefix, *psql_args),
                psql_command=container_plan.execution.command,
                label=label,
                expected_shape=expected_shape,
            )
        except (OSError, StorageSchemaError) as container_error:
            raise _augment_host_error(
                container_error,
                driver="psql",
                label=label,
            ) from container_error


def _internal_container_postgres_config(
    config: OpsConfig,
    *,
    allow_loopback_host: bool = False,
) -> bool:
    return (
        bool(config.config_home)
        and not config.runtime.postgres.direct_host_port_enabled
        and (
            allow_loopback_host
            or config.postgres.host not in ("127.0.0.1", "localhost", "::1")
        )
    )


def _runtime_plan(config: OpsConfig):
    from repomap_kg.runtime.local import build_local_runtime_plan

    return build_local_runtime_plan(
        Path(config.config_home or ""),
        allow_invalid_config=True,
    )


def _container_psql_hint(
    config: OpsConfig,
    *,
    allow_loopback_host: bool = False,
) -> str:
    if not _internal_container_postgres_config(
        config,
        allow_loopback_host=allow_loopback_host,
    ):
        return ""
    container_name = "repomap-postgres"
    if config.config_home:
        try:
            plan = _runtime_plan(config)
            container_name = plan.identity.postgres_container
        except Exception as error:
            if not _is_local_runtime_error(error):
                raise
    return _container_psql_hint_text(config, container_name)


def _container_psql_hint_text(config: OpsConfig, container_name: str) -> str:
    return (
        " Direct DB host-port exposure is disabled and configured Postgres "
        f"host {config.postgres.host!r} is container-internal; no running "
        f"RepoMap-owned Postgres container {container_name!r} was available. "
        "Start the local runtime, or explicitly enable local direct DB "
        "dev/debug exposure if appropriate."
    )


def _psycopg_topology_hint(config: OpsConfig) -> str:
    """Return guidance without planning or inspecting a fallback transport."""

    if not _internal_container_postgres_config(
        config,
        allow_loopback_host=True,
    ):
        return ""
    return _container_psql_hint_text(config, "repomap-postgres")


def _is_local_runtime_error(error: BaseException) -> bool:
    from repomap_kg.runtime.local import LocalRuntimeError

    return isinstance(error, LocalRuntimeError)


def _error_text(error: BaseException) -> str:
    return str(error) or error.__class__.__name__


def _psql_error_is_missing_database(error: BaseException) -> bool:
    text = _error_text(error).lower()
    return (
        "database" in text
        and "does not exist" in text
        and ("fatal:" in text or "psql failed" in text)
    )


def _psql_error_supports_container_fallback(error: BaseException) -> bool:
    if isinstance(error, OSError):
        return True
    if getattr(error, "supports_container_fallback", False) is True:
        return True
    text = _error_text(error).lower()
    return any(
        marker in text
        for marker in (
            "could not translate host name",
            "could not connect",
            "connection refused",
            "name or service not known",
            "nodename nor servname",
            "no such file or directory",
        )
    )


def _psycopg_error_details(
    error: BaseException,
) -> tuple[str | None, bool]:
    cause = error.__cause__
    if cause is None:
        return None, False
    sqlstate = getattr(cause, "sqlstate", None)
    is_operational = (
        cause.__class__.__name__ == "OperationalError"
        and cause.__class__.__module__.split(".", maxsplit=1)[0] == "psycopg"
    )
    return sqlstate if isinstance(sqlstate, str) else None, is_operational


def _host_error_supports_container_fallback(
    error: BaseException,
    *,
    driver: str,
) -> bool:
    if driver == "psql":
        return _psql_error_supports_container_fallback(error)
    sqlstate, is_operational = _psycopg_error_details(error)
    if sqlstate is not None:
        return sqlstate.startswith("08")
    return is_operational


def _container_psql_execution(config: OpsConfig) -> OpsPsqlExecution | None:
    return _resolve_container_readback_plan(config).execution


def _resolve_container_readback_plan(
    config: OpsConfig,
    *,
    allow_loopback_host: bool = False,
) -> _OpsContainerReadbackPlan:
    if not _internal_container_postgres_config(
        config,
        allow_loopback_host=allow_loopback_host,
    ) or not config.config_home:
        return _OpsContainerReadbackPlan(execution=None, unavailable_hint="")
    container_name = "repomap-postgres"
    try:
        plan = _runtime_plan(config)
    except Exception as error:
        if _is_local_runtime_error(error):
            return _OpsContainerReadbackPlan(
                execution=None,
                unavailable_hint=_container_psql_hint_text(config, container_name),
            )
        raise
    container_name = plan.identity.postgres_container
    unavailable_hint = _container_psql_hint_text(config, container_name)
    if shutil.which(plan.container_runtime) is None:
        return _OpsContainerReadbackPlan(
            execution=None,
            unavailable_hint=unavailable_hint,
        )
    from repomap_kg.runtime.local import inspect_container

    status = inspect_container(plan, "postgres", container_name)
    if status.exists and status.owned and status.status == "running":
        return _OpsContainerReadbackPlan(
            execution=OpsPsqlExecution(
                command=plan.container_runtime,
                args_prefix=("exec", "-i", container_name, "psql"),
                strategy="container",
            ),
            unavailable_hint="",
        )
    return _OpsContainerReadbackPlan(
        execution=None,
        unavailable_hint=unavailable_hint,
    )


def _missing_database_error() -> MissingDatabaseReadbackError:
    return MissingDatabaseReadbackError(MISSING_DATABASE_MESSAGE)


def _augment_psql_error(config: OpsConfig, error: BaseException) -> StorageSchemaError:
    return _psql_readback_error(
        error,
        topology_hint=_container_psql_hint(config),
    )


def _psql_readback_error(
    error: BaseException,
    *,
    topology_hint: str = "",
) -> StorageSchemaError:
    if _psql_error_is_missing_database(error):
        return _missing_database_error()
    return StorageSchemaError(f"{_error_text(error)}{topology_hint}")


def _augment_host_error(
    error: BaseException,
    *,
    driver: str,
    label: str,
    topology_hint: str = "",
    config: OpsConfig | None = None,
    database: str | None = None,
) -> StorageSchemaError:
    if driver == "psql":
        return _psql_readback_error(error, topology_hint=topology_hint)
    sqlstate, is_operational = _psycopg_error_details(error)
    if sqlstate == "3D000":
        return _missing_database_error()
    if sqlstate is not None and sqlstate.startswith("28"):
        return StorageSchemaError(f"psycopg authentication failed for {label}")
    if sqlstate is not None and sqlstate.startswith("08"):
        return StorageSchemaError(
            f"psycopg connection failed for {label}{topology_hint}"
        )
    if (
        config is not None
        and database is not None
        and database != str(MAINTENANCE_DATABASE)
        and getattr(error, "_readback_phase", None) == "connect"
        and sqlstate is None
        and is_operational
        and config.postgres.host
        and "," not in config.postgres.host
    ):
        maintenance_args = config.postgres.psql_args_for_database(
            str(MAINTENANCE_DATABASE)
        )
        presence = diagnose_psycopg_database_presence(
            psql_args=maintenance_args,
            target_database=database,
        )
        if presence == "absent":
            return _missing_database_error()
    if (sqlstate is not None and sqlstate.startswith("08")) or is_operational:
        return StorageSchemaError(
            f"psycopg connection failed for {label}{topology_hint}"
        )
    return StorageSchemaError(f"psycopg readback failed for {label}")
