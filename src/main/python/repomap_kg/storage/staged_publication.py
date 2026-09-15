"""SCALE final-transaction and commit-unknown publication helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from itertools import groupby
from typing import Any

from repomap_kg.storage.backend_ownership import ConnectionRole
from repomap_kg.storage.backend_telemetry import BackendTelemetry
from repomap_kg.storage.canonical_staging_merge import build_canonical_merge_statements
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.publication_fencing import (
    PublicationHandoff, PublicationReconciliationOutcome,
    build_publication_finalize_statements, build_publication_prepare_statements,
    build_publication_reconciliation_statements, classify_publication_marker,
)
from repomap_kg.storage.publication import PortablePublicationBinding, RunPublicationReceipt
from repomap_kg.storage.staging_merge import build_source_index_merge_statements
from repomap_kg.storage.staging_family_catalog import merge_operations_for_scope
from repomap_kg.storage.staging_merge_operations import MergeScope
from repomap_kg.storage.staging_observability import (
    StagingMeasurementCategory, StagingMeasurements,
)
from repomap_kg.storage.staging_operation_contracts import operation_code_for_merge
from repomap_kg.storage.staging_ownership import StageOwner
from repomap_kg.storage.staged_connection_telemetry import (
    close_owned_connection, open_owned_connection,
)


_DIRECT_LOCK_CLASS = 19042


def existing_stage_state(
    connection: Any, stage_id: str, owner: StageOwner
) -> str | None:
    """Return one exact owner's stage state, rejecting mismatched ownership."""

    row = connection.execute(
        "SELECT repository_id, operation_id, job_id, attempt, execution_mode, "
        "coordinator_instance_id, singleton_fencing_epoch, graph_lease_fencing_epoch, "
        "source_generation, config_generation, extractor_generation, "
        "canonicalizer_generation, state FROM ingestion_stages WHERE stage_id = %s",
        (stage_id,),
    ).fetchone()
    if row is None:
        return None
    actual = tuple(row[:12])
    expected = (
        owner.repository_id, owner.operation_id, owner.job_id, owner.attempt,
        owner.execution_mode, owner.coordinator_instance_id,
        owner.singleton_fencing_epoch, owner.graph_lease_fencing_epoch,
        owner.source_generation, owner.config_generation,
        owner.extractor_generation, owner.canonicalizer_generation,
    )
    if actual != expected:
        raise StorageSchemaError("staged stage ownership mismatch")
    return str(row[12])


def publication_run(
    connection: Any,
    repository_id: int,
    receipt: RunPublicationReceipt,
    *,
    complete_only: bool,
) -> tuple[int, str] | None:
    """Find one run carrying an exact receipt identity and generations."""

    receipt.validate()
    status_clause = "AND status = 'complete'" if complete_only else ""
    portable_clause = ""
    portable_values: tuple[Any, ...] = ()
    if receipt.portable is not None:
        mapping = receipt.portable.to_mapping()
        portable_clause = " " + " ".join(
            f"AND {col} = %s" for col in receipt.portable.field_names()
        )
        portable_values = tuple(mapping[col] for col in receipt.portable.field_names())
    row = connection.execute(
        f"""
SELECT id, status
FROM runs
WHERE repository_id = %s
  AND publication_job_id = %s
  AND publication_attempt = %s
  AND source_generation = %s
  AND config_generation = %s
  AND extractor_generation = %s
  AND canonicalizer_generation = %s
  {portable_clause}
  {status_clause}
ORDER BY id DESC
LIMIT 1
""",
        (
            repository_id, receipt.attempt.job_id, receipt.attempt.attempt,
            *receipt.generations.values(), *portable_values,
        ),
    ).fetchone()
    if row is None:
        return None
    return int(row[0]), str(row[1])


def execute_final_transaction(
    connection: Any,
    handoff: PublicationHandoff,
    *,
    staging_measurements: StagingMeasurements | None = None,
) -> None:
    """Run the final graph mutation and receipt statements in one transaction."""

    owner = handoff.merge.owner
    lock = connection.execute(
        "SELECT pg_try_advisory_xact_lock(%s, %s)",
        (_DIRECT_LOCK_CLASS, owner.repository_id),
    ).fetchone()
    if lock is None or lock[0] is not True:
        raise StorageSchemaError("graph publication already active")
    if staging_measurements is None:
        _execute(connection, build_publication_prepare_statements(handoff))
        _execute(connection, build_source_index_merge_statements(handoff.merge))
        _execute(connection, build_canonical_merge_statements(handoff.merge))
        _execute(connection, build_publication_finalize_statements(handoff))
        return
    prepare = build_publication_prepare_statements(handoff)
    if len(prepare) != 2:
        raise StorageSchemaError("staged prepare measurement contract is invalid")
    with staging_measurements.timed(StagingMeasurementCategory.SEMANTIC_GUARD):
        for operation_code, statement in zip(
            ("guard.publication_prepare", "transaction.mark_merging"),
            prepare,
            strict=True,
        ):
            with staging_measurements.operation(operation_code):
                _execute(connection, (statement,))
    _execute_measured_merge(
        connection, build_source_index_merge_statements(handoff.merge),
        MergeScope.SOURCE_INDEX, staging_measurements,
    )
    _execute_measured_merge(
        connection, build_canonical_merge_statements(handoff.merge),
        MergeScope.CANONICAL, staging_measurements,
    )
    finalize = build_publication_finalize_statements(handoff)
    if len(finalize) != 2:
        raise StorageSchemaError("staged finalize measurement contract is invalid")
    with staging_measurements.timed(StagingMeasurementCategory.RECEIPT):
        for operation_code, statement in zip(
            ("guard.publication_finalize", "receipt.finalize"),
            finalize,
            strict=True,
        ):
            with staging_measurements.operation(operation_code):
                _execute(connection, (statement,))


def _execute_measured_merge(
    connection: Any,
    statements: tuple[str, ...],
    scope: MergeScope,
    measurements: StagingMeasurements,
) -> None:
    bindings = merge_operations_for_scope(scope)
    if len(statements) != len(bindings) + 2:
        raise StorageSchemaError("staged merge measurement contract is invalid")
    prefix_codes = {
        MergeScope.SOURCE_INDEX: ("guard.source_index_stage", "guard.source_index_proposals"),
        MergeScope.CANONICAL: ("guard.canonical_stage", "guard.canonical_proposals"),
    }[scope]
    with measurements.timed(StagingMeasurementCategory.SEMANTIC_GUARD):
        for operation_code, statement in zip(prefix_codes, statements[:2], strict=True):
            with measurements.operation(operation_code):
                _execute(connection, (statement,))
    paired = zip(bindings, statements[2:], strict=True)
    for is_guard, group in groupby(
        paired,
        key=lambda item: "REFERENCE" in item[0].operation.name,
    ):
        category = (
            StagingMeasurementCategory.SEMANTIC_GUARD
            if is_guard
            else StagingMeasurementCategory.MERGE
        )
        operation_group = tuple(group)
        with measurements.timed(category):
            for binding, statement in operation_group:
                with measurements.operation(
                    operation_code_for_merge(binding.operation)
                ):
                    _execute(connection, (statement,))


def reconcile_commit_unknown(
    connection_factory: Callable[..., Any],
    params: Mapping[str, object],
    handoff: PublicationHandoff,
    repository_id: int,
    *,
    backend_telemetry: BackendTelemetry | None = None,
) -> bool:
    """Reconcile a final commit through the graph-local receipt marker."""

    if handoff.merge.owner.repository_id != repository_id:
        raise StorageSchemaError("staged stage ownership mismatch")
    connection = open_owned_connection(
        connection_factory,
        params,
        role=ConnectionRole.COMMIT_RECONCILIATION,
        telemetry=backend_telemetry,
    )
    try:
        marker = _publication_marker(
            connection,
            repository_id,
            handoff.merge.run_id,
        )
        outcome = classify_publication_marker(handoff, marker)
        if outcome is PublicationReconciliationOutcome.MATCHING_COMMITTED:
            _execute(
                connection,
                build_publication_reconciliation_statements(handoff, outcome),
            )
            connection.commit()
            return True
        if outcome is PublicationReconciliationOutcome.CONFLICTING:
            owner = handoff.merge.owner
            stage_row = connection.execute(
                "SELECT state FROM ingestion_stages "
                "WHERE stage_id = %s AND repository_id = %s",
                (handoff.merge.stage_id, owner.repository_id),
            ).fetchone()
            run_row = connection.execute(
                "SELECT status, source_generation, config_generation, "
                "extractor_generation, canonicalizer_generation FROM runs "
                "WHERE repository_id = %s AND id = %s",
                (owner.repository_id, handoff.merge.run_id),
            ).fetchone()
            if stage_row is not None and len(stage_row) != 1:
                raise StorageSchemaError(
                    "stage row does not match the selected schema"
                )
            if run_row is not None and len(run_row) != 5:
                raise StorageSchemaError(
                    "run row does not match the selected schema"
                )
            published_match = (
                stage_row is not None
                and stage_row[0] == "published"
                and run_row is not None
                and run_row[0] == "complete"
                and run_row[1:5] == (
                    owner.source_generation, owner.config_generation,
                    owner.extractor_generation, owner.canonicalizer_generation,
                )
            )
            if published_match:
                raise StorageSchemaError("staged publication receipt conflicts")
            _execute(
                connection,
                build_publication_reconciliation_statements(handoff, outcome),
            )
            connection.commit()
            raise StorageSchemaError("staged publication receipt conflicts")
        _mark_commit_unknown(connection, handoff)
        connection.commit()
        return False
    except (Exception, KeyboardInterrupt):
        try:
            connection.rollback()
        except Exception:
            pass
        raise
    finally:
        close_owned_connection(connection)


def mark_failed_before_publication(
    connection: Any, stage_id: str, run_id: int, owner: StageOwner
) -> None:
    """Record a proved pre-publication rollback for one exact stage owner."""

    cursor = connection.execute(
        """
UPDATE ingestion_stages
SET state = 'failed', merge_status = 'rolled_back',
    publication_reconciliation_state = 'reconciled',
    cleanup_eligibility = 'eligible', cleanup_eligible_at = now(),
    updated_at = now()
WHERE stage_id = %s AND repository_id = %s AND operation_id = %s
  AND attempt = %s AND execution_mode = %s AND job_id IS NOT DISTINCT FROM %s
  AND coordinator_instance_id IS NOT DISTINCT FROM %s
  AND singleton_fencing_epoch = %s AND graph_lease_fencing_epoch = %s
  AND source_generation = %s AND config_generation = %s
  AND extractor_generation = %s AND canonicalizer_generation = %s
""",
        (
            stage_id, owner.repository_id, owner.operation_id, owner.attempt,
            owner.execution_mode, owner.job_id, owner.coordinator_instance_id,
            owner.singleton_fencing_epoch, owner.graph_lease_fencing_epoch,
            owner.source_generation, owner.config_generation,
            owner.extractor_generation, owner.canonicalizer_generation,
        ),
    )
    if cursor.rowcount != 1:
        raise StorageSchemaError("staged failure transition failed")
    _mark_run_failed(connection, run_id)


def _execute(connection: Any, statements: Sequence[str]) -> None:
    for statement in statements:
        if statement.strip() and not statement.lstrip().startswith("--"):
            connection.execute(statement)


def _publication_marker(
    connection: Any, repository_id: int, run_id: int
) -> Mapping[str, object] | None:
    portable_fields = list(PortablePublicationBinding.field_names())
    columns = [
        "status",
        "id",
        "source_generation",
        "config_generation",
        "extractor_generation",
        "canonicalizer_generation",
        *portable_fields,
    ]
    row = connection.execute(
        f"SELECT {', '.join(columns)} FROM runs WHERE id = %s AND repository_id = %s",
        (run_id, repository_id),
    ).fetchone()
    if row is None:
        return None
    if len(row) != len(columns):
        raise StorageSchemaError(
            "publication marker row does not match the selected schema"
        )
    if row[0] != "complete":
        return None
    marker: dict[str, object] = {
        "latest_run_identity": f"run-{int(row[1])}",
        "source_generation": row[2], "config_generation": row[3],
        "extractor_generation": row[4], "canonicalizer_generation": row[5],
    }
    portable_values = tuple(row[6:])
    populated = tuple(value is not None for value in portable_values)
    if any(populated) and not all(populated):
        raise StorageSchemaError(
            "portable publication identity must be present all-or-none"
        )
    if all(populated):
        marker.update(dict(zip(portable_fields, portable_values, strict=True)))
    return marker


def _mark_commit_unknown(connection: Any, handoff: PublicationHandoff) -> None:
    owner = handoff.merge.owner
    cursor = connection.execute(
        """
UPDATE ingestion_stages
SET state = 'commit_unknown', merge_status = 'unknown',
    publication_reconciliation_state = 'required',
    cleanup_eligibility = 'blocked', updated_at = now()
WHERE stage_id = %s AND repository_id = %s AND operation_id = %s
  AND attempt = %s AND execution_mode = %s AND job_id IS NOT DISTINCT FROM %s
  AND coordinator_instance_id IS NOT DISTINCT FROM %s
  AND singleton_fencing_epoch = %s AND graph_lease_fencing_epoch = %s
  AND source_generation = %s AND config_generation = %s
  AND extractor_generation = %s AND canonicalizer_generation = %s
  AND state IN ('validated', 'merging', 'published')
""",
        (
            handoff.merge.stage_id, owner.repository_id, owner.operation_id, owner.attempt,
            owner.execution_mode, owner.job_id, owner.coordinator_instance_id,
            owner.singleton_fencing_epoch, owner.graph_lease_fencing_epoch,
            owner.source_generation, owner.config_generation,
            owner.extractor_generation, owner.canonicalizer_generation,
        ),
    )
    if cursor.rowcount == 1:
        return
    state = connection.execute(
        "SELECT state FROM ingestion_stages WHERE stage_id = %s",
        (handoff.merge.stage_id,),
    ).fetchone()
    if state is None or state[0] != "commit_unknown":
        raise StorageSchemaError("staged publication stage reconciliation failed")


def _mark_run_failed(connection: Any, run_id: int) -> None:
    connection.execute(
        "UPDATE runs SET status = 'failed', finished_at = now() "
        "WHERE id = %s AND status = 'running'",
        (run_id,),
    )
