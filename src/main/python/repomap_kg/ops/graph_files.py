"""Bounded canonical file readback for configured local graphs."""

from __future__ import annotations

from collections.abc import Mapping

from repomap_kg.ops.config import OpsConfig, graph_database
from repomap_kg.ops.graph_file_records import (
    GRAPH_FILE_CANDIDATE_LIMIT,
    GraphFilePage,
    GraphFileRecord,
    format_graph_file_table,
    graph_file_page_to_jsonable,
    graph_file_record_from_payload,
)
from repomap_kg.ops.graph_file_sql import (
    GRAPH_FILE_DEFAULT_LIMIT,
    GRAPH_FILE_MAX_LIMIT,
    GraphFileFilters,
    build_graph_file_query_sql,
    validate_graph_file_query,
)
from repomap_kg.ops.readback import execute_ops_json_readback
from repomap_kg.ops.refresh_graphs import _find_graph
from repomap_kg.ops.reports import OpsRefreshError
from repomap_kg.storage.errors import StorageSchemaError


def query_graph_files(
    config: OpsConfig,
    graph_id: str,
    *,
    filters: GraphFileFilters,
    limit: int = GRAPH_FILE_DEFAULT_LIMIT,
    offset: int = 0,
    psql_command: str | None = None,
) -> GraphFilePage:
    graph = _find_graph(config, graph_id)
    if not graph.enabled:
        raise OpsRefreshError(f"graph {graph_id!r} is disabled")
    if graph.readback_unsupported_classification is not None:
        raise OpsRefreshError(graph.readback_unsupported_classification)
    try:
        safe_limit, safe_offset = validate_graph_file_query(
            filters,
            limit=limit,
            offset=offset,
        )
        sql = build_graph_file_query_sql(
            graph.repository_name,
            filters=filters,
            limit=safe_limit,
            offset=safe_offset,
        )
    except StorageSchemaError as error:
        raise OpsRefreshError(str(error)) from error
    try:
        payload = execute_ops_json_readback(
            config,
            database=graph_database(config, graph),
            sql=sql,
            label="operations canonical graph files",
            expected_shape="array",
            mode="host_then_container",
            psql_command=psql_command,
        )
        if not isinstance(payload, list):
            raise StorageSchemaError("operations canonical graph files readback did not return an array")
        records_list: list[GraphFileRecord] = []
        for item in payload:
            if not isinstance(item, Mapping):
                raise StorageSchemaError("operations canonical graph file item is not an object")
            records_list.append(graph_file_record_from_payload(item))
        records = tuple(records_list)
    except (StorageSchemaError, TypeError, ValueError, KeyError) as error:
        raise OpsRefreshError(
            f"graph {graph_id!r} file readback failed"
        ) from error
    return GraphFilePage(
        graph_id=graph.id,
        repository_name=graph.repository_name,
        records=records[:safe_limit],
        limit=safe_limit,
        offset=safe_offset,
        has_more=len(records) > safe_limit,
    )


__all__ = (
    "GRAPH_FILE_CANDIDATE_LIMIT",
    "GRAPH_FILE_DEFAULT_LIMIT",
    "GRAPH_FILE_MAX_LIMIT",
    "GraphFileFilters",
    "GraphFilePage",
    "GraphFileRecord",
    "OpsRefreshError",
    "build_graph_file_query_sql",
    "format_graph_file_table",
    "graph_file_page_to_jsonable",
    "graph_file_record_from_payload",
    "query_graph_files",
)
