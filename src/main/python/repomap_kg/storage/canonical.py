"""Canonical storage readback query orchestration."""

from __future__ import annotations

from collections.abc import Sequence

from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.readback_driver import execute_json_readback
from repomap_kg.storage.rows import (
    CanonicalEdgeExplanationRecord,
    CanonicalEdgeRecord,
    CanonicalNeighborhoodRecord,
    CanonicalNodeRecord,
    CanonicalStorageSummaryRecord,
    canonical_edge_explanation_from_storage_payload,
    canonical_edge_record_from_storage_payload,
    canonical_neighborhood_from_storage_payload,
    canonical_node_record_from_storage_payload,
    canonical_storage_summary_from_payload,
)
from repomap_kg.storage.sql import (
    build_canonical_edge_query_sql,
    build_canonical_neighborhood_query_sql,
    build_canonical_node_query_sql,
    build_canonical_storage_summary_query_sql,
    build_explain_canonical_edge_query_sql,
)

__all__ = (
    "query_canonical_node_records",
    "query_canonical_edge_records",
    "query_canonical_neighborhood",
    "query_canonical_edge_explanation",
    "query_canonical_storage_summary",
)



def query_canonical_node_records(
    psql_args: Sequence[str],
    *,
    root_path: str,
    kind: str | None = None,
    canonical_key: str | None = None,
    path_prefix: str | None = None,
    graph_key_version: int = 1,
    limit: int | None = None,
    offset: int = 0,
    repository_identity: str | None = None,
    psql_command: str = "psql",
) -> tuple[CanonicalNodeRecord, ...]:
    payload = execute_json_readback(
        build_canonical_node_query_sql(
            root_path,
            kind=kind,
            canonical_key=canonical_key,
            path_prefix=path_prefix,
            graph_key_version=graph_key_version,
            limit=limit,
            offset=offset,
            repository_identity=repository_identity,
        ),
        psql_args=psql_args,
        psql_command=psql_command,
        label="canonical node records",
        expected_shape="array",
    )
    return tuple(canonical_node_record_from_storage_payload(item) for item in payload)


def query_canonical_edge_records(
    psql_args: Sequence[str],
    *,
    root_path: str,
    kind: str | None = None,
    source_key: str | None = None,
    target_key: str | None = None,
    graph_key_version: int = 1,
    limit: int | None = None,
    offset: int = 0,
    repository_identity: str | None = None,
    psql_command: str = "psql",
) -> tuple[CanonicalEdgeRecord, ...]:
    payload = execute_json_readback(
        build_canonical_edge_query_sql(
            root_path,
            kind=kind,
            source_key=source_key,
            target_key=target_key,
            graph_key_version=graph_key_version,
            limit=limit,
            offset=offset,
            repository_identity=repository_identity,
        ),
        psql_args=psql_args,
        psql_command=psql_command,
        label="canonical edge records",
        expected_shape="array",
    )
    return tuple(canonical_edge_record_from_storage_payload(item) for item in payload)


def query_canonical_neighborhood(
    psql_args: Sequence[str],
    *,
    root_path: str,
    node: str,
    direction: str = "both",
    depth: int = 1,
    graph_key_version: int = 1,
    node_limit: int | None = None,
    node_offset: int = 0,
    edge_limit: int | None = None,
    edge_offset: int = 0,
    repository_identity: str | None = None,
    psql_command: str = "psql",
) -> CanonicalNeighborhoodRecord:
    if depth != 1:
        raise StorageSchemaError("storage neighborhood only supports depth 1")
    payload = execute_json_readback(
        build_canonical_neighborhood_query_sql(
            root_path,
            node=node,
            direction=direction,
            graph_key_version=graph_key_version,
            node_limit=node_limit,
            node_offset=node_offset,
            edge_limit=edge_limit,
            edge_offset=edge_offset,
            repository_identity=repository_identity,
        ),
        psql_args=psql_args,
        psql_command=psql_command,
        label="canonical neighborhood",
        expected_shape="object",
    )
    return canonical_neighborhood_from_storage_payload(payload)


def query_canonical_edge_explanation(
    psql_args: Sequence[str],
    *,
    root_path: str,
    source_key: str,
    kind: str,
    target_key: str,
    identity_metadata_hash: str,
    graph_key_version: int = 1,
    evidence_limit: int | None = None,
    evidence_offset: int = 0,
    repository_identity: str | None = None,
    psql_command: str = "psql",
) -> CanonicalEdgeExplanationRecord:
    payload = execute_json_readback(
        build_explain_canonical_edge_query_sql(
            root_path,
            source_key=source_key,
            kind=kind,
            target_key=target_key,
            identity_metadata_hash=identity_metadata_hash,
            graph_key_version=graph_key_version,
            evidence_limit=evidence_limit,
            evidence_offset=evidence_offset,
            repository_identity=repository_identity,
        ),
        psql_args=psql_args,
        psql_command=psql_command,
        label="canonical edge explanation",
        expected_shape="object",
    )
    return canonical_edge_explanation_from_storage_payload(payload)


def query_canonical_storage_summary(
    psql_args: Sequence[str],
    *,
    root_path: str,
    repository_identity: str | None = None,
    psql_command: str = "psql",
) -> CanonicalStorageSummaryRecord:
    return canonical_storage_summary_from_payload(
        execute_json_readback(
            build_canonical_storage_summary_query_sql(
                root_path, repository_identity=repository_identity,
            ),
            psql_args=psql_args,
            psql_command=psql_command,
            label="canonical storage summary",
            expected_shape="object",
        )
    )
