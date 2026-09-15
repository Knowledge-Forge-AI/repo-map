from __future__ import annotations

from datetime import timedelta

from repomap_kg.coordinator._control_types import ConnectionFactory, JobClaim


def record_publication_marker(
    connect: ConnectionFactory,
    claim: JobClaim,
    *,
    run_identity: str,
    source_generation: str,
    config_generation: str,
    extractor_generation: str,
    canonicalizer_generation: str,
    outcome: str,
) -> bool:
    values = (
        claim.job_id,
        claim.attempt,
        claim.graph_id,
        run_identity,
        source_generation,
        config_generation,
        extractor_generation,
        canonicalizer_generation,
        outcome,
    )
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO synthetic_publication_markers(
                    job_id, attempt, graph_id, run_identity,
                    source_generation, config_generation,
                    extractor_generation, canonicalizer_generation, outcome
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (job_id, attempt) DO NOTHING
                """,
                values,
            )
            if cursor.rowcount == 1:
                return True
            cursor.execute(
                """
                SELECT job_id, attempt, graph_id, run_identity,
                       source_generation, config_generation,
                       extractor_generation, canonicalizer_generation, outcome
                FROM synthetic_publication_markers
                WHERE job_id = %s AND attempt = %s
                """,
                (claim.job_id, claim.attempt),
            )
            existing = cursor.fetchone()
            if existing is None or tuple(existing) != values:
                raise ValueError("publication marker conflict")
            return False


def cleanup_terminal(
    connect: ConnectionFactory,
    minimum_age: timedelta,
    *,
    limit: int,
    dry_run: bool,
) -> tuple[str, ...]:
    if minimum_age.total_seconds() < 0 or limit <= 0:
        raise ValueError("cleanup bounds are invalid")
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT j.job_id FROM jobs AS j
                WHERE j.state IN (
                    'succeeded', 'failed', 'cancelled',
                    'superseded', 'quarantined'
                )
                  AND j.finished_at <= now() - make_interval(secs => %s)
                  AND j.publication_state <> 'commit_unknown'
                  AND NOT EXISTS (
                      SELECT 1 FROM graph_leases AS gl
                      WHERE gl.job_id = j.job_id
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM jobs AS other
                      WHERE other.replacement_job_id = j.job_id
                         OR other.parent_job_id = j.job_id
                  )
                ORDER BY j.finished_at, j.job_id LIMIT %s
                FOR UPDATE OF j SKIP LOCKED
                """,
                (minimum_age.total_seconds(), limit),
            )
            job_ids = tuple(row[0] for row in cursor.fetchall())
            if dry_run or not job_ids:
                return job_ids
            cursor.execute(
                "DELETE FROM synthetic_publication_markers "
                "WHERE job_id = ANY(%s)",
                (list(job_ids),),
            )
            cursor.execute(
                "DELETE FROM job_attempts WHERE job_id = ANY(%s)",
                (list(job_ids),),
            )
            cursor.execute(
                "DELETE FROM jobs WHERE job_id = ANY(%s)",
                (list(job_ids),),
            )
            return job_ids
