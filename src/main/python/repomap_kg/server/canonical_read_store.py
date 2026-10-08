"""Named canonical read-store seam for the migrated MCP canonical tools.

The four canonical MCP tools (nodes, edges, edge explanation, neighborhood)
and the legacy ``repomap_status`` storage summary read through
:class:`CanonicalReadStore`. Callers supply validated filters and
a fetch window; they never supply SQL, callbacks, or commands. The
PostgreSQL production adapter is :class:`PostgresCanonicalReadStore`, which
delegates to the maintained canonical storage query owners and keeps
connection and credential selection inside the adapter; SQLite Local homes
bind ``server.sqlite_read_binding.SqliteCanonicalReadStore``.

Configured graph reads arrive as a :class:`ConfiguredPostgresConnection` from the
PostgreSQL binding, resolve the least-privilege readback authority on the
host and never fall back to a container runtime, so a stdio MCP process can
answer these tools without Docker access. Construction performs no IO.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

from repomap_kg.ops.readback import _psql_readback_error
from repomap_kg.runtime.postgres_route import readback_postgres_authority
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.rows import (
    CanonicalEdgeExplanationRecord,
    CanonicalEdgeRecord,
    CanonicalNeighborhoodRecord,
    CanonicalNodeRecord,
    CanonicalStorageSummaryRecord,
)

if TYPE_CHECKING:
    from repomap_kg.server._ops_records import McpOpsGraphContext

__all__ = (
    "CanonicalEdgeExplanationQuery",
    "CanonicalEdgeQuery",
    "CanonicalNeighborhoodQuery",
    "CanonicalNodeQuery",
    "CanonicalReadStore",
    "CanonicalStorageQueries",
    "ConfiguredPostgresConnection",
    "PostgresCanonicalReadStore",
    "ReadConnection",
    "read_configured_graph",
    "read_storage_connection",
)

_ReadT = TypeVar("_ReadT")


@dataclass(frozen=True)
class CanonicalNodeQuery:
    """Validated canonical node filters and fetch window."""

    kind: str | None
    canonical_key: str | None
    path_prefix: str | None
    graph_key_version: int
    limit: int
    offset: int


@dataclass(frozen=True)
class CanonicalEdgeQuery:
    """Validated canonical edge filters and fetch window."""

    kind: str | None
    source_key: str | None
    target_key: str | None
    graph_key_version: int
    limit: int
    offset: int


@dataclass(frozen=True)
class CanonicalEdgeExplanationQuery:
    """Validated canonical edge identity and evidence window."""

    source_key: str
    kind: str
    target_key: str
    identity_metadata_hash: str
    graph_key_version: int
    evidence_limit: int
    evidence_offset: int


@dataclass(frozen=True)
class CanonicalNeighborhoodQuery:
    """Validated neighborhood center, traversal, and node/edge windows."""

    node: str
    direction: str
    depth: int
    graph_key_version: int
    node_limit: int
    node_offset: int
    edge_limit: int
    edge_offset: int


class CanonicalReadStore(Protocol):
    """Domain read operations for one resolved graph."""

    def canonical_nodes(
        self, query: CanonicalNodeQuery
    ) -> Sequence[CanonicalNodeRecord]: ...

    def canonical_edges(
        self, query: CanonicalEdgeQuery
    ) -> Sequence[CanonicalEdgeRecord]: ...

    def canonical_edge_explanation(
        self, query: CanonicalEdgeExplanationQuery
    ) -> CanonicalEdgeExplanationRecord: ...

    def canonical_neighborhood(
        self, query: CanonicalNeighborhoodQuery
    ) -> CanonicalNeighborhoodRecord: ...

    def canonical_storage_summary(self) -> CanonicalStorageSummaryRecord: ...


class StorageConnection(Protocol):
    """Legacy/explicit MCP storage connection (``mcp_core.StorageConnection``).

    Declared structurally so this seam does not import ``mcp_core``, which
    imports the ops facade that composes the investigation read store.
    """

    @property
    def root_path(self) -> str: ...

    @property
    def psql_command(self) -> str: ...

    def psql_args(self) -> list[str]: ...


@dataclass(frozen=True)
class ConfiguredPostgresConnection:
    """PostgreSQL binding of one selected configured graph.

    Built only by ``server.postgres_read_binding``; reads through
    :func:`read_configured_graph` as the host readback authority.
    """

    context: McpOpsGraphContext


ReadConnection = StorageConnection | ConfiguredPostgresConnection


@dataclass(frozen=True)
class CanonicalStorageQueries:
    """Maintained PostgreSQL canonical query owners, bound at call time."""

    nodes: Callable[..., Sequence[CanonicalNodeRecord]]
    edges: Callable[..., Sequence[CanonicalEdgeRecord]]
    edge_explanation: Callable[..., CanonicalEdgeExplanationRecord]
    neighborhood: Callable[..., CanonicalNeighborhoodRecord]
    storage_summary: Callable[..., CanonicalStorageSummaryRecord]


@dataclass(frozen=True)
class PostgresCanonicalReadStore:
    """PostgreSQL adapter over the maintained canonical readback owners."""

    connection: ReadConnection
    queries: CanonicalStorageQueries

    def canonical_nodes(
        self, query: CanonicalNodeQuery
    ) -> Sequence[CanonicalNodeRecord]:
        return self._read(
            self.queries.nodes,
            kind=query.kind,
            canonical_key=query.canonical_key,
            path_prefix=query.path_prefix,
            graph_key_version=query.graph_key_version,
            limit=query.limit,
            offset=query.offset,
        )

    def canonical_edges(
        self, query: CanonicalEdgeQuery
    ) -> Sequence[CanonicalEdgeRecord]:
        return self._read(
            self.queries.edges,
            kind=query.kind,
            source_key=query.source_key,
            target_key=query.target_key,
            graph_key_version=query.graph_key_version,
            limit=query.limit,
            offset=query.offset,
        )

    def canonical_edge_explanation(
        self, query: CanonicalEdgeExplanationQuery
    ) -> CanonicalEdgeExplanationRecord:
        return self._read(
            self.queries.edge_explanation,
            source_key=query.source_key,
            kind=query.kind,
            target_key=query.target_key,
            identity_metadata_hash=query.identity_metadata_hash,
            graph_key_version=query.graph_key_version,
            evidence_limit=query.evidence_limit,
            evidence_offset=query.evidence_offset,
        )

    def canonical_neighborhood(
        self, query: CanonicalNeighborhoodQuery
    ) -> CanonicalNeighborhoodRecord:
        return self._read(
            self.queries.neighborhood,
            node=query.node,
            direction=query.direction,
            depth=query.depth,
            graph_key_version=query.graph_key_version,
            node_limit=query.node_limit,
            node_offset=query.node_offset,
            edge_limit=query.edge_limit,
            edge_offset=query.edge_offset,
        )

    def canonical_storage_summary(self) -> CanonicalStorageSummaryRecord:
        """Legacy ``repomap_status`` counts; the connection is the scope."""
        return self._read(self.queries.storage_summary)

    def _read(self, storage_query: Callable[..., _ReadT], **filters: Any) -> _ReadT:
        return read_storage_connection(self.connection, storage_query, **filters)


def read_storage_connection(
    connection: ReadConnection,
    storage_query: Callable[..., _ReadT],
    **filters: Any,
) -> _ReadT:
    """Run one maintained storage query for a resolved MCP connection.

    Legacy JSON projects and explicit ``pg_*`` connections keep their declared
    ambient libpq authority. Configured graph-registry connections read as the
    host readback authority through :func:`read_configured_graph`.
    """
    if isinstance(connection, ConfiguredPostgresConnection):
        context = connection.context
        return read_configured_graph(
            context, storage_query, root_path=context.root_path, **filters
        )
    return storage_query(
        connection.psql_args(),
        psql_command=connection.psql_command,
        root_path=connection.root_path,
        **filters,
    )


def read_configured_graph(
    context: McpOpsGraphContext,
    storage_query: Callable[..., _ReadT],
    *,
    root_path: str,
    **filters: Any,
) -> _ReadT:
    """Run one maintained storage query as the host readback authority.

    Shared by the canonical, investigation, and source read stores. Credentials come
    from ``readback_postgres_authority`` and stay in memory; there is no
    container fallback and no topology probing.
    """
    try:
        authority = readback_postgres_authority(context.config)
    except ValueError as error:
        raise StorageSchemaError(str(error)) from None
    password_kwargs = (
        {"password": authority.password} if authority.password is not None else {}
    )
    try:
        return storage_query(
            authority.postgres.psql_args_for_database(context.database),
            psql_command=context.psql_command or "psql",
            root_path=root_path,
            repository_identity=context.repository_identity,
            **password_kwargs,
            **filters,
        )
    except (OSError, StorageSchemaError) as error:
        raise _psql_readback_error(error) from error
