"""Caller-owned SCALE staged ingestion and final publication orchestration."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

import signal as signal

import psycopg

from repomap_kg.artifacts.bundle import PublicationBundle
from repomap_kg.observations.raw import RawObservation
from repomap_kg.runtime.maintenance import maintenance_activity
from repomap_kg.storage._staged_ingestion_authority import (
    IngestionAuthority,
    new_direct_authority,
    stage_id_for_authority,
)
from repomap_kg.storage._staged_ingestion_stages import (
    _DEFAULT_STAGE_TTL,
    _copy_families as _copy_families,
    _create_run as _create_run,
    _create_stage as _create_stage,
    _ensure_repository as _ensure_repository,
    _handle_existing_stage_state,
    _handle_refresh_failure,
    _install_connection_signal_handlers as _install_connection_signal_handlers,
    _mark_prepared as _mark_prepared,
    _refresh_canonical_node_evidence_statistics as _refresh_canonical_node_evidence_statistics,
    _resolve_prepared_rows,
    _restore_connection_signal_handlers as _restore_connection_signal_handlers,
)
from repomap_kg.storage.authority import StageId
from repomap_kg.storage.backend_ownership import ConnectionRole
from repomap_kg.storage.backend_telemetry import BackendTelemetry
from repomap_kg.storage.errors import (
    StorageCommitUnknownError,
    StorageSchemaError,
)
from repomap_kg.storage.main import LoadSummary
from repomap_kg.storage.portable_ingestion import prepare_portable_bundle_rows
from repomap_kg.storage.publication import (
    PortablePublicationBinding,
    RunPublicationReceipt,
)
from repomap_kg.storage.publication_fencing import (
    PublicationHandoff,
    build_graph_publication_claim_statements,
)
from repomap_kg.storage.readback_driver import (
    _psycopg_connection_params_from_psql_args as _psycopg_connection_params_from_psql_args,
)
from repomap_kg.storage.staged_connection_telemetry import (
    close_owned_connection,
    open_owned_connection,
)
from repomap_kg.storage.staged_publication import (
    _execute,
    execute_final_transaction as execute_final_transaction,
    existing_stage_state,
    mark_failed_before_publication,
    reconcile_commit_unknown,
)
from repomap_kg.storage.staged_rows import PreparedStageRows, build_staged_rows
from repomap_kg.storage.staged_validation import (
    mark_validated as mark_validated,
    mark_validating as mark_validating,
    validate_stage as validate_stage,
)
from repomap_kg.storage.staging_copy import copy_stage_rows as copy_stage_rows
from repomap_kg.storage.staging_merge import MergeContext
from repomap_kg.storage.staging_observability import (
    StagingMeasurementCategory,
    StagingMeasurements,
)
from repomap_kg.storage.staging_ownership import StageOwner
from repomap_kg.storage.staging_resource_observability import (
    capture_staging_resources,
    emit_staging_resource_measurements,
)

__all__ = (
    "IngestionAuthority",
    "build_staged_rows",
    "new_direct_authority",
    "run_staged_full_refresh",
    "run_staged_portable_refresh",
    "stage_id_for_authority",
)



def _admit_and_run(
    psql_args: Sequence[str],
    authority: IngestionAuthority,
    backend_telemetry: BackendTelemetry | None,
    runner: Callable[[], LoadSummary],
) -> LoadSummary:
    authority.validate()
    if backend_telemetry is not None and authority.execution_mode != "direct":
        raise StorageSchemaError("backend ownership telemetry requires direct mode")
    params = _psycopg_connection_params_from_psql_args(psql_args)
    try:
        with maintenance_activity(
            lambda: open_owned_connection(
                psycopg.connect,
                params,
                role=ConnectionRole.DIRECT_MAINTENANCE_ADMISSION,
                telemetry=backend_telemetry,
            )
        ):
            return runner()
    except psycopg.Error as error:
        raise StorageSchemaError("staged PostgreSQL connection failed") from error


def run_staged_full_refresh(
    psql_args: Sequence[str],
    observations: Sequence[RawObservation],
    *,
    repository_name: str,
    root_path: str,
    authority: IngestionAuthority,
    repository_identity: str | None = None,
    git_commit: str | None = None,
    stage_id: str | None = None,
    stage_ttl: timedelta = _DEFAULT_STAGE_TTL,
    connect: Callable[..., Any] | None = None,
    backend_telemetry: BackendTelemetry | None = None,
    staging_measurements: StagingMeasurements | None = None,
) -> LoadSummary:
    """Run COPY, set-based merge, and receipt-bearing publication once."""
    if stage_ttl <= timedelta(0):
        raise ValueError("staged ingestion expiry must be positive")
    return _admit_and_run(
        psql_args,
        authority,
        backend_telemetry,
        lambda: _run_staged_full_refresh_admitted(
            psql_args,
            observations,
            repository_name=repository_name,
            root_path=root_path,
            authority=authority,
            repository_identity=repository_identity,
            git_commit=git_commit,
            stage_id=stage_id,
            stage_ttl=stage_ttl,
            connect=connect,
            backend_telemetry=backend_telemetry,
            staging_measurements=staging_measurements,
        ),
    )


def run_staged_portable_refresh(
    psql_args: Sequence[str],
    bundle: PublicationBundle,
    *,
    repository_name: str,
    root_path: str,
    authority: IngestionAuthority,
    portable_binding: PortablePublicationBinding,
    repository_identity: str | None = None,
    connect: Callable[..., Any] | None = None,
    backend_telemetry: BackendTelemetry | None = None,
    staging_measurements: StagingMeasurements | None = None,
) -> LoadSummary:
    """Publish one validated current bundle through the existing sole writer."""
    stage_id = stage_id_for_authority(authority)
    if (
        portable_binding.stage_id != stage_id
        or portable_binding.execution_mode != authority.execution_mode
        or portable_binding.singleton_fencing_epoch != authority.singleton_fencing_epoch
        or portable_binding.graph_lease_fencing_epoch != authority.graph_lease_fencing_epoch
    ):
        raise StorageSchemaError("portable publication authority mismatch")
    prepared = prepare_portable_bundle_rows(bundle, stage_id=stage_id)
    receipt = RunPublicationReceipt(
        authority.receipt().attempt,
        authority.receipt().generations,
        portable_binding,
    ).validate()
    try:
        return _admit_and_run(
            psql_args,
            authority,
            backend_telemetry,
            lambda: _run_staged_full_refresh_admitted(
                psql_args,
                (),
                repository_name=repository_name,
                root_path=root_path,
                authority=authority,
                repository_identity=repository_identity,
                stage_id=stage_id,
                connect=connect,
                backend_telemetry=backend_telemetry,
                staging_measurements=staging_measurements,
                prepared_override=prepared,
                receipt_override=receipt,
            ),
        )
    except BaseException:
        prepared.close()
        raise


def _run_staged_full_refresh_admitted(
    psql_args: Sequence[str],
    observations: Sequence[RawObservation],
    *,
    repository_name: str,
    root_path: str,
    authority: IngestionAuthority,
    repository_identity: str | None = None,
    git_commit: str | None = None,
    stage_id: str | None = None,
    stage_ttl: timedelta = _DEFAULT_STAGE_TTL,
    connect: Callable[..., Any] | None = None,
    backend_telemetry: BackendTelemetry | None = None,
    staging_measurements: StagingMeasurements | None = None,
    prepared_override: PreparedStageRows | None = None,
    receipt_override: RunPublicationReceipt | None = None,
) -> LoadSummary:
    """Execute one staged publication after maintenance admission."""
    authority.validate()
    if backend_telemetry is not None and authority.execution_mode != "direct":
        raise StorageSchemaError("backend ownership telemetry requires direct mode")
    if stage_ttl <= timedelta(0):
        raise ValueError("staged ingestion expiry must be positive")
    resolved_stage_id = StageId(stage_id) if stage_id else stage_id_for_authority(authority)
    prepared = _resolve_prepared_rows(
        prepared_override, observations, repository_name, resolved_stage_id, staging_measurements
    )
    try:
        params = _psycopg_connection_params_from_psql_args(psql_args)
    except BaseException:
        prepared.close()
        raise
    connection_factory = connect or psycopg.connect
    try:
        connection = open_owned_connection(
            connection_factory, params, role=ConnectionRole.DIRECT_STAGED_REFRESH, telemetry=backend_telemetry
        )
    except psycopg.Error as error:
        prepared.close()
        raise StorageSchemaError("staged PostgreSQL connection failed") from error
    except BaseException:
        prepared.close()
        raise
    signal_handlers: dict[int, Any] = {}
    try:
        signal_handlers = _install_connection_signal_handlers(connection)
    except BaseException:
        close_owned_connection(connection)
        prepared.close()
        raise
    resources_before = capture_staging_resources(connection) if staging_measurements is not None else None
    handoff: PublicationHandoff | None = None
    repository_id: int | None = None
    run_id: int | None = None
    stage_committed = False
    transaction_committed = False
    owner: StageOwner | None = None
    try:
        repository_id = _ensure_repository(connection, repository_name, root_path, repository_identity)
        owner = authority.owner(repository_id)
        receipt = receipt_override or authority.receipt()
        existing_state = existing_stage_state(connection, resolved_stage_id, owner)
        if existing_state is not None:
            return _handle_existing_stage_state(
                connection=connection,
                connection_factory=connection_factory,
                params=params,
                existing_state=existing_state,
                resolved_stage_id=resolved_stage_id,
                owner=owner,
                repository_id=repository_id,
                receipt=receipt,
                prepared_files=prepared.files,
                signal_handlers=signal_handlers,
                backend_telemetry=backend_telemetry,
            )
        run_id = _create_run(connection, repository_id, git_commit)
        _create_stage(
            connection,
            resolved_stage_id,
            owner,
            prepared,
            expires_at=datetime.now(timezone.utc) + stage_ttl,
        )
        _execute(connection, build_graph_publication_claim_statements(MergeContext(resolved_stage_id, owner, run_id)))
        connection.commit()
        stage_committed = True

        _copy_families(connection, prepared, resolved_stage_id, staging_measurements=staging_measurements)
        if staging_measurements is None:
            _refresh_canonical_node_evidence_statistics(connection)
        else:
            with staging_measurements.timed(StagingMeasurementCategory.STATISTICS):
                with staging_measurements.operation("statistics.canonical_node_evidence"):
                    _refresh_canonical_node_evidence_statistics(connection)
        _mark_prepared(connection, resolved_stage_id, prepared.row_counts)
        connection.commit()
        if staging_measurements is None:
            mark_validating(connection, resolved_stage_id)
            validate_stage(connection, resolved_stage_id, prepared.row_counts)
            mark_validated(connection, resolved_stage_id)
            connection.commit()
        else:
            with staging_measurements.timed(StagingMeasurementCategory.COMPLETENESS_VALIDATION):
                mark_validating(connection, resolved_stage_id)
                validate_stage(connection, resolved_stage_id, prepared.row_counts, staging_measurements=staging_measurements)
                mark_validated(connection, resolved_stage_id)
            with staging_measurements.phase("staging.pre_final_commit"):
                connection.commit()

        handoff = PublicationHandoff(MergeContext(resolved_stage_id, owner, run_id), receipt).validate()
        try:
            execute_final_transaction(connection, handoff, staging_measurements=staging_measurements)
        except (Exception, KeyboardInterrupt):
            connection.rollback()
            mark_failed_before_publication(connection, resolved_stage_id, run_id, owner)
            connection.commit()
            raise
        try:
            if staging_measurements is None:
                connection.commit()
            else:
                with staging_measurements.operation("transaction.commit"):
                    connection.commit()
            transaction_committed = True
        except (Exception, KeyboardInterrupt) as error:
            _restore_connection_signal_handlers(signal_handlers)
            signal_handlers = {}
            close_owned_connection(connection)
            connection = None
            if reconcile_commit_unknown(
                connection_factory, params, handoff, repository_id, backend_telemetry=backend_telemetry
            ):
                return LoadSummary(
                    repository_id=repository_id,
                    run_id=run_id,
                    files=prepared.files,
                    publication_receipt=handoff.receipt,
                )
            raise StorageCommitUnknownError("staged publication commit is unknown") from error
        if staging_measurements is not None and resources_before is not None:
            emit_staging_resource_measurements(
                staging_measurements, resources_before, capture_staging_resources(connection)
            )
        return LoadSummary(
            repository_id=repository_id,
            run_id=run_id,
            files=prepared.files,
            publication_receipt=handoff.receipt,
        )
    except (Exception, KeyboardInterrupt) as error:
        if transaction_committed:
            raise StorageCommitUnknownError("post-transaction failure occurred after publication commit") from error
        _handle_refresh_failure(
            connection,
            error,
            handoff=handoff,
            stage_committed=stage_committed,
            owner=owner,
            resolved_stage_id=resolved_stage_id,
            run_id=run_id,
        )
    finally:
        _restore_connection_signal_handlers(signal_handlers)
        prepared.close()
        if connection is not None:
            close_owned_connection(connection)
