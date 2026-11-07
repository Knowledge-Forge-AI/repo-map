"""JSON and text formatters for cloe ops lexical-build, lexical-query, and lexical-revoke."""

from __future__ import annotations

from dataclasses import replace
import json
from typing import Any

from common_lore_index.ops.lexical_publication import LexicalBuildOutcome
from common_lore_index.retrieval.query_contracts import (
    CapabilityState,
    OmissionRecord,
    QueryEnvelope,
)
from common_lore_index.storage.lexical_revoke import LexicalRevocationOutcome
from common_lore_index.storage.lexical_driver import LexicalStorageError

LEXICAL_OPS_SCHEMA_VERSION = "cloe-ops-lexical-v1"
MAX_SERIALIZED_LEXICAL_OUTPUT_BYTES = 65536


def _require_serialized_budget(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate the final JSON plus the newline emitted by the CLI."""
    if len(json.dumps(payload, sort_keys=True).encode("utf-8")) + 1 > MAX_SERIALIZED_LEXICAL_OUTPUT_BYTES:
        raise LexicalStorageError(
            "output_budget_exceeded",
            "output_budget_exceeded: a truthful response cannot fit the output limit; "
            "an operation may have completed; inspect current state before retrying",
        )
    return payload


def _enforce_serialized_budget(payload: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    if len(encoded) + 1 <= MAX_SERIALIZED_LEXICAL_OUTPUT_BYTES:
        return payload
    cmd = str(payload.get("command") or "")
    if cmd == "lexical-build":
        bounded = dict(payload)
        bounded["omissions"] = list(payload.get("omissions", ()))[:8] + [
            {
                "binding_id": (payload.get("admitted_binding_ids") or ["graph"])[0],
                "source_relative_path": None,
                "reason_code": "output_budget_exceeded",
                "detail": f"serialized lexical-build output ({len(encoded)} bytes) exceeded {MAX_SERIALIZED_LEXICAL_OUTPUT_BYTES}-byte ceiling",
            }
        ]
        bounded["status"] = "partial"
        bounded["reason"] = "output_budget_exceeded"
        bounded["output_truncated"] = True
        return _require_serialized_budget(bounded)
    if cmd == "lexical-revoke":
        bounded = dict(payload)
        bounded["revoked_generation_ids"] = list(payload.get("revoked_generation_ids", ()))[:16]
        bounded["status"] = "partial"
        bounded["reason"] = "output_budget_exceeded"
        bounded["output_truncated"] = True
        return _require_serialized_budget(bounded)
    return _require_serialized_budget(payload)


def lexical_build_to_jsonable(outcome: LexicalBuildOutcome) -> dict[str, Any]:
    """Serialize LexicalBuildOutcome as a public-safe cloe-ops-lexical-v1 JSON dictionary."""
    base = outcome.to_dict()
    pub = outcome.published
    truncated_docs = sum(
        1 for o in outcome.omissions if o.reason_code == "oversize_projected_file_truncated"
    )
    payload = {
        "schema_version": LEXICAL_OPS_SCHEMA_VERSION,
        "command": "lexical-build",
        "status": "ready" if outcome.result == "published" else outcome.result,
        "reason": outcome.refusal_code or "ok",
        "generation_id": pub.lexical_generation_id if pub is not None else None,
        "accepted_run_id": pub.run_id if pub is not None else None,
        "document_count": pub.projected_document_count if pub is not None else 0,
        "chunk_count": pub.projected_chunk_count if pub is not None else 0,
        "projected_body_bytes": outcome.aggregate_projected_bytes,
        "omission_count": len(outcome.omissions),
        "truncated_document_count": truncated_docs,
        **base,
    }
    return _enforce_serialized_budget(payload)


def format_lexical_build_table(outcome: LexicalBuildOutcome) -> str:
    """Format LexicalBuildOutcome as a compact human-readable summary."""
    lines = [
        f"lexical-build {outcome.graph_id}: {outcome.result}",
        f"database: {outcome.database}",
        f"policy_digest: {outcome.policy_digest}",
    ]
    if outcome.refusal_code is not None:
        lines.append(f"refusal_code: {outcome.refusal_code}")
    if outcome.published is not None:
        pub = outcome.published
        lines.extend(
            [
                f"lexical_generation_id: {pub.lexical_generation_id}",
                f"run_id: {pub.run_id}",
                f"publication_bundle_id: {pub.publication_bundle_id}",
                f"snapshot_manifest_id: {pub.snapshot_manifest_id}",
                f"projected_documents: {pub.projected_document_count}",
                f"projected_chunks: {pub.projected_chunk_count}",
                f"omitted_records: {pub.omitted_record_count}",
            ]
        )
    return "\n".join(lines)


def lexical_query_to_jsonable(
    graph_id: str,
    query_style: str,
    envelope: QueryEnvelope,
) -> dict[str, Any]:
    """Serialize a lexical QueryEnvelope with a 65,536-byte UTF-8 output budget guard."""
    payload = {
        "schema_version": LEXICAL_OPS_SCHEMA_VERSION,
        "command": "lexical-query",
        "status": envelope.capability_state.value,
        "reason": envelope.refusal_code or envelope.capability_state.value,
        "storage_backend": "postgresql",
        "graph_id": graph_id,
        "query_style": query_style,
        "capability_state": envelope.capability_state.value,
        "scope_complete": envelope.scope_complete,
        "hit_count": len(envelope.hits),
        "omission_count": len(envelope.omissions),
        "envelope": envelope.to_dict(),
    }
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    if len(encoded) + 1 <= MAX_SERIALIZED_LEXICAL_OUTPUT_BYTES:
        return payload

    budget_omission = OmissionRecord(
        binding_id=envelope.hits[0].locator.binding_id if envelope.hits else "graph",
        source_relative_path=None,
        reason_code="output_budget_exceeded",
        detail=f"serialized lexical output ({len(encoded)} bytes) exceeded {MAX_SERIALIZED_LEXICAL_OUTPUT_BYTES}-byte ceiling",
    ).validate()
    bounded_env = replace(
        envelope,
        capability_state=CapabilityState.PARTIAL,
        scope_complete=False,
        hits=(),
        omissions=(*envelope.omissions[:16], budget_omission),
    ).validate()
    return _require_serialized_budget({
        "schema_version": LEXICAL_OPS_SCHEMA_VERSION,
        "command": "lexical-query",
        "status": CapabilityState.PARTIAL.value,
        "reason": "output_budget_exceeded",
        "storage_backend": "postgresql",
        "graph_id": graph_id,
        "query_style": query_style,
        "capability_state": CapabilityState.PARTIAL.value,
        "scope_complete": False,
        "hit_count": 0,
        "omission_count": len(bounded_env.omissions),
        "envelope": bounded_env.to_dict(),
    })


def format_lexical_query_table(
    graph_id: str,
    query_style: str,
    envelope: QueryEnvelope,
) -> str:
    """Format a lexical QueryEnvelope as a public-safe table without raw file content."""
    lines = [
        f"lexical-query {graph_id} ({query_style}): {envelope.capability_state.value} "
        f"(hits={len(envelope.hits)}, omissions={len(envelope.omissions)}, "
        f"scope_complete={envelope.scope_complete})",
    ]
    if envelope.hits:
        lines.append("rank | binding_id | path | lines | score | canonical_key")
        for hit in envelope.hits:
            loc = hit.locator
            span = (
                f"{loc.start_line}-{loc.end_line}"
                if loc.start_line is not None and loc.end_line is not None
                else "-"
            )
            score_str = f"{hit.score:.6f}" if hit.score is not None else "-"
            ckey = loc.canonical_key or "-"
            lines.append(
                f"{hit.rank} | {loc.binding_id} | {loc.source_relative_path} | "
                f"{span} | {score_str} | {ckey}"
            )
    if envelope.omissions:
        lines.append("omission_binding | path | reason_code")
        for om in envelope.omissions:
            lines.append(
                f"{om.binding_id} | {om.source_relative_path or '*'} | {om.reason_code}"
            )
    return "\n".join(lines)


def lexical_revoke_to_jsonable(
    outcome: LexicalRevocationOutcome,
    *,
    database: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Serialize LexicalRevocationOutcome as a public-safe cloe-ops-lexical-v1 JSON dictionary."""
    payload = outcome.to_dict()
    status = "dry_run" if dry_run else "revoked"
    return _enforce_serialized_budget(
        {
            "schema_version": LEXICAL_OPS_SCHEMA_VERSION,
            "command": "lexical-revoke",
            "status": status,
            "reason": outcome.reason,
            "storage_backend": "postgresql",
            "database": database,
            "result": status,
            "dry_run": dry_run,
            "generations_invalidated": outcome.revoked_generation_count,
            "documents_purged": outcome.purged_document_count,
            "chunks_purged": outcome.purged_chunk_count,
            "authority_removed": outcome.purged_authority_count > 0,
            **payload,
        }
    )


def format_lexical_revoke_table(
    outcome: LexicalRevocationOutcome,
    *,
    database: str,
    dry_run: bool = False,
) -> str:
    """Format LexicalRevocationOutcome as a human-readable summary."""
    status = "dry_run" if dry_run else "revoked"
    return "\n".join(
        [
            f"lexical-revoke {outcome.graph_id}: {status}",
            f"database: {database}",
            f"repository_id: {outcome.repository_id}",
            f"revoked_generations: {outcome.revoked_generation_count}",
            f"purged_authority_rows: {outcome.purged_authority_count}",
            f"purged_documents: {outcome.purged_document_count}",
            f"purged_chunks: {outcome.purged_chunk_count}",
            f"purged_omissions: {outcome.purged_omission_count}",
            f"reason: {outcome.reason}",
        ]
    )


__all__ = [
    "format_lexical_build_table",
    "format_lexical_query_table",
    "format_lexical_revoke_table",
    "lexical_build_to_jsonable",
    "lexical_query_to_jsonable",
    "lexical_revoke_to_jsonable",
]
