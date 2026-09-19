"""Source observation readback query orchestration."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.readback_driver import execute_json_readback
from repomap_kg.storage.source_rows import (
    IngestedSourceRecord,
    SourceFeedItemRecord,
    SourceReferenceRecord,
    SourceRunRecord,
    SourceSummaryRecord,
    ingested_source_record_from_storage_payload,
    source_feed_item_record_from_storage_payload,
    source_reference_record_from_storage_payload,
    source_run_record_from_storage_payload,
    source_summary_from_storage_payload,
)
from repomap_kg.storage.sql_sources import (
    build_ingested_source_query_sql,
    build_source_feed_item_explanation_query_sql,
    build_source_feed_item_query_sql,
    build_source_reference_query_sql,
    build_source_run_query_sql,
    build_source_summary_query_sql,
)

__all__ = (
    "query_ingested_source_records",
    "query_source_summary",
    "query_source_run_records",
    "query_source_feed_item_records",
    "query_source_reference_records",
    "query_source_feed_item_explanation",
)


def query_ingested_source_records(
    psql_args: Sequence[str],
    *,
    root_path: str,
    source_type: str | None = None,
    policy_status: str | None = None,
    limit: int = 50,
    repository_identity: str | None = None,
    psql_command: str = "psql",
) -> tuple[IngestedSourceRecord, ...]:
    payload = execute_json_readback(
        build_ingested_source_query_sql(
            root_path,
            source_type=source_type,
            policy_status=policy_status,
            limit=limit,
            repository_identity=repository_identity,
        ),
        psql_args=psql_args,
        psql_command=psql_command,
        label="ingested source records",
        expected_shape="array",
    )
    return tuple(ingested_source_record_from_storage_payload(item) for item in payload)


def query_source_summary(
    psql_args: Sequence[str],
    *,
    root_path: str,
    source_id: str,
    repository_identity: str | None = None,
    psql_command: str = "psql",
) -> SourceSummaryRecord:
    payload = execute_json_readback(
        build_source_summary_query_sql(
            root_path,
            source_id=source_id,
            repository_identity=repository_identity,
        ),
        psql_args=psql_args,
        psql_command=psql_command,
        label="source summary",
        expected_shape="object",
    )
    return source_summary_from_storage_payload(payload)


def query_source_run_records(
    psql_args: Sequence[str],
    *,
    root_path: str,
    source_id: str,
    limit: int = 25,
    repository_identity: str | None = None,
    psql_command: str = "psql",
) -> tuple[SourceRunRecord, ...]:
    payload = execute_json_readback(
        build_source_run_query_sql(
            root_path,
            source_id=source_id,
            limit=limit,
            repository_identity=repository_identity,
        ),
        psql_args=psql_args,
        psql_command=psql_command,
        label="source run records",
        expected_shape="array",
    )
    return tuple(source_run_record_from_storage_payload(item) for item in payload)


def query_source_feed_item_records(
    psql_args: Sequence[str],
    *,
    root_path: str,
    source_id: str,
    source_run_id: str | None = None,
    limit: int = 50,
    repository_identity: str | None = None,
    psql_command: str = "psql",
) -> tuple[SourceFeedItemRecord, ...]:
    payload = execute_json_readback(
        build_source_feed_item_query_sql(
            root_path,
            source_id=source_id,
            source_run_id=source_run_id,
            limit=limit,
            repository_identity=repository_identity,
        ),
        psql_args=psql_args,
        psql_command=psql_command,
        label="source feed item records",
        expected_shape="array",
    )
    return tuple(source_feed_item_record_from_storage_payload(item) for item in payload)


def query_source_reference_records(
    psql_args: Sequence[str],
    *,
    root_path: str,
    source_id: str,
    source_run_id: str | None = None,
    target_kind: str | None = None,
    limit: int = 50,
    repository_identity: str | None = None,
    psql_command: str = "psql",
) -> tuple[SourceReferenceRecord, ...]:
    payload = execute_json_readback(
        build_source_reference_query_sql(
            root_path,
            source_id=source_id,
            source_run_id=source_run_id,
            target_kind=target_kind,
            limit=limit,
            repository_identity=repository_identity,
        ),
        psql_args=psql_args,
        psql_command=psql_command,
        label="source reference records",
        expected_shape="array",
    )
    return tuple(source_reference_record_from_storage_payload(item) for item in payload)


def query_source_feed_item_explanation(
    psql_args: Sequence[str],
    *,
    root_path: str,
    item_key: str,
    source_id: str | None = None,
    repository_identity: str | None = None,
    psql_command: str = "psql",
) -> dict[str, Any]:
    payload = execute_json_readback(
        build_source_feed_item_explanation_query_sql(
            root_path,
            item_key=item_key,
            source_id=source_id,
            repository_identity=repository_identity,
        ),
        psql_args=psql_args,
        psql_command=psql_command,
        label="source feed item explanation",
        expected_shape="object",
    )
    if not isinstance(payload, dict):
        raise StorageSchemaError("source feed item explanation payload must be a JSON object")
    return payload
