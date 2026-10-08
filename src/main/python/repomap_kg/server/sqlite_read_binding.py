"""SQLite Local binding for configured-graph MCP read stores.

The backend for a neutral ``GraphSelection`` whose home declares
``[storage] backend = "sqlite"``. Graph selection and its public refusals
have already happened; each store operation opens the graph's existing
database read-only for exactly one operation (one committed snapshot) and
closes it before returning. Nothing here creates, initializes, migrates,
extracts, publishes, starts a service or falls back to PostgreSQL.

Matrix (LOCAL5): all 23 database-reading tools. The four canonical tools,
legacy status, graph status, refresh status, project summary,
node/file/observation search, the configured neighborhood, the five
language/framework summaries and the six source/feed tools. Source/feed reads
reconstruct their facts from the accepted publication
(``storage.sqlite_local.source_queries`` and ``source_feed_queries``); they
never fetch, inspect a source root or acquire an artifact. The two
configuration inventories and the two server-memory readers do not read a
graph database.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from repomap_kg.ops.config_local import (
    LocalSqliteConfig,
    local_graph_binding,
    sqlite_graph_database_path,
)
from repomap_kg.ops.config_records import OpsConfigError, OpsGraphConfig
from repomap_kg.ops.refresh_graphs import _status_from_graph
from repomap_kg.ops.report_records import OpsRefreshGraphStatus
from repomap_kg.server._ops_records import McpOpsError, checked_graph
from repomap_kg.server.canonical_read_store import (
    CanonicalEdgeExplanationQuery,
    CanonicalEdgeQuery,
    CanonicalNeighborhoodQuery,
    CanonicalNodeQuery,
)
from repomap_kg.server.graph_selection import GraphSelection
from repomap_kg.server.investigation_read_store import (
    ConfiguredNeighborhoodQuery,
    GraphRefreshStatusQuery,
    GraphSearchQuery,
    GraphSearchResult,
    LanguageSummaryQuery,
    ProjectSummaryQuery,
)
from repomap_kg.server.source_read_store import (
    IngestedSourcesQuery,
    SourceFeedItemExplanationQuery,
    SourceFeedItemsQuery,
    SourceReferencesQuery,
    SourceRunsQuery,
    SourceSummaryQuery,
)
from repomap_kg.storage.canonical_readback_rows import (
    CanonicalEdgeExplanationRecord,
    CanonicalEdgeRecord,
    CanonicalNeighborhoodRecord,
    CanonicalNodeRecord,
)
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.sqlite_local import (
    api_summary_queries,
    investigation_queries,
    nix_summary_queries,
    queries,
    source_feed_queries,
    source_queries,
    summary_queries,
)
from repomap_kg.storage.sqlite_local.connection import read_transaction
from repomap_kg.storage.sqlite_local.schema import (
    DATABASE_UNAVAILABLE,
    LocalGraphBinding,
    LocalStoreError,
)
from repomap_kg.storage.source_rows import (
    IngestedSourceRecord,
    SourceFeedItemRecord,
    SourceReferenceRecord,
    SourceRunRecord,
    SourceSummaryRecord,
)
from repomap_kg.storage.summary_rows_storage import CanonicalStorageSummaryRecord

# Not a valid PostgreSQL database name, so it can never collide with one; the
# public ``database`` display redacts it like any other storage name.
SQLITE_STORAGE_LABEL = "[sqlite-local]"
SQLITE_DATABASE_SOURCE = "sqlite-graph-file"

SUPPORTED_TOOLS = (
    "repomap_canonical_nodes",
    "repomap_canonical_edges",
    "repomap_explain_canonical_edge",
    "repomap_canonical_neighborhood",
    "repomap_status",
    "repomap_graph_status",
    "repomap_refresh_status",
    "repomap_project_summary",
    "repomap_search_nodes",
    "repomap_search_files",
    "repomap_search_observations",
    "repomap_neighborhood",
    "repomap_python_summary",
    "repomap_terraform_summary",
    "repomap_openapi_summary",
    "repomap_js_framework_summary",
    "repomap_nix_summary",
    "repomap_ingested_sources",
    "repomap_source_summary",
    "repomap_source_runs",
    "repomap_source_feed_items",
    "repomap_explain_source_feed_item",
    "repomap_source_references",
)


# Closed family set; each value is a named SQLite summary operation.
_SUMMARIES: dict[str, Callable[..., Any]] = {
    "python": summary_queries.python_summary,
    "terraform": summary_queries.terraform_summary,
    "openapi": api_summary_queries.openapi_summary,
    "js_framework": api_summary_queries.js_framework_summary,
    "nix": nix_summary_queries.nix_summary,
}


def _database(config: LocalSqliteConfig, graph: OpsGraphConfig) -> Path:
    try:
        return sqlite_graph_database_path(config, graph)
    except OpsConfigError:
        raise LocalStoreError(DATABASE_UNAVAILABLE, "graph store overlaps a source root") from None


@dataclass(frozen=True)
class SqliteCanonicalReadStore:
    path: Path
    binding: LocalGraphBinding

    def canonical_nodes(self, query: CanonicalNodeQuery) -> Sequence[CanonicalNodeRecord]:
        with read_transaction(self.path, self.binding) as connection:
            return queries.canonical_nodes(
                connection, kind=query.kind, canonical_key=query.canonical_key,
                path_prefix=query.path_prefix, graph_key_version=query.graph_key_version,
                limit=query.limit, offset=query.offset,
            )

    def canonical_edges(self, query: CanonicalEdgeQuery) -> Sequence[CanonicalEdgeRecord]:
        with read_transaction(self.path, self.binding) as connection:
            return queries.canonical_edges(
                connection, kind=query.kind, source_key=query.source_key,
                target_key=query.target_key, graph_key_version=query.graph_key_version,
                limit=query.limit, offset=query.offset,
            )

    def canonical_edge_explanation(
        self, query: CanonicalEdgeExplanationQuery
    ) -> CanonicalEdgeExplanationRecord:
        with read_transaction(self.path, self.binding) as connection:
            return queries.canonical_edge_explanation(
                connection, source_key=query.source_key, kind=query.kind,
                target_key=query.target_key,
                identity_metadata_hash=query.identity_metadata_hash,
                graph_key_version=query.graph_key_version,
                evidence_limit=query.evidence_limit, evidence_offset=query.evidence_offset,
            )

    def canonical_neighborhood(
        self, query: CanonicalNeighborhoodQuery
    ) -> CanonicalNeighborhoodRecord:
        with read_transaction(self.path, self.binding) as connection:
            return queries.canonical_neighborhood(
                connection, node=query.node, direction=query.direction, depth=query.depth,
                graph_key_version=query.graph_key_version,
                node_limit=query.node_limit, node_offset=query.node_offset,
                edge_limit=query.edge_limit, edge_offset=query.edge_offset,
            )

    def canonical_storage_summary(self) -> CanonicalStorageSummaryRecord:
        """Legacy ``repomap_status`` counts; an unpublished graph reports zeros."""
        with read_transaction(self.path, self.binding) as connection:
            return investigation_queries.storage_summary(
                connection, root_path=self.binding.root_path
            )


@dataclass(frozen=True)
class SqliteSourceReadStore:
    """Source/feed facts from the accepted publication, one snapshot per operation."""

    path: Path
    binding: LocalGraphBinding

    def ingested_sources(self, query: IngestedSourcesQuery) -> Sequence[IngestedSourceRecord]:
        with read_transaction(self.path, self.binding) as connection:
            return source_queries.ingested_sources(
                connection, source_type=query.source_type,
                policy_status=query.policy_status, limit=query.limit,
            )

    def source_summary(self, query: SourceSummaryQuery) -> SourceSummaryRecord:
        with read_transaction(self.path, self.binding) as connection:
            return source_queries.source_summary(connection, source_id=query.source_id)

    def source_runs(self, query: SourceRunsQuery) -> Sequence[SourceRunRecord]:
        with read_transaction(self.path, self.binding) as connection:
            return source_queries.source_runs(
                connection, source_id=query.source_id, limit=query.limit
            )

    def source_feed_items(self, query: SourceFeedItemsQuery) -> Sequence[SourceFeedItemRecord]:
        with read_transaction(self.path, self.binding) as connection:
            return source_feed_queries.source_feed_items(
                connection, source_id=query.source_id,
                source_run_id=query.source_run_id, limit=query.limit,
            )

    def source_feed_item_explanation(
        self, query: SourceFeedItemExplanationQuery
    ) -> dict[str, Any]:
        with read_transaction(self.path, self.binding) as connection:
            return source_feed_queries.source_feed_item_explanation(
                connection, item_key=query.item_key, source_id=query.source_id
            )

    def source_references(self, query: SourceReferencesQuery) -> Sequence[SourceReferenceRecord]:
        with read_transaction(self.path, self.binding) as connection:
            return source_feed_queries.source_references(
                connection, source_id=query.source_id, source_run_id=query.source_run_id,
                target_kind=query.target_kind, limit=query.limit,
            )


@dataclass(frozen=True)
class SqliteInvestigationReadStore:
    config: LocalSqliteConfig

    def refresh_statuses(
        self, query: GraphRefreshStatusQuery
    ) -> Mapping[str, OpsRefreshGraphStatus]:
        graphs = [
            checked_graph(self.config, graph_id, require_readback=False)
            for graph_id in query.graph_ids
        ]
        return {graph.id: self._status(graph) for graph in graphs}

    def _status(self, graph: OpsGraphConfig) -> OpsRefreshGraphStatus:
        if graph.readback_unsupported_classification is not None:
            return _status_from_graph(
                graph,
                database=SQLITE_STORAGE_LABEL,
                error=graph.readback_unsupported_classification,
            )
        try:
            with read_transaction(
                _database(self.config, graph), local_graph_binding(graph)
            ) as connection:
                fields = investigation_queries.status_fields(connection)
        except LocalStoreError as error:
            # Status reports an unusable graph as a row, like the PostgreSQL
            # owner does for a missing database, so one bad graph never fails
            # an all-visible status call.
            return _status_from_graph(
                graph,
                database=SQLITE_STORAGE_LABEL,
                db_checked=True,
                repository_exists=False,
                error=error.code,
            )
        return _status_from_graph(
            graph, database=SQLITE_STORAGE_LABEL, db_checked=True, **fields
        )

    def search(self, query: GraphSearchQuery) -> GraphSearchResult:
        graph = checked_graph(self.config, query.graph_id)
        if query.target not in {"nodes", "files", "observations"}:
            raise McpOpsError("search target must be nodes, observations, or files")
        with read_transaction(
            _database(self.config, graph), local_graph_binding(graph)
        ) as connection:
            if query.target == "observations":
                payload = investigation_queries.observation_search(
                    connection, query=query.query, kind=query.kind, path=query.path,
                    limit=query.limit, offset=query.offset, include_raw=query.include_raw,
                )
            else:
                payload = investigation_queries.search(
                    connection, target=query.target, query=query.query, kind=query.kind,
                    path=query.path, limit=query.limit, offset=query.offset,
                )
        return GraphSearchResult(
            rows=tuple(payload["results"]),
            total=int(payload["total"]),
            has_more=bool(payload["has_more"]),
        )

    def project_summary(self, query: ProjectSummaryQuery) -> CanonicalStorageSummaryRecord:
        graph = checked_graph(self.config, query.graph_id)
        binding = local_graph_binding(graph)
        with read_transaction(_database(self.config, graph), binding) as connection:
            return investigation_queries.storage_summary(connection, root_path=binding.root_path)

    def configured_neighborhood(
        self, query: ConfiguredNeighborhoodQuery
    ) -> CanonicalNeighborhoodRecord:
        """Unbounded depth-1 neighborhood, exactly the PostgreSQL configured call."""
        graph = checked_graph(self.config, query.graph_id)
        if query.direction not in {"both", "in", "out"}:
            # The PostgreSQL SQL builder's refusal, raised before any open.
            raise StorageSchemaError("neighborhood direction must be one of both, in, out")
        with read_transaction(
            _database(self.config, graph), local_graph_binding(graph)
        ) as connection:
            return queries.canonical_neighborhood(
                connection, node=query.node, direction=query.direction, depth=query.depth,
                graph_key_version=query.graph_key_version,
                node_limit=None, node_offset=0, edge_limit=None, edge_offset=0,
            )

    def language_summary(self, query: LanguageSummaryQuery) -> Any:
        read = _SUMMARIES.get(query.family)
        if read is None:
            raise McpOpsError(f"unsupported summary family: {query.family}")
        graph = checked_graph(self.config, query.graph_id)
        binding = local_graph_binding(graph)
        with read_transaction(_database(self.config, graph), binding) as connection:
            return read(connection, root_path=binding.root_path)


@dataclass(frozen=True)
class SqliteInvestigationStores:
    """Investigation binding: the SQLite adapter over one parsed Local home."""

    config: LocalSqliteConfig

    def storage_label(self, selection: GraphSelection) -> str:
        return SQLITE_STORAGE_LABEL

    def investigation_store(self) -> SqliteInvestigationReadStore:
        return SqliteInvestigationReadStore(self.config)


@dataclass(frozen=True)
class SqliteGraphStores:
    """Canonical and source binding for one Local home."""

    config: LocalSqliteConfig

    def canonical_store(self, selection: GraphSelection) -> SqliteCanonicalReadStore:
        return SqliteCanonicalReadStore(
            _database(self.config, selection.graph), local_graph_binding(selection.graph)
        )

    def source_store(self, selection: GraphSelection) -> SqliteSourceReadStore:
        return SqliteSourceReadStore(
            _database(self.config, selection.graph), local_graph_binding(selection.graph)
        )


__all__ = (
    "SQLITE_DATABASE_SOURCE",
    "SQLITE_STORAGE_LABEL",
    "SUPPORTED_TOOLS",
    "SqliteCanonicalReadStore",
    "SqliteGraphStores",
    "SqliteInvestigationReadStore",
    "SqliteInvestigationStores",
    "SqliteSourceReadStore",
)
