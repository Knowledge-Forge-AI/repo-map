"""Ingested source query tools for the RepoMap MCP server."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from repomap_kg.server.mcp_core import (
    storage_connection as default_storage_connection,
    validate_feed_item_key,
    validate_limit,
    validate_optional_text_filter,
    validate_source_id_arg,
)
from repomap_kg.storage import (
    ingested_source_records_to_jsonable as default_ingested_source_records_to_jsonable,
    query_ingested_source_records as default_query_ingested_source_records,
    query_source_feed_item_explanation as default_query_source_feed_item_explanation,
    query_source_feed_item_records as default_query_source_feed_item_records,
    query_source_reference_records as default_query_source_reference_records,
    query_source_run_records as default_query_source_run_records,
    query_source_summary as default_query_source_summary,
    source_feed_item_records_to_jsonable as default_source_feed_item_records_to_jsonable,
    source_reference_records_to_jsonable as default_source_reference_records_to_jsonable,
    source_run_records_to_jsonable as default_source_run_records_to_jsonable,
    source_summary_to_jsonable as default_source_summary_to_jsonable,
)


@dataclass(frozen=True)
class SourceToolDependencies:
    storage_connection: Callable[..., Any] = default_storage_connection
    query_ingested_source_records: Callable[..., Any] = default_query_ingested_source_records
    ingested_source_records_to_jsonable: Callable[..., Any] = default_ingested_source_records_to_jsonable
    query_source_summary: Callable[..., Any] = default_query_source_summary
    source_summary_to_jsonable: Callable[..., Any] = default_source_summary_to_jsonable
    query_source_run_records: Callable[..., Any] = default_query_source_run_records
    source_run_records_to_jsonable: Callable[..., Any] = default_source_run_records_to_jsonable
    query_source_feed_item_records: Callable[..., Any] = default_query_source_feed_item_records
    source_feed_item_records_to_jsonable: Callable[..., Any] = default_source_feed_item_records_to_jsonable
    query_source_feed_item_explanation: Callable[..., Any] = default_query_source_feed_item_explanation
    query_source_reference_records: Callable[..., Any] = default_query_source_reference_records
    source_reference_records_to_jsonable: Callable[..., Any] = default_source_reference_records_to_jsonable


def repomap_ingested_sources(
    *,
    root_path: str | None = None,
    project: str | None = None,
    pg_database: str | None = None,
    pg_host: str | None = None,
    pg_port: str | int | None = None,
    pg_user: str | None = None,
    psql_command: str | None = None,
    source_type: str | None = None,
    policy_status: str | None = None,
    limit: int = 50,
    dependencies: SourceToolDependencies | None = None,
) -> list[dict[str, Any]]:
    deps = dependencies or SourceToolDependencies()
    connection = deps.storage_connection(
        root_path=root_path,
        project=project,
        pg_database=pg_database,
        pg_host=pg_host,
        pg_port=pg_port,
        pg_user=pg_user,
        psql_command=psql_command,
    )
    validate_optional_text_filter(source_type, "source_type")
    validate_optional_text_filter(policy_status, "policy_status")
    records = connection.query_storage(
        deps.query_ingested_source_records,
        root_path=connection.root_path,
        source_type=source_type,
        policy_status=policy_status,
        limit=validate_limit(limit),
    )
    return deps.ingested_source_records_to_jsonable(records)


def repomap_source_summary(
    *,
    source_id: str,
    root_path: str | None = None,
    project: str | None = None,
    pg_database: str | None = None,
    pg_host: str | None = None,
    pg_port: str | int | None = None,
    pg_user: str | None = None,
    psql_command: str | None = None,
    dependencies: SourceToolDependencies | None = None,
) -> dict[str, Any]:
    deps = dependencies or SourceToolDependencies()
    connection = deps.storage_connection(
        root_path=root_path,
        project=project,
        pg_database=pg_database,
        pg_host=pg_host,
        pg_port=pg_port,
        pg_user=pg_user,
        psql_command=psql_command,
    )
    valid_source_id = validate_source_id_arg(source_id)
    return deps.source_summary_to_jsonable(
        connection.query_storage(
            deps.query_source_summary,
            root_path=connection.root_path,
            source_id=valid_source_id,
        )
    )


def repomap_source_runs(
    *,
    source_id: str,
    root_path: str | None = None,
    project: str | None = None,
    pg_database: str | None = None,
    pg_host: str | None = None,
    pg_port: str | int | None = None,
    pg_user: str | None = None,
    psql_command: str | None = None,
    limit: int = 25,
    dependencies: SourceToolDependencies | None = None,
) -> list[dict[str, Any]]:
    deps = dependencies or SourceToolDependencies()
    connection = deps.storage_connection(
        root_path=root_path,
        project=project,
        pg_database=pg_database,
        pg_host=pg_host,
        pg_port=pg_port,
        pg_user=pg_user,
        psql_command=psql_command,
    )
    records = connection.query_storage(
        deps.query_source_run_records,
        root_path=connection.root_path,
        source_id=validate_source_id_arg(source_id),
        limit=validate_limit(limit),
    )
    return deps.source_run_records_to_jsonable(records)


def repomap_source_feed_items(
    *,
    source_id: str,
    root_path: str | None = None,
    project: str | None = None,
    pg_database: str | None = None,
    pg_host: str | None = None,
    pg_port: str | int | None = None,
    pg_user: str | None = None,
    psql_command: str | None = None,
    source_run_id: str | None = None,
    limit: int = 50,
    dependencies: SourceToolDependencies | None = None,
) -> list[dict[str, Any]]:
    deps = dependencies or SourceToolDependencies()
    connection = deps.storage_connection(
        root_path=root_path,
        project=project,
        pg_database=pg_database,
        pg_host=pg_host,
        pg_port=pg_port,
        pg_user=pg_user,
        psql_command=psql_command,
    )
    validate_optional_text_filter(source_run_id, "source_run_id")
    records = connection.query_storage(
        deps.query_source_feed_item_records,
        root_path=connection.root_path,
        source_id=validate_source_id_arg(source_id),
        source_run_id=source_run_id,
        limit=validate_limit(limit),
    )
    return deps.source_feed_item_records_to_jsonable(records)


def repomap_explain_source_feed_item(
    *,
    item_key: str,
    root_path: str | None = None,
    project: str | None = None,
    pg_database: str | None = None,
    pg_host: str | None = None,
    pg_port: str | int | None = None,
    pg_user: str | None = None,
    psql_command: str | None = None,
    source_id: str | None = None,
    dependencies: SourceToolDependencies | None = None,
) -> dict[str, Any]:
    deps = dependencies or SourceToolDependencies()
    connection = deps.storage_connection(
        root_path=root_path,
        project=project,
        pg_database=pg_database,
        pg_host=pg_host,
        pg_port=pg_port,
        pg_user=pg_user,
        psql_command=psql_command,
    )
    validate_feed_item_key(item_key)
    validated_source_id = (
        validate_source_id_arg(source_id) if source_id is not None else None
    )
    return connection.query_storage(
        deps.query_source_feed_item_explanation,
        root_path=connection.root_path,
        item_key=item_key,
        source_id=validated_source_id,
    )


def repomap_source_references(
    *,
    source_id: str,
    root_path: str | None = None,
    project: str | None = None,
    pg_database: str | None = None,
    pg_host: str | None = None,
    pg_port: str | int | None = None,
    pg_user: str | None = None,
    psql_command: str | None = None,
    source_run_id: str | None = None,
    target_kind: str | None = None,
    limit: int = 50,
    dependencies: SourceToolDependencies | None = None,
) -> list[dict[str, Any]]:
    deps = dependencies or SourceToolDependencies()
    connection = deps.storage_connection(
        root_path=root_path,
        project=project,
        pg_database=pg_database,
        pg_host=pg_host,
        pg_port=pg_port,
        pg_user=pg_user,
        psql_command=psql_command,
    )
    validate_optional_text_filter(source_run_id, "source_run_id")
    validate_optional_text_filter(target_kind, "target_kind")
    records = connection.query_storage(
        deps.query_source_reference_records,
        root_path=connection.root_path,
        source_id=validate_source_id_arg(source_id),
        source_run_id=source_run_id,
        target_kind=target_kind,
        limit=validate_limit(limit),
    )
    return deps.source_reference_records_to_jsonable(records)
