from __future__ import annotations

from datetime import timedelta
from typing import Any

from psycopg.rows import dict_row

from repomap_kg.coordinator._control_types import (
    ConnectionFactory,
    JobClaim,
    SingletonActiveError,
)
from repomap_kg.runtime.maintenance import require_transaction_admission


def acquire_singleton(
    connect: ConnectionFactory, instance_id: str, ttl: timedelta
) -> int:
    seconds = positive_seconds(ttl)
    with connect() as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT *, now() AS database_now
                FROM coordinator_instances
                WHERE singleton_scope = 'control' FOR UPDATE
                """
            )
            owner = cursor.fetchone()
            if owner is None:
                cursor.execute(
                    """
                    INSERT INTO coordinator_instances(
                        singleton_scope, instance_id, fencing_epoch,
                        expires_at, status
                    ) VALUES ('control', %s, 1,
                              now() + make_interval(secs => %s), 'active')
                    RETURNING fencing_epoch
                    """,
                    (instance_id, seconds),
                )
            elif owner["status"] == "active" and owner["expires_at"] > owner[
                "database_now"
            ]:
                raise SingletonActiveError("coordinator singleton is active")
            else:
                cursor.execute(
                    """
                    UPDATE coordinator_instances
                    SET instance_id = %s,
                        fencing_epoch = fencing_epoch + 1,
                        started_at = now(), heartbeat_at = now(),
                        expires_at = now() + make_interval(secs => %s),
                        stopped_at = NULL, status = 'active'
                    WHERE singleton_scope = 'control'
                    RETURNING fencing_epoch
                    """,
                    (instance_id, seconds),
                )
            row = cursor.fetchone()
            if row is None:
                raise ValueError("coordinator singleton was not updated")
            return int(row["fencing_epoch"])


def heartbeat_singleton(
    connect: ConnectionFactory,
    instance_id: str,
    fencing_epoch: int,
    ttl: timedelta,
) -> bool:
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE coordinator_instances
                SET heartbeat_at = now(),
                    expires_at = now() + make_interval(secs => %s)
                WHERE singleton_scope = 'control' AND instance_id = %s
                  AND fencing_epoch = %s AND status = 'active'
                  AND expires_at > now()
                """,
                (positive_seconds(ttl), instance_id, fencing_epoch),
            )
            return cursor.rowcount == 1


def stop_singleton(
    connect: ConnectionFactory, instance_id: str, fencing_epoch: int
) -> bool:
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE coordinator_instances
                SET status = 'stopped', stopped_at = now(), expires_at = now()
                WHERE singleton_scope = 'control' AND instance_id = %s
                  AND fencing_epoch = %s AND status = 'active'
                """,
                (instance_id, fencing_epoch),
            )
            return cursor.rowcount == 1


def claim_once(
    connect: ConnectionFactory,
    instance_id: str,
    fencing_epoch: int,
    lease_seconds: float,
    *,
    max_attempts: int,
    automatic_only: bool,
) -> JobClaim | None:
    with connect() as connection:
        require_transaction_admission(connection)
        with connection.cursor(row_factory=dict_row) as cursor:
            require_live_owner(cursor, instance_id, fencing_epoch)
            cursor.execute(
                """
                SELECT j.* FROM jobs AS j
                WHERE j.state = 'queued' AND j.next_eligible_at <= now()
                  AND j.current_attempt < %s
                  AND (NOT %s OR j.priority_class = 'automatic')
                  AND (
                      j.priority_class = 'manual'
                      OR NOT EXISTS (
                          SELECT 1 FROM coalescing_state AS cs
                          WHERE cs.graph_id = j.graph_id
                            AND cs.job_kind_family = 'refresh_graph'
                            AND cs.paused
                      )
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM graph_leases AS gl
                      WHERE gl.graph_id = j.graph_id
                  )
                ORDER BY j.priority_value DESC, j.next_eligible_at,
                         j.submitted_at, j.job_id
                FOR UPDATE OF j SKIP LOCKED LIMIT 1
                """,
                (max_attempts, automatic_only),
            )
            job = cursor.fetchone()
            if job is None:
                return None
            attempt = int(job["current_attempt"]) + 1
            cursor.execute(
                "SELECT pg_current_xact_id()::text::bigint "
                "AS graph_lease_fencing_epoch"
            )
            epoch_row = cursor.fetchone()
            if epoch_row is None:
                raise ValueError("transaction fencing epoch unavailable")
            graph_lease_fencing_epoch = int(
                epoch_row["graph_lease_fencing_epoch"]
            )
            cursor.execute(
                """
                INSERT INTO job_attempts(
                    job_id, attempt, coordinator_instance_id, fencing_epoch,
                    source_generation, config_generation,
                    extractor_generation, canonicalizer_generation
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    job["job_id"],
                    attempt,
                    instance_id,
                    fencing_epoch,
                    job["source_generation"],
                    job["config_generation"],
                    job["extractor_generation"],
                    job["canonicalizer_generation"],
                ),
            )
            cursor.execute(
                """
                INSERT INTO graph_leases(
                    graph_id, job_id, attempt, coordinator_instance_id,
                    fencing_epoch, expires_at
                ) VALUES (%s, %s, %s, %s, %s,
                          now() + make_interval(secs => %s))
                """,
                (
                    job["graph_id"],
                    job["job_id"],
                    attempt,
                    instance_id,
                    fencing_epoch,
                    lease_seconds,
                ),
            )
            cursor.execute(
                """
                UPDATE jobs SET state = 'claimed', current_attempt = %s,
                                updated_at = now()
                WHERE job_id = %s AND state = 'queued'
                """,
                (attempt, job["job_id"]),
            )
            if job["priority_class"] == "automatic":
                cursor.execute(
                    """
                    UPDATE coalescing_state
                    SET queued_job_id = NULL, running_job_id = %s,
                        dirty = false
                    WHERE graph_id = %s AND job_kind_family = 'refresh_graph'
                      AND queued_job_id = %s
                    """,
                    (job["job_id"], job["graph_id"], job["job_id"]),
                )
            return JobClaim(
                job_id=job["job_id"],
                graph_id=job["graph_id"],
                attempt=attempt,
                instance_id=instance_id,
                fencing_epoch=fencing_epoch,
                priority_class=job["priority_class"],
                source_generation=job["source_generation"],
                config_generation=job["config_generation"],
                extractor_generation=job["extractor_generation"],
                canonicalizer_generation=job["canonicalizer_generation"],
                graph_lease_fencing_epoch=graph_lease_fencing_epoch,
            )


def release_graph_lease(
    connect: ConnectionFactory,
    graph_id: str,
    job_id: str,
    attempt: int,
    owner_instance_id: str,
    owner_epoch: int,
    *,
    reconciler_instance_id: str,
    reconciler_epoch: int,
) -> bool:
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM graph_leases AS gl
                WHERE gl.graph_id = %s AND gl.job_id = %s AND gl.attempt = %s
                  AND gl.coordinator_instance_id = %s
                  AND gl.fencing_epoch = %s
                  AND EXISTS (
                      SELECT 1 FROM coordinator_instances AS c
                      WHERE c.singleton_scope = 'control'
                        AND c.instance_id = %s AND c.fencing_epoch = %s
                        AND c.status = 'active' AND c.expires_at > now()
                  )
                  AND EXISTS (
                      SELECT 1 FROM jobs AS j
                      WHERE j.job_id = gl.job_id
                        AND (
                            (j.state = 'succeeded'
                             AND j.publication_state = 'committed')
                            OR
                            (j.state IN (
                                'failed', 'cancelled', 'superseded', 'quarantined'
                             ) AND j.publication_state IN (
                                'not_started', 'prepared', 'rolled_back'
                             ))
                        )
                  )
                """,
                (
                    graph_id,
                    job_id,
                    attempt,
                    owner_instance_id,
                    owner_epoch,
                    reconciler_instance_id,
                    reconciler_epoch,
                ),
            )
            released = cursor.rowcount == 1
            if released:
                cursor.execute(
                    """
                    UPDATE coalescing_state
                    SET running_job_id = NULL
                    WHERE graph_id = %s AND job_kind_family = 'refresh_graph'
                      AND running_job_id = %s
                    """,
                    (graph_id, job_id),
                )
            return released


def require_live_owner(cursor: Any, instance_id: str, epoch: int) -> None:
    cursor.execute(
        """
        SELECT 1 FROM coordinator_instances
        WHERE singleton_scope = 'control' AND instance_id = %s
          AND fencing_epoch = %s AND status = 'active'
          AND expires_at > now()
        """,
        (instance_id, epoch),
    )
    if cursor.fetchone() is None:
        raise SingletonActiveError("coordinator singleton is not owned")


def positive_seconds(value: timedelta) -> float:
    seconds = value.total_seconds()
    if seconds <= 0:
        raise ValueError("duration must be positive")
    return seconds


def is_expected_graph_lease_race(error: BaseException) -> bool:
    diagnostic = getattr(error, "diag", None)
    return getattr(diagnostic, "constraint_name", None) == "graph_leases_pkey"
