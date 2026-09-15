"""Transactional automatic-intent coalescing for the control store."""

from __future__ import annotations

import hashlib
import json
import uuid

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from repomap_kg.coordinator._control_submission import (
    _enforce_admission,
    _safe_category,
    validate_request,
)
from repomap_kg.coordinator._control_types import ConnectionFactory, SubmissionResult
from repomap_kg.coordinator.contracts import JobRequest
from repomap_kg.coordinator.limits import CoordinatorLimits
from repomap_kg.runtime.maintenance import require_transaction_admission


def coalesce_automatic(
    connect: ConnectionFactory,
    request: JobRequest,
    *,
    requester: str,
    limits: CoordinatorLimits,
) -> SubmissionResult:
    request = validate_request(request)
    if request.priority != "automatic":
        raise ValueError("coalescing requires automatic priority")
    requester = _safe_category(requester, "requester")
    fingerprint = hashlib.sha256(
        json.dumps(
            request.semantic_payload(), sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    digest = hashlib.sha256(request.idempotency_key.encode()).hexdigest()
    with connect() as connection:
        require_transaction_admission(connection)
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("LOCK TABLE jobs IN SHARE ROW EXCLUSIVE MODE")
            cursor.execute(
                """
                SELECT * FROM coalescing_state
                WHERE graph_id = %s AND job_kind_family = 'refresh_graph'
                FOR UPDATE
                """,
                (request.graph_id,),
            )
            current = cursor.fetchone()
            if current is not None and current["paused"]:
                raise ValueError("graph intent is paused")
            generations = (
                request.source_generation,
                request.config_generation,
                request.extractor_generation,
                request.canonicalizer_generation,
            )
            if current is not None and _desired(current) == generations:
                existing_id = current["queued_job_id"] or current["running_job_id"]
                if existing_id is not None:
                    cursor.execute(
                        "SELECT state FROM jobs WHERE job_id = %s", (existing_id,)
                    )
                    existing = cursor.fetchone()
                    if existing is not None and existing["state"] not in {
                        "succeeded", "failed", "cancelled", "superseded",
                        "quarantined",
                    }:
                        return SubmissionResult(
                            existing_id, existing["state"], True
                        )
            replaced = current["queued_job_id"] if current is not None else None
            if replaced is not None:
                cursor.execute(
                    """
                    UPDATE jobs SET state = 'superseded', finished_at = now(),
                                    updated_at = now()
                    WHERE job_id = %s AND state = 'queued'
                      AND priority_class = 'automatic'
                    """,
                    (replaced,),
                )
            _enforce_admission(cursor, request, limits)
            job_id = str(uuid.uuid4())
            cursor.execute(
                """
                INSERT INTO jobs(
                    job_id, schema_version, job_kind, graph_id, request_id,
                    requester, idempotency_digest, request_fingerprint,
                    priority_class, priority_value, source_generation,
                    config_generation, extractor_generation,
                    canonicalizer_generation, operation_options
                ) VALUES (%s, 1, 'refresh_graph', %s, %s, %s, %s, %s,
                          'automatic', 50, %s, %s, %s, %s, %s)
                """,
                (
                    job_id,
                    request.graph_id,
                    request.request_id,
                    requester,
                    digest,
                    fingerprint,
                    request.source_generation,
                    request.config_generation,
                    request.extractor_generation,
                    request.canonicalizer_generation,
                    Jsonb(dict(request.operation_options)),
                ),
            )
            if replaced is not None:
                cursor.execute(
                    "UPDATE jobs SET replacement_job_id = %s WHERE job_id = %s",
                    (job_id, replaced),
                )
            _upsert_intent(cursor, request, job_id, generations)
            return SubmissionResult(job_id, "queued", False)


def _desired(row) -> tuple[str, str, str, str]:
    return (
        row["desired_source_generation"],
        row["desired_config_generation"],
        row["desired_extractor_generation"],
        row["desired_canonicalizer_generation"],
    )


def _upsert_intent(cursor, request, job_id, generations) -> None:
    cursor.execute(
        """
        INSERT INTO coalescing_state(
            graph_id, job_kind_family, desired_source_generation,
            desired_config_generation, desired_extractor_generation,
            desired_canonicalizer_generation, dirty, reason_categories,
            queued_job_id
        ) VALUES (%s, 'refresh_graph', %s, %s, %s, %s, true, %s, %s)
        ON CONFLICT (graph_id, job_kind_family) DO UPDATE SET
            desired_source_generation = EXCLUDED.desired_source_generation,
            desired_config_generation = EXCLUDED.desired_config_generation,
            desired_extractor_generation = EXCLUDED.desired_extractor_generation,
            desired_canonicalizer_generation = EXCLUDED.desired_canonicalizer_generation,
            dirty = true,
            reason_categories = EXCLUDED.reason_categories,
            queued_job_id = EXCLUDED.queued_job_id,
            last_hint_at = now()
        """,
        (
            request.graph_id,
            *generations,
            [dict(request.operation_options)["reason"]],
            job_id,
        ),
    )
