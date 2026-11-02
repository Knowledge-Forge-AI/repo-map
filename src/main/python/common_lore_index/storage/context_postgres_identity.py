"""PostgreSQL accepted-publication identity SQL and parser for W4 context operations."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
from typing import Any

from common_lore_index.retrieval.context_identity import (
    ContextIdentityError,
    normalize_accepted_publication,
    parse_snapshot_vector as parse_strict_snapshot_vector,
)
from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage.sql_core import sql_literal


def postgres_repo_predicate_sql(
    repository_identity: str | None,
    root_path: str,
    *,
    context_identity: bool = False,
) -> str:
    """Return repository matching predicate; context_identity forbids root_path fallback."""
    if context_identity:
        if not repository_identity:
            return "FALSE"
        return f"repo.repository_identity = {sql_literal(repository_identity)}"
    return (
        f"repo.repository_identity = {sql_literal(repository_identity)}"
        if repository_identity
        else f"repo.root_path = {sql_literal(root_path)}"
    )


def postgres_accepted_run_cte_sql(*, context_identity: bool = False) -> str:
    """Return the accepted_run CTE body for PostgreSQL navigation/location queries."""
    extra_cols = ""
    latest_complete_guard = ""
    if context_identity:
        extra_cols = """
        mr.repository_id AS repository_id,
        r.snapshot_manifest_id,
        r.extraction_receipt_id,
        r.graph_candidate_id,
        r.publication_job_id,
        r.publication_attempt,
        r.snapshot_vector_json,"""
        latest_complete_guard = """
      AND r.id = (
          SELECT max(r_latest.id)
          FROM public.runs r_latest
          WHERE r_latest.repository_id = mr.repository_id
            AND r_latest.status = 'complete'
      )"""
    return f"""accepted_run AS MATERIALIZED (
    SELECT{extra_cols}
        r.id AS run_id,
        r.publication_bundle_id,
        (
            SELECT count(*)::int
            FROM public.runs r2
            WHERE r2.repository_id = mr.repository_id
              AND r2.status = 'complete'
              AND r2.execution_route = 'portable-worker-v1'
              AND r2.publication_bundle_id IS NOT NULL
              AND r2.id <= r.id
        ) AS generation
    FROM public.runs r
    JOIN matched_repo mr ON mr.repository_id = r.repository_id
    WHERE r.status = 'complete'
      AND r.execution_route = 'portable-worker-v1'
      AND r.publication_bundle_id IS NOT NULL
      AND r.snapshot_manifest_id IS NOT NULL
      AND r.extraction_receipt_id IS NOT NULL
      AND r.graph_candidate_id IS NOT NULL
      AND r.snapshot_vector_json IS NOT NULL{latest_complete_guard}
      AND (
          r.portable_execution_mode <> 'coordinator'
          OR EXISTS (
              SELECT 1
              FROM public.graph_publication_authority gpa
              WHERE gpa.repository_id = mr.repository_id
                AND gpa.last_run_id = r.id
          )
      )
      AND NOT EXISTS (
          SELECT 1
          FROM public.graph_publication_authority gpa
          WHERE gpa.repository_id = mr.repository_id
            AND gpa.last_run_id IS NOT NULL
            AND gpa.last_run_id <> r.id
      )
    ORDER BY r.id DESC
    LIMIT 1
)"""


def postgres_accepted_json_sql(*, context_identity: bool = False) -> str:
    """Return the SQL json_build_object expression for accepted_run."""
    if not context_identity:
        return """json_build_object(
            'generation', acc.generation,
            'run_id', acc.run_id,
            'publication_bundle_id', acc.publication_bundle_id
        )"""
    return """json_build_object(
            'repository_id', acc.repository_id,
            'generation', acc.generation,
            'run_id', acc.run_id,
            'publication_bundle_id', acc.publication_bundle_id,
            'snapshot_manifest_id', acc.snapshot_manifest_id,
            'extraction_receipt_id', acc.extraction_receipt_id,
            'graph_candidate_id', acc.graph_candidate_id,
            'publication_job_id', acc.publication_job_id,
            'publication_attempt', acc.publication_attempt,
            'snapshot_vector_json', acc.snapshot_vector_json
        )"""


def parse_snapshot_vector(raw_vector: Any) -> list[list[Any]]:
    """Normalize snapshot_vector_json into [[binding_id, revision, snapshot_id], ...]."""
    if isinstance(raw_vector, str):
        try:
            parsed = json.loads(raw_vector)
        except (TypeError, ValueError) as exc:
            raise StorageSchemaError("malformed snapshot_vector_json in accepted run") from exc
    else:
        parsed = raw_vector
    try:
        parsed_vector = parse_strict_snapshot_vector(parsed)
    except (ContextIdentityError, TypeError) as exc:
        raise StorageSchemaError("malformed snapshot_vector in accepted run") from exc
    return [list(item) for item in parsed_vector]


def format_postgres_accepted_publication(
    accepted: Mapping[str, Any],
    *,
    context_identity: bool = False,
) -> dict[str, Any]:
    """Format accepted_publication dict from PostgreSQL JSON payload."""
    if not context_identity:
        return {
            "generation": int(accepted["generation"]),
            "run_id": int(accepted["run_id"]),
            "publication_bundle_id": str(accepted["publication_bundle_id"]),
        }
    try:
        identity_input = dict(accepted)
        if "snapshot_vector_json" in identity_input:
            identity_input["snapshot_vector_json"] = parse_snapshot_vector(
                identity_input["snapshot_vector_json"]
            )
        normalized = normalize_accepted_publication(identity_input, require_pin=False)
    except (ContextIdentityError, TypeError) as exc:
        raise StorageSchemaError("malformed accepted context publication") from exc
    base: dict[str, Any] = {
        "generation": normalized["generation"],
        "run_id": normalized["run_id"],
        "publication_bundle_id": normalized["publication_bundle_id"],
    }
    base.update(
        {
            "repository_id": (
                int(accepted["repository_id"])
                if accepted.get("repository_id") is not None
                else None
            ),
            "snapshot_manifest_id": normalized["snapshot_manifest_id"],
            "extraction_receipt_id": normalized["extraction_receipt_id"],
            "graph_candidate_id": (
                str(accepted["graph_candidate_id"])
                if accepted.get("graph_candidate_id") is not None
                else None
            ),
            "publication_job_id": normalized["publication_job_id"],
            "publication_attempt": normalized["publication_attempt"],
            "snapshot_vector": [list(item) for item in normalized["snapshot_vector"]],
        }
    )
    return base


def build_postgres_context_identity_sql(repository_identity: str | None) -> str:
    """Build single-statement SQL to read accepted publication identity on PostgreSQL."""
    repo_pred = postgres_repo_predicate_sql(
        repository_identity, "", context_identity=True
    )
    return f"""WITH matched_repo AS MATERIALIZED (
    SELECT repo.id AS repository_id
    FROM public.repositories repo
    WHERE {repo_pred}
    ORDER BY repo.id DESC
    LIMIT 1
),
{postgres_accepted_run_cte_sql(context_identity=True)}
SELECT json_build_object(
    'has_accepted', EXISTS (SELECT 1 FROM accepted_run),
    'accepted', (
        SELECT {postgres_accepted_json_sql(context_identity=True)}
        FROM accepted_run acc
    )
)::text;"""


def read_postgres_context_identity_with_executor(
    repository_identity: str | None,
    *,
    executor: Callable[[str], Any],
) -> dict[str, Any]:
    """Execute single-statement PostgreSQL context identity readback."""
    if not repository_identity:
        return {"status": "unavailable", "reason": "publication_absent", "accepted_publication": None}
    sql = build_postgres_context_identity_sql(repository_identity)
    payload = executor(sql)
    if not isinstance(payload, Mapping):
        raise StorageSchemaError("malformed PostgreSQL context identity readback")
    if not payload.get("has_accepted") or not isinstance(payload.get("accepted"), Mapping):
        return {"status": "unavailable", "reason": "publication_absent", "accepted_publication": None}
    return {
        "status": "ok",
        "reason": None,
        "accepted_publication": format_postgres_accepted_publication(
            payload["accepted"], context_identity=True
        ),
    }


__all__ = [
    "build_postgres_context_identity_sql",
    "format_postgres_accepted_publication",
    "parse_snapshot_vector",
    "postgres_accepted_json_sql",
    "postgres_accepted_run_cte_sql",
    "postgres_repo_predicate_sql",
    "read_postgres_context_identity_with_executor",
]
