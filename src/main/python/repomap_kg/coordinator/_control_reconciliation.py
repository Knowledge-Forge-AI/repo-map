"""Authoritative synthetic publication reconciliation transactions."""

from __future__ import annotations

from psycopg.rows import dict_row

from repomap_kg.coordinator._control_ownership import require_live_owner
from repomap_kg.coordinator._control_types import ConnectionFactory, JobClaim


def reconcile_publication(
    connect: ConnectionFactory,
    claim: JobClaim,
    *,
    max_attempts: int,
    reconciler_instance_id: str,
    reconciler_epoch: int,
) -> str:
    with connect() as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            require_live_owner(
                cursor, reconciler_instance_id, reconciler_epoch
            )
            row = _lock_evidence(cursor, claim)
            if row is None:
                return "ownership_lost"
            if row["attempt_finished_at"] is None:
                return "reconciliation_required"
            marker = _marker_classification(row)
            if marker == "matching_committed":
                _close_terminal(cursor, claim, "succeeded", "committed", None)
                return "succeeded"
            if marker == "conflicting":
                _pause_graph_intent(cursor, claim)
                _close_terminal(
                    cursor,
                    claim,
                    "quarantined",
                    row["job_publication_state"],
                    "publication_unknown",
                )
                return "quarantined"
            if row["error_category"] == "protocol":
                _pause_graph_intent(cursor, claim)
                _close_terminal(
                    cursor,
                    claim,
                    "quarantined",
                    row["job_publication_state"],
                    "protocol",
                )
                return "quarantined"
            if row["job_publication_state"] == "commit_unknown":
                return "reconciliation_required"
            if row["cancel_requested_at"] is not None:
                _close_terminal(
                    cursor, claim, "cancelled", "rolled_back", "cancelled"
                )
                return "cancelled"
            if row["current_attempt"] >= max_attempts:
                _close_terminal(
                    cursor, claim, "failed", "rolled_back", "permanent"
                )
                return "failed"
            _queue_retry(cursor, claim)
            return "queued"


def _lock_evidence(cursor, claim):
    cursor.execute(
        """
        SELECT j.publication_state AS job_publication_state,
               j.current_attempt,
               j.error_category,
               j.cancel_requested_at,
               j.graph_id,
               j.source_generation AS job_source_generation,
               j.config_generation AS job_config_generation,
               j.extractor_generation AS job_extractor_generation,
               j.canonicalizer_generation AS job_canonicalizer_generation,
               a.finished_at AS attempt_finished_at,
               a.source_generation AS attempt_source_generation,
               a.config_generation AS attempt_config_generation,
               a.extractor_generation AS attempt_extractor_generation,
               a.canonicalizer_generation AS attempt_canonicalizer_generation,
               m.outcome AS marker_outcome,
               m.graph_id AS marker_graph_id,
               m.source_generation AS marker_source_generation,
               m.config_generation AS marker_config_generation,
               m.extractor_generation AS marker_extractor_generation,
               m.canonicalizer_generation AS marker_canonicalizer_generation
        FROM jobs AS j
        JOIN job_attempts AS a
          ON a.job_id = j.job_id AND a.attempt = j.current_attempt
        LEFT JOIN synthetic_publication_markers AS m
          ON m.job_id = a.job_id AND m.attempt = a.attempt
        WHERE j.job_id = %s AND j.state = 'reconciliation_required'
          AND j.current_attempt = %s AND a.is_current
          AND a.coordinator_instance_id = %s AND a.fencing_epoch = %s
        FOR UPDATE OF j, a
        """,
        (
            claim.job_id,
            claim.attempt,
            claim.instance_id,
            claim.fencing_epoch,
        ),
    )
    return cursor.fetchone()


def _marker_classification(row) -> str:
    if row["marker_outcome"] is None:
        return "absent"
    matches = (
        row["marker_outcome"] == "committed"
        and row["marker_graph_id"] == row["graph_id"]
        and row["marker_source_generation"] == row["job_source_generation"]
        and row["marker_source_generation"] == row["attempt_source_generation"]
        and row["marker_config_generation"] == row["job_config_generation"]
        and row["marker_config_generation"] == row["attempt_config_generation"]
        and row["marker_extractor_generation"] == row["job_extractor_generation"]
        and row["marker_extractor_generation"] == row["attempt_extractor_generation"]
        and row["marker_canonicalizer_generation"]
        == row["job_canonicalizer_generation"]
        and row["marker_canonicalizer_generation"]
        == row["attempt_canonicalizer_generation"]
    )
    return "matching_committed" if matches else "conflicting"


def _close_terminal(cursor, claim, target, publication, category) -> None:
    cursor.execute(
        """
        UPDATE jobs SET state = %s, publication_state = %s,
                        error_category = %s, finished_at = now(),
                        updated_at = now()
        WHERE job_id = %s AND state = 'reconciliation_required'
          AND current_attempt = %s
        """,
        (target, publication, category, claim.job_id, claim.attempt),
    )
    _close_attempt(cursor, claim, publication, category)
    _delete_lease(cursor, claim)


def _pause_graph_intent(cursor, claim) -> None:
    cursor.execute(
        """
        INSERT INTO coalescing_state(
            graph_id, job_kind_family, desired_source_generation,
            desired_config_generation, desired_extractor_generation,
            desired_canonicalizer_generation, dirty, paused,
            reason_categories
        )
        SELECT graph_id, 'refresh_graph', source_generation,
               config_generation, extractor_generation,
               canonicalizer_generation, true, true,
               ARRAY['publication_unknown']::text[]
        FROM jobs WHERE job_id = %s
        ON CONFLICT (graph_id, job_kind_family) DO UPDATE SET
            paused = true, dirty = true, queued_job_id = NULL,
            reason_categories = ARRAY['publication_unknown']::text[]
        """,
        (claim.job_id,),
    )


def _queue_retry(cursor, claim) -> None:
    cursor.execute(
        """
        UPDATE jobs SET state = 'queued', publication_state = 'not_started',
                        error_category = 'transient',
                        next_eligible_at = now() + make_interval(secs => 1),
                        updated_at = now()
        WHERE job_id = %s AND state = 'reconciliation_required'
          AND current_attempt = %s
        """,
        (claim.job_id, claim.attempt),
    )
    _close_attempt(cursor, claim, "rolled_back", "transient")
    _delete_lease(cursor, claim)


def _close_attempt(cursor, claim, publication, category) -> None:
    cursor.execute(
        """
        UPDATE job_attempts
        SET is_current = false, finished_at = COALESCE(finished_at, now()),
            publication_state = %s, result_category = %s
        WHERE job_id = %s AND attempt = %s AND is_current
          AND coordinator_instance_id = %s AND fencing_epoch = %s
        """,
        (
            publication,
            category,
            claim.job_id,
            claim.attempt,
            claim.instance_id,
            claim.fencing_epoch,
        ),
    )
    if cursor.rowcount != 1:
        raise RuntimeError("reconciliation attempt closure failed")


def _delete_lease(cursor, claim) -> None:
    cursor.execute(
        """
        DELETE FROM graph_leases
        WHERE graph_id = %s AND job_id = %s AND attempt = %s
          AND coordinator_instance_id = %s AND fencing_epoch = %s
        """,
        (
            claim.graph_id,
            claim.job_id,
            claim.attempt,
            claim.instance_id,
            claim.fencing_epoch,
        ),
    )
    if cursor.rowcount != 1:
        raise RuntimeError("reconciliation lease release failed")
    cursor.execute(
        """
        UPDATE coalescing_state SET running_job_id = NULL
        WHERE graph_id = %s AND job_kind_family = 'refresh_graph'
          AND running_job_id = %s
        """,
        (claim.graph_id, claim.job_id),
    )
