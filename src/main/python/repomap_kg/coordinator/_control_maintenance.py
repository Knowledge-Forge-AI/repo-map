from __future__ import annotations

from datetime import timedelta

from typing import Callable

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


from dataclasses import dataclass


@dataclass(frozen=True)
class CleanupReport:
    deleted_job_ids: tuple[str, ...]
    residuals: tuple[str, ...] = ()

    @property
    def residual_count(self) -> int:
        return len(self.residuals)


def _sanitize_error_category(err: BaseException) -> str:
    if isinstance(err, PermissionError):
        return "permission_denied"
    if isinstance(err, FileNotFoundError):
        return "not_found"
    if isinstance(err, OSError):
        return "os_error"
    if isinstance(err, ValueError):
        return "validation_error"
    return "unknown_error"


def cleanup_terminal(
    connect: ConnectionFactory,
    minimum_age: timedelta,
    *,
    limit: int,
    dry_run: bool,
    publication_retirer: Callable[[object], object] | None = None,
) -> CleanupReport:
    if minimum_age.total_seconds() < 0 or limit <= 0:
        raise ValueError("cleanup bounds are invalid")
    scan_limit = max(limit * 4, limit + 64) if publication_retirer is not None else limit
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
                (minimum_age.total_seconds(), scan_limit),
            )
            candidate_ids = tuple(row[0] for row in cursor.fetchall())
            if not candidate_ids:
                return CleanupReport(())
            if dry_run:
                return CleanupReport(candidate_ids[:limit])
            if publication_retirer is None:
                deleted_job_ids = candidate_ids[:limit]
                collected_residuals: list[str] = []
            else:
                cursor.execute(
                    """
                    SELECT a.job_id, a.attempt, j.graph_id,
                           a.coordinator_instance_id,
                           a.fencing_epoch,
                           a.source_generation, a.config_generation,
                           a.extractor_generation, a.canonicalizer_generation
                    FROM job_attempts AS a
                    JOIN jobs AS j ON j.job_id = a.job_id
                    WHERE a.job_id = ANY(%s)
                    ORDER BY a.job_id, a.attempt
                    """,
                    (list(candidate_ids),),
                )
                attempts_by_job: dict[str, list[JobClaim]] = {jid: [] for jid in candidate_ids}
                for row in cursor.fetchall():
                    claim = JobClaim(
                        job_id=row[0],
                        attempt=row[1],
                        graph_id=row[2],
                        instance_id=row[3],
                        fencing_epoch=row[4],
                        source_generation=row[5],
                        config_generation=row[6],
                        extractor_generation=row[7],
                        canonicalizer_generation=row[8],
                    )
                    if claim.job_id in attempts_by_job:
                        attempts_by_job[claim.job_id].append(claim)

                deleted_list: list[str] = []
                collected_residuals = []
                for jid in candidate_ids:
                    claims = attempts_by_job.get(jid, [])
                    job_failed = False
                    for claim in claims:
                        try:
                            publication_retirer(claim)
                        except (OSError, ValueError) as err:
                            job_failed = True
                            cat = _sanitize_error_category(err)
                            collected_residuals.append(f"{claim.job_id}:{claim.attempt}:{cat}")
                    if not job_failed:
                        deleted_list.append(jid)
                        if len(deleted_list) == limit:
                            break
                deleted_job_ids = tuple(deleted_list)

            if deleted_job_ids:
                cursor.execute(
                    "DELETE FROM synthetic_publication_markers "
                    "WHERE job_id = ANY(%s)",
                    (list(deleted_job_ids),),
                )
                cursor.execute(
                    "DELETE FROM job_attempts WHERE job_id = ANY(%s)",
                    (list(deleted_job_ids),),
                )
                cursor.execute(
                    "DELETE FROM jobs WHERE job_id = ANY(%s)",
                    (list(deleted_job_ids),),
                )
            return CleanupReport(deleted_job_ids, tuple(collected_residuals))
