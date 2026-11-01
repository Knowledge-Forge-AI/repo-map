"""Transactional lifecycle and publication fence verification for cloe_lexical."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
import json
from typing import Any

from common_lore_index.retrieval.lexical_capture import LexicalCapturePlan
from common_lore_index.retrieval.lexical_policy import PublicationFence
from common_lore_index.storage.lexical_driver import (
    LexicalStorageError,
    execute_fetchone,
    sanitize_driver_exception,
)
from common_lore_index.storage import lexical_build_lease
from common_lore_index.storage.lexical_population import (
    claim_lexical_generation,
    populate_lexical_generation_rows,
)
from common_lore_index.storage.publication import (
    RunPublicationReceipt,
    publication_receipt_from_mapping,
)
_RECEIPT_JSON_COLS = ", ".join(
    f"'{f}', runs.{f}" for f in RunPublicationReceipt.field_names()
)
_LC_RECEIPT_JSON_COLS = ", ".join(
    f"'{f}', lc.{f}" for f in RunPublicationReceipt.field_names()
)

READ_ACCEPTED_GRAPH_PUBLICATION_SQL = f"""
WITH matched_repo AS (
    SELECT r.id AS repository_id, r.name AS repository_name, r.repository_identity
    FROM public.repositories r
    WHERE (%(repository_identity)s::text IS NOT NULL AND r.repository_identity = %(repository_identity)s)
       OR (r.repository_identity IS NULL AND %(repository_name)s::text IS NOT NULL AND r.name = %(repository_name)s)
       OR (r.repository_identity IS NULL AND %(root_path)s::text IS NOT NULL AND r.root_path = %(root_path)s)
    ORDER BY
        (r.repository_identity = %(repository_identity)s) DESC NULLS LAST,
        (r.name = %(repository_name)s) DESC NULLS LAST,
        (r.root_path = %(root_path)s) DESC NULLS LAST, r.id DESC
    LIMIT 1
),
latest_complete AS (
    SELECT runs.id AS run_id, runs.repository_id, runs.execution_route,
           runs.publication_bundle_id, runs.snapshot_manifest_id,
           runs.extraction_receipt_id, runs.graph_candidate_id, runs.snapshot_vector_json,
           runs.portable_execution_mode,
           json_build_object({_RECEIPT_JSON_COLS})::text AS publication_receipt_json
    FROM public.runs runs
    JOIN matched_repo mr ON mr.repository_id = runs.repository_id
    WHERE runs.status = 'complete' ORDER BY runs.id DESC LIMIT 1
)
SELECT mr.repository_id, mr.repository_name, mr.repository_identity,
       lc.run_id, lc.execution_route, lc.publication_bundle_id, lc.snapshot_manifest_id,
       lc.extraction_receipt_id, lc.graph_candidate_id, lc.snapshot_vector_json,
       (
           lc.portable_execution_mode <> 'coordinator'
           OR EXISTS (
               SELECT 1 FROM public.graph_publication_authority gpa
               WHERE gpa.repository_id = mr.repository_id
                 AND gpa.last_run_id = lc.run_id
           )
       ) AS authority_consistent,
       lc.publication_receipt_json
FROM matched_repo mr LEFT JOIN latest_complete lc ON lc.repository_id = mr.repository_id
"""

VERIFY_FENCE_AT_COMMIT_SQL = f"""
SELECT lc.id AS run_id, lc.execution_route, lc.publication_bundle_id,
       lc.snapshot_manifest_id, lc.extraction_receipt_id, lc.graph_candidate_id,
       lc.snapshot_vector_json,
       (
           lc.portable_execution_mode <> 'coordinator'
           OR EXISTS (
               SELECT 1 FROM public.graph_publication_authority gpa
               WHERE gpa.repository_id = lc.repository_id AND gpa.last_run_id = lc.id
           )
       ) AS authority_consistent,
       json_build_object({_LC_RECEIPT_JSON_COLS})::text AS publication_receipt_json,
       pg_try_advisory_xact_lock(pg_catalog.hashtextextended('{lexical_build_lease.LIFECYCLE_ADVISORY_NAMESPACE}', lc.repository_id::bigint)) AS advisory_lock_acquired,
       NOT EXISTS (
           SELECT 1 FROM cloe_lexical.generations g
           WHERE g.repository_id = lc.repository_id
             AND g.lexical_generation_id <> %s
             AND g.state = 'building'
             AND (g.lease_expires_at IS NULL OR g.lease_expires_at > clock_timestamp())
       ) AS no_competing_builder,
       EXISTS (
           SELECT 1 FROM cloe_lexical.generations g
           WHERE g.repository_id = lc.repository_id
             AND g.lexical_generation_id = %s
             AND g.builder_owner_id = %s
             AND g.state = 'building'
             AND g.lease_expires_at > clock_timestamp()
             AND (SELECT count(*) FROM cloe_lexical.documents d WHERE d.repository_id = g.repository_id AND d.lexical_generation_id = g.lexical_generation_id) = g.projected_document_count
             AND (SELECT count(*) FROM cloe_lexical.chunks c WHERE c.repository_id = g.repository_id AND c.lexical_generation_id = g.lexical_generation_id) = g.projected_chunk_count
             AND (SELECT count(*) FROM cloe_lexical.omissions o WHERE o.repository_id = g.repository_id AND o.lexical_generation_id = g.lexical_generation_id) = g.omitted_record_count
       ) AS lease_and_counts_valid
FROM public.runs lc
WHERE lc.repository_id = %s AND lc.status = 'complete'
ORDER BY lc.id DESC LIMIT 1 FOR SHARE
"""

REVOKE_LIMITED_ROLES_SQL = """
DO $cloe_lexical_roles$
DECLARE
    role_name text;
BEGIN
    REVOKE ALL ON SCHEMA cloe_lexical FROM PUBLIC;
    REVOKE ALL ON ALL TABLES IN SCHEMA cloe_lexical FROM PUBLIC;
    REVOKE ALL ON ALL SEQUENCES IN SCHEMA cloe_lexical FROM PUBLIC;
    ALTER DEFAULT PRIVILEGES IN SCHEMA cloe_lexical REVOKE ALL ON TABLES FROM PUBLIC;
    ALTER DEFAULT PRIVILEGES IN SCHEMA cloe_lexical REVOKE ALL ON SEQUENCES FROM PUBLIC;
    ALTER DEFAULT PRIVILEGES IN SCHEMA cloe_lexical REVOKE ALL ON FUNCTIONS FROM PUBLIC;
    FOREACH role_name IN ARRAY ARRAY[
        'repomap_read_status',
        'repomap_refresh_publication',
        'repomap_coordinator_control'
    ]
    LOOP
        IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = role_name) THEN
            EXECUTE format('REVOKE ALL ON SCHEMA cloe_lexical FROM %I', role_name);
            EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA cloe_lexical FROM %I', role_name);
            EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA cloe_lexical FROM %I', role_name);
            EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA cloe_lexical REVOKE ALL ON TABLES FROM %I', role_name);
            EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA cloe_lexical REVOKE ALL ON SEQUENCES FROM %I', role_name);
            EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA cloe_lexical REVOKE ALL ON FUNCTIONS FROM %I', role_name);
        END IF;
    END LOOP;
END
$cloe_lexical_roles$;
"""


@dataclass(frozen=True)
class AcceptedGraphPublicationRecord:
    """Accepted portable graph publication resolved from public.repositories and public.runs."""

    repository_id: int
    repository_name: str
    repository_identity: str | None
    run_id: int
    publication_bundle_id: str
    snapshot_manifest_id: str
    extraction_receipt_id: str
    graph_candidate_id: str
    snapshot_vector: tuple[tuple[str, int, str], ...]
    snapshot_vector_json: str
    publication_receipt_json: str = "{}"
    receipt: RunPublicationReceipt | None = None

    def to_publication_fence(self) -> PublicationFence:
        return PublicationFence(
            run_id=self.run_id,
            publication_bundle_id=self.publication_bundle_id,
            snapshot_manifest_id=self.snapshot_manifest_id,
            snapshot_vector=self.snapshot_vector,
        ).validate()


@dataclass(frozen=True)
class LexicalBuildSummary:
    """Public-safe summary of a published cloe_lexical generation."""

    lexical_generation_id: str
    repository_id: int
    run_id: int
    publication_bundle_id: str
    snapshot_manifest_id: str
    extraction_receipt_id: str
    graph_candidate_id: str
    policy_digest: str
    representation_version: str
    text_config_regconfig: str
    ranking_function: str
    normalization_flags: int
    alias_split_rule_version: str
    projected_document_count: int
    projected_chunk_count: int
    omitted_record_count: int
    aggregate_input_bytes: int
    aggregate_projected_bytes: int
    superseded_generation_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


PublishedLexicalGeneration = LexicalBuildSummary


def parse_snapshot_vector_json(raw_json: str) -> tuple[tuple[str, int, str], ...]:
    """Parse snapshot_vector_json from either 3-tuple array or dict array form."""
    try:
        parsed = json.loads(raw_json)
    except (TypeError, ValueError) as error:
        raise LexicalStorageError("lexical_invalid_snapshot_vector", "stored snapshot_vector_json is not valid JSON") from error
    if not isinstance(parsed, list) or not parsed:
        raise LexicalStorageError("lexical_invalid_snapshot_vector", "stored snapshot_vector_json must be a non-empty JSON list")
    entries: list[tuple[str, int, str]] = []
    for item in parsed:
        if isinstance(item, list) and len(item) == 3:
            b_id, rev, snap_id = str(item[0]), int(item[1]), str(item[2])
        elif isinstance(item, dict):
            b_id = str(item["binding_id"])
            rev = int(item["binding_revision"] if "binding_revision" in item else item["revision"])
            snap_id = str(item["snapshot_id"])
        else:
            raise LexicalStorageError("lexical_invalid_snapshot_vector", "stored snapshot_vector_json entry has unsupported shape")
        entries.append((b_id, rev, snap_id))
    return tuple(sorted(entries))


def read_accepted_graph_publication(
    connection: Any,
    *,
    repository_identity: str | None = None,
    repository_name: str | None = None,
    root_path: str | None = None,
) -> AcceptedGraphPublicationRecord | None:
    """Resolve the active accepted portable graph publication for a repository."""
    row = execute_fetchone(
        connection, READ_ACCEPTED_GRAPH_PUBLICATION_SQL,
        {"repository_identity": repository_identity, "repository_name": repository_name, "root_path": root_path},
        operation="read_accepted_publication",
    )
    if row is None:
        return None
    (
        repo_id, repo_name, repo_identity, run_id, execution_route,
        bundle_id, manifest_id, receipt_id, candidate_id, vector_json, authority_consistent,
    ) = row[:11]
    raw_receipt_json = str(row[11]) if len(row) >= 12 and row[11] is not None else "{}"
    if (
        run_id is None or execution_route != "portable-worker-v1"
        or not bundle_id or not manifest_id or not receipt_id
        or not candidate_id or not vector_json or not authority_consistent
    ):
        return None
    receipt_obj: RunPublicationReceipt | None = None
    canonical_receipt_json = "{}"
    if raw_receipt_json != "{}":
        try:
            receipt_obj = publication_receipt_from_mapping(json.loads(raw_receipt_json))
        except Exception:
            return None
        if receipt_obj is None or receipt_obj.portable is None:
            return None
        canonical_receipt_json = json.dumps(receipt_obj.to_mapping(), sort_keys=True, separators=(",", ":"))
    vector = parse_snapshot_vector_json(str(vector_json))
    return AcceptedGraphPublicationRecord(
        int(repo_id), str(repo_name), str(repo_identity) if repo_identity is not None else None,
        int(run_id), str(bundle_id), str(manifest_id), str(receipt_id), str(candidate_id), vector, str(vector_json),
        publication_receipt_json=canonical_receipt_json, receipt=receipt_obj,
    )


def publish_lexical_generation(
    connection: Any,
    plan: LexicalCapturePlan,
    *,
    builder_owner_id: str = "local-builder",
    live_policy_recheck: Callable[[], str] | None = None,
) -> LexicalBuildSummary:
    """Populate and atomically publish a cloe_lexical generation if fence is unchanged."""
    claim_lexical_generation(connection, plan, builder_owner_id=builder_owner_id)
    populate_lexical_generation_rows(
        connection,
        plan,
        builder_owner_id=builder_owner_id,
        claim_generation=False,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                VERIFY_FENCE_AT_COMMIT_SQL,
                (
                    plan.lexical_generation_id,
                    plan.lexical_generation_id,
                    builder_owner_id,
                    plan.repository_id,
                ),
            )
            fence_row = cursor.fetchone()
            if fence_row is None or len(fence_row) != 12:
                raise LexicalStorageError("cloe_lexical_publication_fence_mismatch", "no complete graph publication exists at lexical publish commit")
            (
                live_run_id, live_route, live_bundle_id, live_manifest_id,
                live_receipt_id, live_candidate_id, live_vector_json, authority_consistent,
            ) = fence_row[:8]
            advisory_ok = fence_row[9] is True
            no_competing = fence_row[10] is True
            counts_valid = fence_row[11] is True
            if not advisory_ok or not no_competing:
                raise LexicalStorageError("cloe_lexical_concurrent_build_active", "another lexical builder holds the repository build lock or active lease")
            if not counts_valid:
                raise LexicalStorageError("cloe_lexical_count_verification_failed", "building generation lease expired or row counts did not match capture plan")
            if live_policy_recheck is not None and live_policy_recheck() != plan.policy_digest:
                raise LexicalStorageError("cloe_lexical_policy_digest_mismatch", "on-disk lexical policy digest changed before generation activation")
            receipt_mismatch = False
            if len(fence_row) >= 9 and plan.publication_receipt_json not in {"", "{}"}:
                try:
                    live_rec = publication_receipt_from_mapping(json.loads(str(fence_row[8])))
                    live_rec_json = json.dumps(live_rec.to_mapping(), sort_keys=True, separators=(",", ":")) if live_rec is not None else ""
                    receipt_mismatch = live_rec_json != plan.publication_receipt_json
                except Exception:
                    receipt_mismatch = True
            if (
                int(live_run_id) != plan.run_id or live_route != "portable-worker-v1"
                or str(live_bundle_id) != plan.publication_bundle_id
                or str(live_manifest_id) != plan.snapshot_manifest_id
                or str(live_receipt_id) != plan.extraction_receipt_id
                or str(live_candidate_id) != plan.graph_candidate_id
                or not authority_consistent or receipt_mismatch
                or parse_snapshot_vector_json(str(live_vector_json)) != tuple(sorted(plan.snapshot_vector))
            ):
                raise LexicalStorageError("cloe_lexical_publication_fence_mismatch", "accepted graph publication changed before lexical generation commit")
            cursor.execute(
                """
                UPDATE cloe_lexical.generations
                SET state = 'published', published_at = clock_timestamp(),
                    revoked_at = NULL, revocation_reason = NULL,
                    builder_owner_id = NULL, lease_expires_at = NULL
                WHERE repository_id = %s
                  AND lexical_generation_id = %s
                  AND state = 'building'
                  AND builder_owner_id = %s
                  AND lease_expires_at > clock_timestamp()
                """,
                (plan.repository_id, plan.lexical_generation_id, builder_owner_id),
            )
            if int(cursor.rowcount or 0) != 1:
                raise LexicalStorageError(
                    "cloe_lexical_generation_not_published",
                    "building lexical generation row was not found for publication",
                )
            cursor.execute(
                """
                INSERT INTO cloe_lexical.authority (
                    repository_id, lexical_generation_id, run_id,
                    publication_bundle_id, snapshot_manifest_id, policy_digest, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, clock_timestamp())
                ON CONFLICT (repository_id) DO UPDATE SET
                    lexical_generation_id = EXCLUDED.lexical_generation_id,
                    run_id = EXCLUDED.run_id,
                    publication_bundle_id = EXCLUDED.publication_bundle_id,
                    snapshot_manifest_id = EXCLUDED.snapshot_manifest_id,
                    policy_digest = EXCLUDED.policy_digest,
                    updated_at = clock_timestamp()
                """,
                (
                    plan.repository_id, plan.lexical_generation_id, plan.run_id,
                    plan.publication_bundle_id, plan.snapshot_manifest_id, plan.policy_digest,
                ),
            )
            lexical_build_lease.purge_superseded_published_rows(
                cursor,
                repository_id=plan.repository_id,
                lexical_generation_id=plan.lexical_generation_id,
            )
            cursor.execute(
                """
                UPDATE cloe_lexical.generations
                SET state = 'invalidated', revoked_at = clock_timestamp(),
                    revocation_reason = 'superseded_by_newer_lexical_generation',
                    builder_owner_id = NULL, lease_expires_at = NULL
                WHERE repository_id = %s
                  AND lexical_generation_id <> %s
                  AND state = 'published'
                """,
                (plan.repository_id, plan.lexical_generation_id),
            )
            superseded_count = int(cursor.rowcount or 0)
            cursor.execute(REVOKE_LIMITED_ROLES_SQL)
    except Exception as error:
        raise sanitize_driver_exception(error, operation="lexical_publish") from None

    return LexicalBuildSummary(
        plan.lexical_generation_id, plan.repository_id, plan.run_id,
        plan.publication_bundle_id, plan.snapshot_manifest_id,
        plan.extraction_receipt_id, plan.graph_candidate_id, plan.policy_digest,
        plan.representation_version, plan.text_config_regconfig,
        plan.ranking_function, plan.normalization_flags,
        plan.alias_split_rule_version, plan.projected_document_count,
        plan.projected_chunk_count, plan.omitted_record_count,
        plan.aggregate_input_bytes, plan.aggregate_projected_bytes,
        superseded_count,
    )


__all__ = [
    "AcceptedGraphPublicationRecord", "LexicalBuildSummary",
    "PublishedLexicalGeneration", "READ_ACCEPTED_GRAPH_PUBLICATION_SQL",
    "REVOKE_LIMITED_ROLES_SQL", "VERIFY_FENCE_AT_COMMIT_SQL",
    "parse_snapshot_vector_json", "publish_lexical_generation",
    "read_accepted_graph_publication",
]
