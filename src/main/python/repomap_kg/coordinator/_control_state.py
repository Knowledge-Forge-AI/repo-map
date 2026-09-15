from __future__ import annotations

from datetime import timedelta

from psycopg.rows import dict_row

from repomap_kg.coordinator._control_ownership import positive_seconds, require_live_owner
from repomap_kg.coordinator._control_types import ConnectionFactory, JobClaim, JobStatus
from repomap_kg.coordinator.contracts import TERMINAL_JOB_STATES, validate_transition
from repomap_kg.coordinator.semantics import RetryPolicy


_TERMINAL_STATES = frozenset(state.value for state in TERMINAL_JOB_STATES)
_SAFE_UNPUBLISHED = frozenset({"not_started", "prepared", "rolled_back"})


def compare_and_set_state(
    connect: ConnectionFactory,
    job_id: str,
    *,
    expected_state: str,
    new_state: str,
    attempt: int,
    instance_id: str,
    fencing_epoch: int,
    publication_state: str | None,
    error_category: str | None,
    diagnostic_summary: str | None = None,
) -> bool:
    validate_transition(expected_state, new_state)
    validate_state_publication(new_state, publication_state)
    terminal = new_state in _TERMINAL_STATES
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE jobs AS j
                SET state = %s,
                    publication_state = COALESCE(%s, publication_state),
                    error_category = %s, updated_at = now(),
                    finished_at = CASE WHEN %s THEN now() ELSE finished_at END
                WHERE j.job_id = %s AND j.state = %s
                  AND j.current_attempt = %s
                  AND EXISTS (
                      SELECT 1 FROM job_attempts AS a
                      WHERE a.job_id = j.job_id AND a.attempt = %s
                        AND a.is_current
                        AND a.coordinator_instance_id = %s
                        AND a.fencing_epoch = %s
                        AND (
                            %s <> 'succeeded'
                            OR EXISTS (
                                SELECT 1
                                FROM synthetic_publication_markers AS m
                                WHERE m.job_id = a.job_id
                                  AND m.attempt = a.attempt
                                  AND m.graph_id = j.graph_id
                                  AND m.source_generation = a.source_generation
                                  AND m.config_generation = a.config_generation
                                  AND m.extractor_generation = a.extractor_generation
                                  AND m.canonicalizer_generation = a.canonicalizer_generation
                                  AND a.source_generation = j.source_generation
                                  AND a.config_generation = j.config_generation
                                  AND a.extractor_generation = j.extractor_generation
                                  AND a.canonicalizer_generation =
                                      j.canonicalizer_generation
                                  AND m.outcome = 'committed'
                            )
                        )
                  )
                  AND EXISTS (
                      SELECT 1 FROM coordinator_instances AS c
                      WHERE c.singleton_scope = 'control'
                        AND c.instance_id = %s AND c.fencing_epoch = %s
                        AND c.status = 'active' AND c.expires_at > now()
                  )
                """,
                (
                    new_state,
                    publication_state,
                    error_category,
                    terminal,
                    job_id,
                    expected_state,
                    attempt,
                    attempt,
                    instance_id,
                    fencing_epoch,
                    new_state,
                    instance_id,
                    fencing_epoch,
                ),
            )
            if cursor.rowcount != 1:
                return False
            if terminal:
                cursor.execute(
                    """
                    UPDATE job_attempts
                    SET is_current = false, finished_at = now(),
                        result_category = %s,
                        publication_state = COALESCE(%s, publication_state),
                        diagnostic_summary = COALESCE(%s, diagnostic_summary)
                    WHERE job_id = %s AND attempt = %s AND is_current
                      AND coordinator_instance_id = %s AND fencing_epoch = %s
                    """,
                    (
                        error_category,
                        publication_state,
                        diagnostic_summary,
                        job_id,
                        attempt,
                        instance_id,
                        fencing_epoch,
                    ),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("current attempt closure failed")
            elif (
                publication_state is not None
                or error_category is not None
                or diagnostic_summary is not None
            ):
                cursor.execute(
                    """
                    UPDATE job_attempts
                    SET publication_state = COALESCE(%s, publication_state),
                        result_category = COALESCE(%s, result_category),
                        diagnostic_summary = COALESCE(%s, diagnostic_summary)
                    WHERE job_id = %s AND attempt = %s AND is_current
                      AND coordinator_instance_id = %s AND fencing_epoch = %s
                    """,
                    (
                        publication_state,
                        error_category,
                        diagnostic_summary,
                        job_id,
                        attempt,
                        instance_id,
                        fencing_epoch,
                    ),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("current attempt publication update failed")
            return True


def validate_state_publication(
    new_state: str, publication_state: str | None
) -> None:
    if new_state == "succeeded" and publication_state != "committed":
        raise ValueError("succeeded mutating job requires committed publication")
    if new_state in {"failed", "cancelled", "superseded"}:
        if publication_state not in _SAFE_UNPUBLISHED:
            raise ValueError(f"{new_state} requires safely unpublished state")
    if new_state == "queued" and publication_state == "commit_unknown":
        raise ValueError("commit_unknown publication cannot be retried")


def heartbeat_attempt(
    connect: ConnectionFactory,
    claim: JobClaim,
    lease_ttl: timedelta,
    *,
    phase: str | None,
    completed: int | None,
    total: int | None,
    progress_counter_delta: int,
    progress_min_interval_seconds: int,
    max_counter: int,
) -> bool:
    seconds = positive_seconds(lease_ttl)
    with connect() as connection:
        with connection.cursor() as cursor:
            require_live_owner(cursor, claim.instance_id, claim.fencing_epoch)
            cursor.execute(
                """
                UPDATE graph_leases
                SET heartbeat_at = now(),
                    expires_at = now() + make_interval(secs => %s)
                WHERE graph_id = %s AND job_id = %s AND attempt = %s
                  AND coordinator_instance_id = %s AND fencing_epoch = %s
                """,
                (
                    seconds,
                    claim.graph_id,
                    claim.job_id,
                    claim.attempt,
                    claim.instance_id,
                    claim.fencing_epoch,
                ),
            )
            if cursor.rowcount != 1:
                return False
            cursor.execute(
                """
                UPDATE job_attempts SET heartbeat_at = now()
                WHERE job_id = %s AND attempt = %s AND is_current
                  AND coordinator_instance_id = %s AND fencing_epoch = %s
                """,
                (
                    claim.job_id,
                    claim.attempt,
                    claim.instance_id,
                    claim.fencing_epoch,
                ),
            )
            if phase is not None:
                _validate_progress(completed, total, max_counter)
                cursor.execute(
                    """
                    UPDATE jobs SET phase = %s, progress_completed = %s,
                                    progress_total = %s, updated_at = now()
                    WHERE job_id = %s AND current_attempt = %s
                      AND (
                          phase <> %s OR progress_total IS DISTINCT FROM %s
                          OR %s - progress_completed >= %s
                          OR updated_at <= now() - make_interval(secs => %s)
                      )
                    """,
                    (
                        phase, completed, total, claim.job_id, claim.attempt,
                        phase, total, completed, progress_counter_delta,
                        progress_min_interval_seconds,
                    ),
                )
            return True


def request_cancellation(connect: ConnectionFactory, job_id: str) -> str:
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE jobs
                SET state = CASE WHEN state = 'queued'
                                 THEN 'cancelled'
                                 ELSE 'cancel_requested' END,
                    cancel_requested_at = now(), updated_at = now(),
                    finished_at = CASE WHEN state = 'queued'
                                       THEN now() ELSE finished_at END
                WHERE job_id = %s
                  AND state IN ('queued', 'claimed', 'starting', 'running')
                RETURNING state
                """,
                (job_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise ValueError("job cannot be cancelled")
            return row[0]


def mark_attempt_terminated(
    connect: ConnectionFactory,
    claim: JobClaim,
    *,
    process_cleanup_proved: bool,
    reconciler_instance_id: str,
    reconciler_epoch: int,
    diagnostic_summary: str | None = None,
) -> bool:
    if process_cleanup_proved is not True:
        raise ValueError("process cleanup proof is required")
    with connect() as connection:
        with connection.cursor() as cursor:
            require_live_owner(cursor, reconciler_instance_id, reconciler_epoch)
            cursor.execute(
                """
                UPDATE job_attempts AS a
                SET finished_at = now(),
                    diagnostic_summary = COALESCE(%s, a.diagnostic_summary)
                WHERE a.job_id = %s AND a.attempt = %s AND a.is_current
                  AND a.coordinator_instance_id = %s AND a.fencing_epoch = %s
                  AND EXISTS (
                      SELECT 1 FROM jobs AS j
                      WHERE j.job_id = a.job_id
                        AND j.state = 'reconciliation_required'
                        AND j.current_attempt = a.attempt
                  )
                """,
                (diagnostic_summary, claim.job_id, claim.attempt, claim.instance_id, claim.fencing_epoch),
            )
            return cursor.rowcount == 1


def schedule_retry(
    connect: ConnectionFactory,
    claim: JobClaim,
    *,
    expected_state: str,
    delay: timedelta,
    category: str,
    max_attempts: int,
    diagnostic_summary: str | None = None,
) -> bool:
    validate_transition(expected_state, "queued")
    seconds = delay.total_seconds()
    if seconds < 0:
        raise ValueError("retry delay is invalid")
    with connect() as connection:
        with connection.cursor() as cursor:
            require_live_owner(cursor, claim.instance_id, claim.fencing_epoch)
            cursor.execute(
                """
                SELECT j.publication_state, j.current_attempt
                FROM jobs AS j
                JOIN job_attempts AS a
                  ON a.job_id = j.job_id AND a.attempt = j.current_attempt
                WHERE j.job_id = %s AND j.state = %s
                  AND j.current_attempt = %s AND a.is_current
                  AND a.coordinator_instance_id = %s AND a.fencing_epoch = %s
                FOR UPDATE OF j
                """,
                (claim.job_id, expected_state, claim.attempt, claim.instance_id, claim.fencing_epoch),
            )
            row = cursor.fetchone()
            if row is None:
                return False
            policy = RetryPolicy(max_attempts, 1, max(1, seconds or 1))
            if row[0] not in _SAFE_UNPUBLISHED:
                raise ValueError(f"{row[0]} publication cannot be retried")
            if not policy.may_retry(int(row[1]), category, row[0]):
                raise ValueError("retry is not permitted")
            cursor.execute(
                """
                UPDATE jobs
                SET state = 'queued', publication_state = 'not_started',
                    error_category = %s,
                    next_eligible_at = now() + make_interval(secs => %s),
                    updated_at = now()
                WHERE job_id = %s AND state = %s AND current_attempt = %s
                """,
                (category, seconds, claim.job_id, expected_state, claim.attempt),
            )
            cursor.execute(
                """
                UPDATE job_attempts
                SET is_current = false, finished_at = now(),
                    result_category = %s,
                    diagnostic_summary = COALESCE(%s, diagnostic_summary)
                WHERE job_id = %s AND attempt = %s AND is_current
                  AND coordinator_instance_id = %s AND fencing_epoch = %s
                """,
                (category, diagnostic_summary, claim.job_id, claim.attempt, claim.instance_id, claim.fencing_epoch),
            )
            cursor.execute(
                """
                DELETE FROM graph_leases
                WHERE graph_id = %s AND job_id = %s AND attempt = %s
                  AND coordinator_instance_id = %s AND fencing_epoch = %s
                """,
                (claim.graph_id, claim.job_id, claim.attempt, claim.instance_id, claim.fencing_epoch),
            )
            return True


def status(connect: ConnectionFactory, job_id: str) -> JobStatus:
    with connect() as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT job_id, graph_id, state, current_attempt,
                       publication_state, phase, progress_completed,
                       progress_total, error_category
                FROM jobs WHERE job_id = %s
                """,
                (job_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise KeyError("unknown job")
            return JobStatus(
                row["job_id"], row["graph_id"], row["state"], row["current_attempt"],
                row["publication_state"], row["phase"], row["progress_completed"],
                row["progress_total"], row["error_category"],
            )


def _validate_progress(
    completed: int | None, total: int | None, max_counter: int
) -> None:
    if (
        isinstance(completed, bool) or not isinstance(completed, int)
        or not (0 <= completed <= max_counter)
    ):
        raise ValueError("completed progress is invalid")
    if total is not None and (
        isinstance(total, bool) or not isinstance(total, int)
        or not (completed <= total <= max_counter)
    ):
        raise ValueError("total progress is invalid")
