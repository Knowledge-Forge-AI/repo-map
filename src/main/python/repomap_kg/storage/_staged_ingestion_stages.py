"""Internal stage lifecycle and copy execution helpers for staged ingestion."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from datetime import datetime, timedelta
import signal
from threading import current_thread, main_thread
from typing import Any, NoReturn

import psycopg
from psycopg.types.json import Jsonb

from repomap_kg.observations.raw import RawObservation
from repomap_kg.storage.authority import GraphRunId, StageId
from repomap_kg.storage.backend_telemetry import BackendTelemetry
from repomap_kg.storage.errors import (
    StorageCommitUnknownError,
    StorageSchemaError,
)
from repomap_kg.storage.main import LoadSummary
from repomap_kg.storage.publication import RunPublicationReceipt
from repomap_kg.storage.publication_fencing import PublicationHandoff
from repomap_kg.storage.repository_identity import validate_repository_identity
from repomap_kg.storage.row_spool import RowSpool
from repomap_kg.storage.staged_connection_telemetry import close_owned_connection
from repomap_kg.storage.staged_publication import (
    mark_failed_before_publication,
    publication_run,
    reconcile_commit_unknown,
)
from repomap_kg.storage.staged_rows import PreparedStageRows, build_staged_rows
from repomap_kg.storage.staged_validation import (
    mark_validated,
    mark_validating,
    validate_stage,
)
from repomap_kg.storage.staging_copy import STAGING_COPY_TABLES, copy_stage_rows
from repomap_kg.storage.staging_family_contracts import STAGING_FAMILY_DESCRIPTORS
from repomap_kg.storage.staging_merge import MergeContext
from repomap_kg.storage.staging_observability import (
    StagingMeasurementCategory,
    StagingMeasurements,
)
from repomap_kg.storage.staging_ownership import StageOwner

__all__ = (
    "_DEFAULT_STAGE_TTL",
    "_copy_families",
    "_create_run",
    "_create_stage",
    "_ensure_repository",
    "_handle_existing_stage_state",
    "_handle_refresh_failure",
    "_install_connection_signal_handlers",
    "_mark_prepared",
    "_populate_and_mark_stage",
    "_refresh_canonical_node_evidence_statistics",
    "_resolve_prepared_rows",
    "_restore_connection_signal_handlers",
    "_validate_and_commit_stage",
)

_DEFAULT_STAGE_TTL = timedelta(hours=24)
_SIGNAL_CANCEL_TIMEOUT = 1.0


def _install_connection_signal_handlers(connection: Any) -> dict[int, Any]:
    """Request bounded server cancellation before a process signal exits."""
    if current_thread() is not main_thread():
        return {}
    previous: dict[int, Any] = {}

    def cancel_connection(_number: int, _frame: Any) -> None:
        try:
            connection.cancel_safe(timeout=_SIGNAL_CANCEL_TIMEOUT)
        except Exception:
            try:
                connection.cancel()
            except Exception:
                pass
        raise KeyboardInterrupt

    try:
        for signal_number in (signal.SIGINT, signal.SIGTERM):
            previous[signal_number] = signal.getsignal(signal_number)
            signal.signal(signal_number, cancel_connection)
    except Exception:
        _restore_connection_signal_handlers(previous)
        raise
    return previous


def _restore_connection_signal_handlers(previous: Mapping[int, Any]) -> None:
    """Restore process signal handlers after one graph operation."""
    for signal_number, handler in previous.items():
        signal.signal(signal_number, handler)


def _ensure_repository(
    connection: Any,
    name: str,
    root_path: str,
    repository_identity: str | None = None,
) -> int:
    values: tuple[str, ...]
    if repository_identity is None:
        sql = (
            "INSERT INTO repositories(name, root_path) VALUES (%s, %s) "
            "ON CONFLICT (root_path) DO UPDATE SET name = EXCLUDED.name RETURNING id"
        )
        values = (name, root_path)
    else:
        validate_repository_identity(repository_identity)
        sql = (
            "INSERT INTO repositories(name, root_path, repository_identity) VALUES (%s, %s, %s) "
            "ON CONFLICT (repository_identity) WHERE repository_identity IS NOT NULL "
            "DO UPDATE SET name = EXCLUDED.name, root_path = EXCLUDED.root_path RETURNING id"
        )
        values = (name, root_path, repository_identity)
    row = connection.execute(sql, values).fetchone()
    if row is None:
        raise StorageSchemaError("staged repository identity was not returned")
    return int(row[0])


def _create_run(
    connection: Any,
    repository_id: int,
    git_commit: str | None,
) -> GraphRunId:
    sql = "INSERT INTO runs(repository_id, git_commit, status) VALUES (%s, %s, 'running') RETURNING id"
    row = connection.execute(sql, (repository_id, git_commit)).fetchone()
    if row is None:
        raise StorageSchemaError("staged run identity was not returned")
    return GraphRunId(int(row[0]))


def _create_stage(
    connection: Any,
    stage_id: StageId,
    owner: StageOwner,
    prepared: PreparedStageRows,
    *,
    expires_at: datetime,
) -> None:
    checksums = {
        family: asdict(checksum) for family, checksum in prepared.checksums.items()
    }
    manifest = {"schema_version": 1, "families": list(STAGING_FAMILY_DESCRIPTORS)}
    sql = (
        "INSERT INTO ingestion_stages("
        "stage_id, repository_id, operation_id, job_id, attempt, execution_mode, "
        "coordinator_instance_id, singleton_fencing_epoch, graph_lease_fencing_epoch, "
        "source_generation, config_generation, extractor_generation, canonicalizer_generation, "
        "expires_at, expected_family_manifest, expected_row_counts, family_checksums, "
        "normalized_byte_counts) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
    )
    connection.execute(
        sql,
        (
            stage_id,
            owner.repository_id,
            owner.operation_id,
            owner.job_id,
            owner.attempt,
            owner.execution_mode,
            owner.coordinator_instance_id,
            owner.singleton_fencing_epoch,
            owner.graph_lease_fencing_epoch,
            owner.source_generation,
            owner.config_generation,
            owner.extractor_generation,
            owner.canonicalizer_generation,
            expires_at,
            Jsonb(manifest),
            Jsonb(dict(prepared.row_counts)),
            Jsonb(checksums),
            Jsonb(dict(prepared.normalized_byte_counts)),
        ),
    )


def _copy_families(
    connection: Any,
    prepared: PreparedStageRows,
    stage_id: str,
    *,
    staging_measurements: StagingMeasurements | None = None,
) -> None:
    for family in STAGING_FAMILY_DESCRIPTORS:
        rows = prepared.family_rows[family]
        if staging_measurements is None:
            copy_stage_rows(connection, STAGING_COPY_TABLES[family], rows, expected_stage_id=stage_id)
        else:
            with staging_measurements.timed(StagingMeasurementCategory.COPY, family=family):
                with staging_measurements.phase(f"staging.family_copy.{family}"):
                    copy_stage_rows(connection, STAGING_COPY_TABLES[family], rows, expected_stage_id=stage_id)
        if isinstance(rows, RowSpool):
            rows.close()


def _refresh_canonical_node_evidence_statistics(connection: Any) -> None:
    connection.execute("ANALYZE stage_canonical_node_evidence")


def _mark_prepared(connection: Any, stage_id: str, counts: Mapping[str, int]) -> None:
    cursor = connection.execute(
        "UPDATE ingestion_stages SET state = 'prepared', observed_row_counts = %s, updated_at = now() "
        "WHERE stage_id = %s AND state = 'loading'",
        (Jsonb(dict(counts)), stage_id),
    )
    if cursor.rowcount != 1:
        raise StorageSchemaError("staged prepared transition failed")


def _resolve_prepared_rows(
    prepared_override: PreparedStageRows | None,
    observations: Sequence[RawObservation],
    repository_name: str,
    resolved_stage_id: StageId,
    staging_measurements: StagingMeasurements | None,
) -> PreparedStageRows:
    """Build or adopt stage rows for ingestion."""
    if prepared_override is not None:
        return prepared_override
    if staging_measurements is None:
        return build_staged_rows(
            observations,
            repository_name=repository_name,
            stage_id=resolved_stage_id,
            staging_measurements=None,
        )
    with staging_measurements.phase("refresh.staged_row_build"):
        return build_staged_rows(
            observations,
            repository_name=repository_name,
            stage_id=resolved_stage_id,
            staging_measurements=staging_measurements,
        )


def _populate_and_mark_stage(
    connection: Any,
    prepared: PreparedStageRows,
    resolved_stage_id: str,
    *,
    staging_measurements: StagingMeasurements | None = None,
) -> None:
    """Copy staging families, analyze evidence table, mark prepared, and commit."""
    _copy_families(
        connection,
        prepared,
        resolved_stage_id,
        staging_measurements=staging_measurements,
    )
    if staging_measurements is None:
        _refresh_canonical_node_evidence_statistics(connection)
    else:
        with staging_measurements.timed(StagingMeasurementCategory.STATISTICS):
            with staging_measurements.operation("statistics.canonical_node_evidence"):
                _refresh_canonical_node_evidence_statistics(connection)
    _mark_prepared(connection, resolved_stage_id, prepared.row_counts)
    connection.commit()


def _validate_and_commit_stage(
    connection: Any,
    resolved_stage_id: StageId,
    row_counts: Mapping[str, int],
    staging_measurements: StagingMeasurements | None,
) -> None:
    """Run stage validation and commit the pre-publication transaction."""
    if staging_measurements is None:
        mark_validating(connection, resolved_stage_id)
        validate_stage(connection, resolved_stage_id, row_counts)
        mark_validated(connection, resolved_stage_id)
        connection.commit()
    else:
        with staging_measurements.timed(StagingMeasurementCategory.COMPLETENESS_VALIDATION):
            mark_validating(connection, resolved_stage_id)
            validate_stage(
                connection,
                resolved_stage_id,
                row_counts,
                staging_measurements=staging_measurements,
            )
            mark_validated(connection, resolved_stage_id)
        with staging_measurements.phase("staging.pre_final_commit"):
            connection.commit()


def _handle_existing_stage_state(
    *,
    connection: Any,
    connection_factory: Callable[..., Any],
    params: Mapping[str, object],
    existing_state: str,
    resolved_stage_id: StageId,
    owner: StageOwner,
    repository_id: int,
    receipt: RunPublicationReceipt,
    prepared_files: int,
    signal_handlers: dict[int, Any],
    backend_telemetry: BackendTelemetry | None = None,
) -> LoadSummary:
    """Handle existing stage state if one is already recorded."""
    if existing_state == "published":
        existing_run = publication_run(
            connection, repository_id, receipt, complete_only=True
        )
        if existing_run is None:
            raise StorageSchemaError("staged published receipt is missing")
        connection.rollback()
        return LoadSummary(
            repository_id=repository_id,
            run_id=existing_run[0],
            files=prepared_files,
            publication_receipt=receipt,
        )
    if existing_state == "commit_unknown":
        existing_run = publication_run(
            connection, repository_id, receipt, complete_only=False
        )
        if existing_run is None:
            raise StorageSchemaError("staged commit-unknown run is missing")
        handoff = PublicationHandoff(
            MergeContext(resolved_stage_id, owner, existing_run[0]),
            receipt,
        ).validate()
        _restore_connection_signal_handlers(signal_handlers)
        signal_handlers.clear()
        connection.rollback()
        close_owned_connection(connection)
        if reconcile_commit_unknown(
            connection_factory,
            params,
            handoff,
            repository_id,
            backend_telemetry=backend_telemetry,
        ):
            return LoadSummary(
                repository_id=repository_id,
                run_id=existing_run[0],
                files=prepared_files,
                publication_receipt=receipt,
            )
        raise StorageCommitUnknownError("staged publication commit is unknown")
    if existing_state in {
        "loading",
        "prepared",
        "validating",
        "validated",
        "merging",
    }:
        raise StorageSchemaError("staged operation is already active")
    raise StorageSchemaError("staged operation cannot be replayed")


def _handle_refresh_failure(
    connection: Any,
    error: BaseException,
    *,
    handoff: PublicationHandoff | None,
    stage_committed: bool,
    owner: StageOwner | None,
    resolved_stage_id: StageId,
    run_id: int | None,
) -> NoReturn:
    """Handle rollback, failed state marking, and error wrapping on failure."""
    if handoff is None and connection is not None:
        try:
            connection.rollback()
            if stage_committed and owner is not None and run_id is not None:
                mark_failed_before_publication(
                    connection, resolved_stage_id, run_id, owner
                )
                connection.commit()
        except Exception:
            try:
                connection.rollback()
            except Exception:
                pass
    if isinstance(error, psycopg.Error):
        raise StorageSchemaError("staged PostgreSQL operation failed") from error
    raise error
