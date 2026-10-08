"""PostgreSQL binding for configured-graph MCP read stores.

The PostgreSQL production backend for a neutral ``GraphSelection`` (SQLite
Local homes bind ``server.sqlite_read_binding`` instead). The facades
(``server.ops`` for investigation, ``server.mcp`` for canonical and source)
construct these bindings with their call-time query owners; this module owns
everything PostgreSQL-specific that selection no longer carries: the client
command from ``REPOMAP_PSQL_COMMAND``, database naming via ``graph_database``,
and the :class:`McpOpsGraphContext` handed to the host readback authority.

Credentials and driver selection stay inside ``read_configured_graph`` and the
investigation owners. Bindings retain the parsed ``OpsConfig``; construction
performs no IO beyond validating the client command from the environment.
"""

from __future__ import annotations

from dataclasses import dataclass

from repomap_kg.ops.config import OpsConfig, graph_database
from repomap_kg.server._ops_records import (
    McpOpsGraphContext,
    psql_command_from_environment,
)
from repomap_kg.server.canonical_read_store import (
    CanonicalStorageQueries,
    ConfiguredPostgresConnection,
    PostgresCanonicalReadStore,
)
from repomap_kg.server.graph_selection import GraphSelection
from repomap_kg.server.investigation_read_store import (
    InvestigationStorageQueries,
    PostgresInvestigationReadStore,
)
from repomap_kg.server.source_read_store import (
    PostgresSourceReadStore,
    SourceStorageQueries,
)

__all__ = (
    "PostgresGraphStores",
    "PostgresInvestigationStores",
    "postgres_graph_stores",
    "postgres_investigation_stores",
)


@dataclass(frozen=True)
class PostgresInvestigationStores:
    """Investigation binding: the PostgreSQL adapter over one parsed config."""

    config: OpsConfig
    psql_command: str | None
    queries: InvestigationStorageQueries

    def storage_label(self, selection: GraphSelection) -> str:
        return graph_database(self.config, selection.graph)

    def investigation_store(self) -> PostgresInvestigationReadStore:
        return PostgresInvestigationReadStore(
            self.config, self.psql_command, self.queries
        )


@dataclass(frozen=True)
class PostgresGraphStores:
    """Canonical and source binding for one selected configured graph."""

    config: OpsConfig
    psql_command: str | None
    canonical_queries: CanonicalStorageQueries
    source_queries: SourceStorageQueries

    def canonical_store(self, selection: GraphSelection) -> PostgresCanonicalReadStore:
        return PostgresCanonicalReadStore(
            self._connection(selection), self.canonical_queries
        )

    def source_store(self, selection: GraphSelection) -> PostgresSourceReadStore:
        return PostgresSourceReadStore(self._connection(selection), self.source_queries)

    def _connection(self, selection: GraphSelection) -> ConfiguredPostgresConnection:
        return ConfiguredPostgresConnection(
            McpOpsGraphContext(
                config=self.config,
                graph=selection.graph,
                psql_command=self.psql_command,
            )
        )


def postgres_investigation_stores(
    config: OpsConfig,
    queries: InvestigationStorageQueries,
) -> PostgresInvestigationStores:
    return PostgresInvestigationStores(config, psql_command_from_environment(), queries)


def postgres_graph_stores(
    config: OpsConfig,
    canonical_queries: CanonicalStorageQueries,
    source_queries: SourceStorageQueries,
) -> PostgresGraphStores:
    return PostgresGraphStores(
        config, psql_command_from_environment(), canonical_queries, source_queries
    )
