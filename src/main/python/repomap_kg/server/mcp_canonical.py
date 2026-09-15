"""Implementation support for canonical RepoMap MCP tools."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable

from repomap_kg.server.mcp_core import private_storage_payload


@dataclass(frozen=True)
class CanonicalToolDependencies:
    """Call-time dependencies supplied by the patchable MCP facade."""

    storage_connection: Callable[..., Any]
    validate_canonical_node_args: Callable[..., str | None]
    validate_canonical_edge_args: Callable[..., None]
    validate_canonical_neighborhood_args: Callable[..., None]
    validate_identity_metadata: Callable[..., dict[str, Any]]
    validate_limit: Callable[[int], int]
    validate_offset: Callable[[int], int]
    validate_read_schema_version: Callable[[int], int]
    query_canonical_node_records: Callable[..., Any]
    query_canonical_edge_records: Callable[..., Any]
    query_canonical_edge_explanation: Callable[..., Any]
    query_canonical_neighborhood: Callable[..., Any]
    canonical_node_records_to_jsonable: Callable[..., list[dict[str, Any]]]
    canonical_edge_records_to_jsonable: Callable[..., list[dict[str, Any]]]
    canonical_edge_explanation_to_jsonable: Callable[..., dict[str, Any]]
    canonical_neighborhood_to_jsonable: Callable[..., dict[str, Any]]
    public_read_page: Callable[..., Any]
    public_read_page_to_jsonable: Callable[..., dict[str, Any]]
    public_embedded_read_result_to_jsonable: Callable[..., dict[str, Any]]
    identity_metadata_hash: Callable[[dict[str, Any]], str]


def canonical_nodes_payload(
    *,
    root_path: str | None,
    project: str | None,
    pg_database: str | None,
    pg_host: str | None,
    pg_port: str | int | None,
    pg_user: str | None,
    psql_command: str | None,
    kind: str | None,
    canonical_key: str | None,
    path_prefix: str | None,
    graph_key_version: int,
    limit: int,
    offset: int,
    result_schema_version: int,
    dependencies: CanonicalToolDependencies,
) -> dict[str, Any] | list[dict[str, Any]]:
    connection = dependencies.storage_connection(
        root_path=root_path,
        project=project,
        pg_database=pg_database,
        pg_host=pg_host,
        pg_port=pg_port,
        pg_user=pg_user,
        psql_command=psql_command,
    )
    safe_limit = dependencies.validate_limit(limit)
    safe_offset = dependencies.validate_offset(offset)
    safe_schema_version = dependencies.validate_read_schema_version(
        result_schema_version
    )
    node_kind = dependencies.validate_canonical_node_args(
        kind=kind,
        canonical_key=canonical_key,
        path_prefix=path_prefix,
        graph_key_version=graph_key_version,
    )
    records = connection.query_storage(
        dependencies.query_canonical_node_records,
        root_path=connection.root_path,
        kind=node_kind,
        canonical_key=canonical_key,
        path_prefix=path_prefix,
        graph_key_version=graph_key_version,
        limit=safe_limit + 1,
        offset=safe_offset,
    )
    page = dependencies.public_read_page(
        records,
        limit=safe_limit,
        offset=safe_offset,
    )
    payload = dependencies.public_read_page_to_jsonable(
        page,
        result_kind="canonical_nodes",
        serialize_items=dependencies.canonical_node_records_to_jsonable,
    )
    if safe_schema_version == 0:
        return private_storage_payload(
            connection,
            dependencies.canonical_node_records_to_jsonable(page.items),
        )
    return private_storage_payload(connection, payload)


def canonical_edges_payload(
    *,
    root_path: str | None,
    project: str | None,
    pg_database: str | None,
    pg_host: str | None,
    pg_port: str | int | None,
    pg_user: str | None,
    psql_command: str | None,
    kind: str | None,
    source_key: str | None,
    target_key: str | None,
    graph_key_version: int,
    limit: int,
    offset: int,
    result_schema_version: int,
    dependencies: CanonicalToolDependencies,
) -> dict[str, Any] | list[dict[str, Any]]:
    connection = dependencies.storage_connection(
        root_path=root_path,
        project=project,
        pg_database=pg_database,
        pg_host=pg_host,
        pg_port=pg_port,
        pg_user=pg_user,
        psql_command=psql_command,
    )
    safe_limit = dependencies.validate_limit(limit)
    safe_offset = dependencies.validate_offset(offset)
    safe_schema_version = dependencies.validate_read_schema_version(
        result_schema_version
    )
    dependencies.validate_canonical_edge_args(
        kind=kind,
        source_key=source_key,
        target_key=target_key,
        graph_key_version=graph_key_version,
    )
    records = connection.query_storage(
        dependencies.query_canonical_edge_records,
        root_path=connection.root_path,
        kind=kind,
        source_key=source_key,
        target_key=target_key,
        graph_key_version=graph_key_version,
        limit=safe_limit + 1,
        offset=safe_offset,
    )
    page = dependencies.public_read_page(
        records,
        limit=safe_limit,
        offset=safe_offset,
    )
    payload = dependencies.public_read_page_to_jsonable(
        page,
        result_kind="canonical_edges",
        serialize_items=dependencies.canonical_edge_records_to_jsonable,
    )
    if safe_schema_version == 0:
        return private_storage_payload(
            connection,
            dependencies.canonical_edge_records_to_jsonable(page.items),
        )
    return private_storage_payload(connection, payload)


def canonical_edge_explanation_payload(
    *,
    root_path: str | None,
    project: str | None,
    pg_database: str | None,
    pg_host: str | None,
    pg_port: str | int | None,
    pg_user: str | None,
    psql_command: str | None,
    source_key: str,
    kind: str,
    target_key: str,
    identity_metadata: dict[str, Any] | None,
    graph_key_version: int,
    evidence_limit: int,
    evidence_offset: int,
    result_schema_version: int,
    dependencies: CanonicalToolDependencies,
) -> dict[str, Any]:
    connection = dependencies.storage_connection(
        root_path=root_path,
        project=project,
        pg_database=pg_database,
        pg_host=pg_host,
        pg_port=pg_port,
        pg_user=pg_user,
        psql_command=psql_command,
    )
    dependencies.validate_canonical_edge_args(
        kind=kind,
        source_key=source_key,
        target_key=target_key,
        graph_key_version=graph_key_version,
    )
    metadata = dependencies.validate_identity_metadata(identity_metadata)
    safe_evidence_limit = dependencies.validate_limit(evidence_limit)
    safe_evidence_offset = dependencies.validate_offset(evidence_offset)
    safe_schema_version = dependencies.validate_read_schema_version(
        result_schema_version
    )
    record = connection.query_storage(
        dependencies.query_canonical_edge_explanation,
        root_path=connection.root_path,
        source_key=source_key,
        kind=kind,
        target_key=target_key,
        identity_metadata_hash=dependencies.identity_metadata_hash(metadata),
        graph_key_version=graph_key_version,
        evidence_limit=safe_evidence_limit + 1,
        evidence_offset=safe_evidence_offset,
    )
    evidence_page = dependencies.public_read_page(
        record.evidence,
        limit=safe_evidence_limit,
        offset=safe_evidence_offset,
    )
    record = replace(record, evidence=evidence_page.items)
    result = dependencies.canonical_edge_explanation_to_jsonable(record)
    payload = dependencies.public_embedded_read_result_to_jsonable(
        result,
        result_kind="canonical_edge_explanation",
        collection_pages={"evidence": evidence_page},
    )
    if safe_schema_version == 0:
        payload = result
    return private_storage_payload(connection, payload)


def canonical_neighborhood_payload(
    *,
    root_path: str | None,
    project: str | None,
    pg_database: str | None,
    pg_host: str | None,
    pg_port: str | int | None,
    pg_user: str | None,
    psql_command: str | None,
    node: str,
    direction: str,
    depth: int,
    graph_key_version: int,
    node_limit: int,
    node_offset: int,
    edge_limit: int,
    edge_offset: int,
    result_schema_version: int,
    dependencies: CanonicalToolDependencies,
) -> dict[str, Any]:
    connection = dependencies.storage_connection(
        root_path=root_path,
        project=project,
        pg_database=pg_database,
        pg_host=pg_host,
        pg_port=pg_port,
        pg_user=pg_user,
        psql_command=psql_command,
    )
    dependencies.validate_canonical_neighborhood_args(
        node=node,
        direction=direction,
        depth=depth,
        graph_key_version=graph_key_version,
    )
    safe_node_limit = dependencies.validate_limit(node_limit)
    safe_node_offset = dependencies.validate_offset(node_offset)
    safe_edge_limit = dependencies.validate_limit(edge_limit)
    safe_edge_offset = dependencies.validate_offset(edge_offset)
    safe_schema_version = dependencies.validate_read_schema_version(
        result_schema_version
    )
    record = connection.query_storage(
        dependencies.query_canonical_neighborhood,
        root_path=connection.root_path,
        node=node,
        direction=direction,
        depth=depth,
        graph_key_version=graph_key_version,
        node_limit=safe_node_limit + 1,
        node_offset=safe_node_offset,
        edge_limit=safe_edge_limit + 1,
        edge_offset=safe_edge_offset,
    )
    node_page = dependencies.public_read_page(
        record.nodes,
        limit=safe_node_limit,
        offset=safe_node_offset,
    )
    edge_page = dependencies.public_read_page(
        record.edges,
        limit=safe_edge_limit,
        offset=safe_edge_offset,
    )
    record = replace(record, nodes=node_page.items, edges=edge_page.items)
    result = dependencies.canonical_neighborhood_to_jsonable(record)
    payload = dependencies.public_embedded_read_result_to_jsonable(
        result,
        result_kind="canonical_neighborhood",
        collection_pages={"nodes": node_page, "edges": edge_page},
    )
    if safe_schema_version == 0:
        payload = result
    return private_storage_payload(connection, payload)
