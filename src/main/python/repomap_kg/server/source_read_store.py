"""Named source read-store seam for the ingested-source MCP tools.

The six ingested-source/feed tools (ingested sources, source summary, source
runs, feed items, feed item explanation, and source references) read through
:class:`SourceReadStore`. Callers supply named request records carrying the
validated identifiers and filters those tools already accept; they never supply
SQL, callbacks, commands, source paths, or credentials. Argument validation and
result serialization stay with the MCP tool owners.

Two production adapters implement it. :class:`PostgresSourceReadStore`
delegates to the maintained source readback owners bound at call time.
Configured graph-registry connections (bound by ``server.postgres_read_binding``)
read as the host readback authority with no container fallback; legacy JSON
projects and explicit ``pg_*`` connections keep their declared authority.
SQLite Local homes bind ``server.sqlite_read_binding.SqliteSourceReadStore``,
which reads the same facts from the graph's accepted publication in one
read-only snapshot per operation. Construction performs no IO, and neither
adapter inspects or acquires sources.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from repomap_kg.server.canonical_read_store import (
    ReadConnection,
    read_storage_connection,
)
from repomap_kg.storage.source_rows import (
    IngestedSourceRecord,
    SourceFeedItemRecord,
    SourceReferenceRecord,
    SourceRunRecord,
    SourceSummaryRecord,
)

__all__ = (
    "IngestedSourcesQuery",
    "PostgresSourceReadStore",
    "SourceFeedItemExplanationQuery",
    "SourceFeedItemsQuery",
    "SourceReadStore",
    "SourceReferencesQuery",
    "SourceRunsQuery",
    "SourceStorageQueries",
    "SourceSummaryQuery",
)


@dataclass(frozen=True)
class IngestedSourcesQuery:
    """Validated ingested-source filters and row limit."""

    source_type: str | None
    policy_status: str | None
    limit: int


@dataclass(frozen=True)
class SourceSummaryQuery:
    """Validated source identity whose summary is requested."""

    source_id: str


@dataclass(frozen=True)
class SourceRunsQuery:
    """Validated source identity and run row limit."""

    source_id: str
    limit: int


@dataclass(frozen=True)
class SourceFeedItemsQuery:
    """Validated source identity, optional run filter, and row limit."""

    source_id: str
    source_run_id: str | None
    limit: int


@dataclass(frozen=True)
class SourceFeedItemExplanationQuery:
    """Validated feed item key and optional source identity."""

    item_key: str
    source_id: str | None


@dataclass(frozen=True)
class SourceReferencesQuery:
    """Validated source identity, optional run and target filters, and limit."""

    source_id: str
    source_run_id: str | None
    target_kind: str | None
    limit: int


class SourceReadStore(Protocol):
    """Domain read operations over published ingested-source records."""

    def ingested_sources(
        self, query: IngestedSourcesQuery
    ) -> Sequence[IngestedSourceRecord]: ...

    def source_summary(self, query: SourceSummaryQuery) -> SourceSummaryRecord: ...

    def source_runs(self, query: SourceRunsQuery) -> Sequence[SourceRunRecord]: ...

    def source_feed_items(
        self, query: SourceFeedItemsQuery
    ) -> Sequence[SourceFeedItemRecord]: ...

    def source_feed_item_explanation(
        self, query: SourceFeedItemExplanationQuery
    ) -> dict[str, Any]: ...

    def source_references(
        self, query: SourceReferencesQuery
    ) -> Sequence[SourceReferenceRecord]: ...


@dataclass(frozen=True)
class SourceStorageQueries:
    """Maintained PostgreSQL source readback owners, bound at call time."""

    ingested_sources: Callable[..., Sequence[IngestedSourceRecord]]
    summary: Callable[..., SourceSummaryRecord]
    runs: Callable[..., Sequence[SourceRunRecord]]
    feed_items: Callable[..., Sequence[SourceFeedItemRecord]]
    feed_item_explanation: Callable[..., dict[str, Any]]
    references: Callable[..., Sequence[SourceReferenceRecord]]


@dataclass(frozen=True)
class PostgresSourceReadStore:
    """PostgreSQL adapter over the maintained source readback owners."""

    connection: ReadConnection
    queries: SourceStorageQueries

    def ingested_sources(
        self, query: IngestedSourcesQuery
    ) -> Sequence[IngestedSourceRecord]:
        return read_storage_connection(
            self.connection,
            self.queries.ingested_sources,
            source_type=query.source_type,
            policy_status=query.policy_status,
            limit=query.limit,
        )

    def source_summary(self, query: SourceSummaryQuery) -> SourceSummaryRecord:
        return read_storage_connection(
            self.connection, self.queries.summary, source_id=query.source_id
        )

    def source_runs(self, query: SourceRunsQuery) -> Sequence[SourceRunRecord]:
        return read_storage_connection(
            self.connection,
            self.queries.runs,
            source_id=query.source_id,
            limit=query.limit,
        )

    def source_feed_items(
        self, query: SourceFeedItemsQuery
    ) -> Sequence[SourceFeedItemRecord]:
        return read_storage_connection(
            self.connection,
            self.queries.feed_items,
            source_id=query.source_id,
            source_run_id=query.source_run_id,
            limit=query.limit,
        )

    def source_feed_item_explanation(
        self, query: SourceFeedItemExplanationQuery
    ) -> dict[str, Any]:
        return read_storage_connection(
            self.connection,
            self.queries.feed_item_explanation,
            item_key=query.item_key,
            source_id=query.source_id,
        )

    def source_references(
        self, query: SourceReferencesQuery
    ) -> Sequence[SourceReferenceRecord]:
        return read_storage_connection(
            self.connection,
            self.queries.references,
            source_id=query.source_id,
            source_run_id=query.source_run_id,
            target_kind=query.target_kind,
            limit=query.limit,
        )
