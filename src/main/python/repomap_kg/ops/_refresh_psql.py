"""PSQL execution and storage readback helpers for RepoMap refresh operations."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from typing import Any, TypeVar

from repomap_kg.ops.config import OpsConfig
from repomap_kg.ops.readback import (
    _augment_psql_error,
    _container_psql_execution,
    _psql_error_supports_container_fallback,
)
from repomap_kg.ops.reports import OpsPsqlExecution
from repomap_kg.storage import LoadSummary, StorageSchemaError, run_psql
from repomap_kg.storage.backend_telemetry import BackendTelemetry
from repomap_kg.storage.publication import RunPublicationReceipt
from repomap_kg.storage.staged_ingestion import (
    IngestionAuthority,
    run_staged_full_refresh,
)
from repomap_kg.storage.staging_observability import StagingMeasurements

_StorageReadbackT = TypeVar("_StorageReadbackT")


def _dispatch_run_psql() -> Any:
    facade = sys.modules.get("repomap_kg.ops.refresh")
    return getattr(facade, "run_psql", run_psql) if facade is not None else run_psql


def _dispatch_container_exec(config: OpsConfig) -> Any:
    facade = sys.modules.get("repomap_kg.ops.refresh")
    fn = getattr(facade, "_container_psql_execution", _container_psql_execution) if facade is not None else _container_psql_execution
    return fn(config)


def _dispatch_staged_refresh() -> Any:
    facade = sys.modules.get("repomap_kg.ops.refresh")
    return getattr(facade, "run_staged_full_refresh", run_staged_full_refresh) if facade is not None else run_staged_full_refresh


def _ops_psql_tail_args() -> tuple[str, ...]:
    return ("-qAt", "-v", "ON_ERROR_STOP=1")


def _ops_psql_executions(
    config: OpsConfig,
    psql_command: str | None,
) -> tuple[OpsPsqlExecution, ...]:
    if psql_command is not None:
        return (OpsPsqlExecution(command=psql_command, strategy="explicit"),)
    return (OpsPsqlExecution(command="psql"),)


def _run_ops_psql(
    config: OpsConfig,
    database: str,
    *,
    psql_command: str | None,
    input_text: str,
) -> Any:
    psql_args = config.postgres.psql_args_for_database(database)
    executions = _ops_psql_executions(config, psql_command)
    run_psql_fn = _dispatch_run_psql()
    for execution in executions:
        try:
            return run_psql_fn(
                execution.full_command(psql_args, _ops_psql_tail_args()),
                input_text=input_text,
            )
        except (OSError, StorageSchemaError) as error:
            if psql_command is not None or not _psql_error_supports_container_fallback(
                error
            ):
                raise _augment_psql_error(config, error) from error
            container_execution = _dispatch_container_exec(config)
            if container_execution is None:
                raise _augment_psql_error(config, error) from error
            try:
                return run_psql_fn(
                    container_execution.full_command(
                        psql_args,
                        _ops_psql_tail_args(),
                    ),
                    input_text=input_text,
                )
            except (OSError, StorageSchemaError) as container_error:
                raise _augment_psql_error(config, container_error) from container_error
    raise _augment_psql_error(config, StorageSchemaError("psql failed"))


def _load_file_observations_with_ops_psql(
    config: OpsConfig,
    database: str,
    observations: Sequence[Any],
    *,
    repository_name: str,
    root_path: str,
    repository_identity: str,
    psql_command: str | None,
    publication_receipt: RunPublicationReceipt | None = None,
    ingestion_mode: str = "staged",
    staged_authority: IngestionAuthority | None = None,
    backend_telemetry: BackendTelemetry | None = None,
    staging_measurements: StagingMeasurements | None = None,
) -> LoadSummary:
    psql_args = config.postgres.psql_args_for_database(database)
    if ingestion_mode != "staged":
        raise ValueError("refresh ingestion mode is invalid")
    if staged_authority is None:
        raise StorageSchemaError("staged refresh authority is missing")
    if (
        publication_receipt is not None
        and staged_authority.receipt() != publication_receipt
    ):
        raise StorageSchemaError("staged refresh receipt authority mismatch")
    return _dispatch_staged_refresh()(
        psql_args,
        observations,
        repository_name=repository_name,
        root_path=root_path,
        authority=staged_authority,
        repository_identity=repository_identity,
        backend_telemetry=backend_telemetry,
        staging_measurements=staging_measurements,
    )


def run_storage_readback_with_ops_psql(
    config: OpsConfig,
    database: str,
    storage_query: Callable[..., _StorageReadbackT],
    *,
    psql_command: str | None,
    **query_kwargs: Any,
) -> _StorageReadbackT:
    psql_args = config.postgres.psql_args_for_database(database)
    executions = _ops_psql_executions(config, psql_command)
    for execution in executions:
        try:
            return storage_query(
                [*execution.args_prefix, *psql_args],
                psql_command=execution.command,
                **query_kwargs,
            )
        except (OSError, StorageSchemaError) as error:
            if psql_command is not None or not _psql_error_supports_container_fallback(
                error
            ):
                raise _augment_psql_error(config, error) from error
            container_execution = _dispatch_container_exec(config)
            if container_execution is None:
                raise _augment_psql_error(config, error) from error
            try:
                return storage_query(
                    [*container_execution.args_prefix, *psql_args],
                    psql_command=container_execution.command,
                    **query_kwargs,
                )
            except (OSError, StorageSchemaError) as container_error:
                raise _augment_psql_error(config, container_error) from container_error
    raise _augment_psql_error(config, StorageSchemaError("psql failed"))
