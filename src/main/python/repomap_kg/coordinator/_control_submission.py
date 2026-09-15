from __future__ import annotations

import hashlib
import json
import re
import uuid

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from repomap_kg.coordinator._control_types import (
    ConnectionFactory,
    SubmissionResult,
)
from repomap_kg.coordinator.contracts import JobRequest, normalize_request
from repomap_kg.coordinator.limits import CoordinatorLimits
from repomap_kg.runtime.maintenance import require_transaction_admission


_SAFE_CATEGORY = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")


def submit(
    connect: ConnectionFactory,
    request: JobRequest,
    *,
    requester: str,
    limits: CoordinatorLimits,
) -> SubmissionResult:
    request = validate_request(request)
    requester = _safe_category(requester, "requester")
    idempotency_digest = hashlib.sha256(
        request.idempotency_key.encode()
    ).hexdigest()
    semantic = request.semantic_payload()
    fingerprint = hashlib.sha256(
        json.dumps(semantic, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    job_id = str(uuid.uuid4())
    priority_value = 100 if request.priority == "manual" else 50
    with connect() as connection:
        require_transaction_admission(connection)
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("LOCK TABLE jobs IN SHARE ROW EXCLUSIVE MODE")
            existing = _find_existing(
                cursor, requester, request, idempotency_digest
            )
            if existing is not None:
                if existing["request_fingerprint"] != fingerprint:
                    raise ValueError("idempotency conflict")
                return SubmissionResult(existing["job_id"], existing["state"], True)
            _enforce_admission(cursor, request, limits)
            cursor.execute(
                """
                INSERT INTO jobs(
                    job_id, schema_version, job_kind, graph_id, request_id,
                    requester, idempotency_digest, request_fingerprint,
                    priority_class, priority_value, source_generation,
                    config_generation, extractor_generation,
                    canonicalizer_generation, operation_options
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s
                )
                RETURNING job_id, state
                """,
                (
                    job_id,
                    request.schema_version,
                    request.job_kind,
                    request.graph_id,
                    request.request_id,
                    requester,
                    idempotency_digest,
                    fingerprint,
                    request.priority,
                    priority_value,
                    request.source_generation,
                    request.config_generation,
                    request.extractor_generation,
                    request.canonicalizer_generation,
                    Jsonb(dict(request.operation_options)),
                ),
            )
            inserted = cursor.fetchone()
            if inserted is None:
                raise ValueError("failed to insert job")
            return SubmissionResult(inserted["job_id"], inserted["state"], False)


def _find_existing(cursor, requester, request, digest):
    cursor.execute(
        """
        SELECT job_id, state, request_fingerprint FROM jobs
        WHERE requester = %s AND job_kind = %s AND graph_id = %s
          AND idempotency_digest = %s
        """,
        (requester, request.job_kind, request.graph_id, digest),
    )
    return cursor.fetchone()


def _enforce_admission(cursor, request, limits):
    cursor.execute(
        "SELECT count(*) AS job_count FROM jobs WHERE state NOT IN "
        "('succeeded','failed','cancelled','superseded','quarantined')"
    )
    if cursor.fetchone()["job_count"] >= limits.max_nonterminal_jobs:
        raise ValueError("nonterminal job limit reached")
    if request.priority == "manual":
        cursor.execute(
            """
            SELECT count(*) AS job_count FROM jobs
            WHERE graph_id = %s AND priority_class = 'manual'
              AND state = 'queued'
            """,
            (request.graph_id,),
        )
        if cursor.fetchone()["job_count"] >= limits.max_queued_manual_jobs_per_graph:
            raise ValueError("manual queue limit reached")


def validate_request(request: JobRequest) -> JobRequest:
    if not isinstance(request, JobRequest):
        raise TypeError("request must be a validated JobRequest")
    options = dict(request.operation_options)
    normalized = normalize_request(
        {
            "schema_version": request.schema_version,
            "job_kind": request.job_kind,
            "graph_id": request.graph_id,
            "request_id": request.request_id,
            "idempotency_key": request.idempotency_key,
            "priority": request.priority,
            "operation_options": options,
        },
        source_generation=request.source_generation,
        config_generation=request.config_generation,
        extractor_generation=request.extractor_generation,
        canonicalizer_generation=request.canonicalizer_generation,
        require_synthetic_graph=False,
    )
    if normalized != request:
        raise ValueError("request is not canonically normalized")
    _safe_category(options["reason"], "operation_options reason")
    return request


def _safe_category(value: str, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_CATEGORY.fullmatch(value):
        raise ValueError(f"{field} must be a public-safe category")
    return value
