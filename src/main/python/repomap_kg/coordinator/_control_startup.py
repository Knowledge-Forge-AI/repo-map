"""Stable bounded control-store reads used during coordinator startup."""

from __future__ import annotations

from typing import Any, Callable

from psycopg.rows import dict_row

from repomap_kg.coordinator._control_types import ConnectionFactory, JobClaim
from repomap_kg.coordinator._publication_phase import WorkerFencingProof



_ABANDONED_STATES = (
    "claimed",
    "starting",
    "running",
    "cancel_requested",
    "cancelling",
)


def recover_abandoned_attempts(
    connect: ConnectionFactory,
    instance_id: str,
    fencing_epoch: int,
    limit: int,
) -> int:
    """Classify abandoned attempts without asserting process or publication fencing.

    A prior claimed/starting worker may still launch after its coordinator dies.
    Every abandoned attempt therefore needs real publication reconciliation;
    the completion timestamp below is classification metadata only.
    """

    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise ValueError("abandoned-attempt limit must be positive")
    with connect() as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT 1 FROM coordinator_instances
                WHERE singleton_scope = 'control' AND instance_id = %s
                  AND fencing_epoch = %s AND status = 'active'
                  AND expires_at > now()
                FOR UPDATE
                """,
                (instance_id, fencing_epoch),
            )
            if cursor.fetchone() is None:
                raise RuntimeError("replacement coordinator is not the live owner")
            cursor.execute(
                """
                SELECT j.job_id, j.current_attempt, j.publication_state, j.state
                FROM jobs AS j
                JOIN job_attempts AS a
                  ON a.job_id = j.job_id AND a.attempt = j.current_attempt
                WHERE j.state = ANY(%s) AND a.is_current
                  AND (a.coordinator_instance_id, a.fencing_epoch)
                      IS DISTINCT FROM (%s, %s)
                ORDER BY j.submitted_at, j.job_id
                LIMIT %s
                FOR UPDATE OF j, a
                """,
                (list(_ABANDONED_STATES), instance_id, fencing_epoch, limit),
            )
            rows = tuple(cursor.fetchall())
            for row in rows:
                publication_state = "commit_unknown"
                cursor.execute(
                    """
                    UPDATE jobs
                    SET state = 'reconciliation_required',
                        publication_state = %s,
                        error_category = 'publication_unknown',
                        updated_at = now()
                    WHERE job_id = %s AND current_attempt = %s
                    """,
                    (publication_state, row["job_id"], row["current_attempt"]),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("abandoned job fencing failed")
                cursor.execute(
                    """
                    UPDATE job_attempts
                    SET finished_at = COALESCE(finished_at, now()),
                        supervisor_registration_digest = NULL,
                        supervisor_registration_consumed = TRUE,
                        publication_state = %s,
                        result_category = 'publication_unknown'
                    WHERE job_id = %s AND attempt = %s AND is_current
                    """,
                    (publication_state, row["job_id"], row["current_attempt"]),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("abandoned attempt closure failed")
            return len(rows)


def reconciliation_claims(
    connect: ConnectionFactory, limit: int
) -> tuple[JobClaim, ...]:
    """Return current reconciliation claims in stable submission order."""

    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise ValueError("reconciliation limit must be positive")
    with connect() as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT j.job_id, j.graph_id, j.current_attempt,
                       j.priority_class, j.source_generation,
                       j.config_generation, j.extractor_generation,
                       j.canonicalizer_generation,
                       a.coordinator_instance_id, a.fencing_epoch,
                       a.graph_lease_fencing_epoch
                FROM jobs AS j
                JOIN job_attempts AS a
                  ON a.job_id = j.job_id AND a.attempt = j.current_attempt
                WHERE j.state = 'reconciliation_required' AND a.is_current
                ORDER BY j.submitted_at, j.job_id
                LIMIT %s
                """,
                (limit,),
            )
            return tuple(
                JobClaim(
                    job_id=row["job_id"],
                    graph_id=row["graph_id"],
                    attempt=row["current_attempt"],
                    instance_id=row["coordinator_instance_id"],
                    fencing_epoch=row["fencing_epoch"],
                    priority_class=row["priority_class"],
                    source_generation=row["source_generation"],
                    config_generation=row["config_generation"],
                    extractor_generation=row["extractor_generation"],
                    canonicalizer_generation=row["canonicalizer_generation"],
                    graph_lease_fencing_epoch=row.get("graph_lease_fencing_epoch", 0),
                )
                for row in cursor.fetchall()
            )


def prove_worker_fenced(
    connect: ConnectionFactory,
    claim: JobClaim,
    *,
    reconciler_instance_id: str,
    reconciler_epoch: int,
    fence_callback: Callable[..., Any] | None = None,
) -> WorkerFencingProof | None:
    """Produce authoritative proof that a prior attempt cannot publish."""
    from repomap_kg.coordinator._restart_fencing import build_store_fencing_proof

    return build_store_fencing_proof(
        connect,
        claim,
        reconciler_instance_id=reconciler_instance_id,
        reconciler_epoch=reconciler_epoch,
        fence_callback=fence_callback,
    )


def close_unpublished_reconciliation(
    connect: ConnectionFactory,
    claim: JobClaim,
    *,
    reconciler_instance_id: str,
    reconciler_epoch: int,
    fence_callback: Callable[..., Any] | None,
    file_closer: Callable[[JobClaim, WorkerFencingProof], bool] | None,
) -> bool:
    """Atomically validated store closure operation."""
    from repomap_kg.coordinator._restart_fencing import execute_durable_closure

    return execute_durable_closure(
        connect,
        claim,
        reconciler_instance_id=reconciler_instance_id,
        reconciler_epoch=reconciler_epoch,
        fence_callback=fence_callback,
        file_closer=file_closer,
    )
