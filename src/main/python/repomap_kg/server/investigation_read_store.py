"""Named investigation read-store seam for configured-graph MCP tools.

Twelve configured-graph tools (graph status, refresh status, node, file and
observation search, project summary, configured neighborhood, and the five
language/framework summaries) read through :class:`InvestigationReadStore`. Callers supply a validated graph id and named
query records; they never supply SQL, callbacks, commands, source paths,
database names, or credentials. Graph visibility, argument validation, result
serialization, redaction, and paging stay with the MCP payload owners.

Tool payload owners select the graph as a neutral ``GraphSelection`` and obtain
the store from an :class:`InvestigationStoreBinding`; they never see a database
name, client command or credential.

There are two production bindings, chosen by the home's declared storage
backend. ``server.postgres_read_binding``'s
:class:`PostgresInvestigationReadStore` re-resolves the graph inside the
adapter, delegates to the maintained PostgreSQL query owners bound at call
time, and reads as the host readback authority with no container fallback.
``server.sqlite_read_binding``'s ``SqliteInvestigationReadStore`` serves the
same twelve operations from one SQLite Local graph file through named SQLite
query owners. Construction performs no IO. The PostgreSQL query-owner records
below remain PostgreSQL-typed: database naming and the search semantics are
not neutral.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from repomap_kg.ops.config import OpsConfig, OpsGraphConfig
from repomap_kg.ops.report_records import OpsRefreshGraphStatus
from repomap_kg.server._ops_records import (
    McpOpsError,
    McpOpsGraphContext,
    checked_graph,
)
from repomap_kg.server.canonical_read_store import read_configured_graph
from repomap_kg.server.graph_selection import GraphSelection
from repomap_kg.storage.rows import (
    CanonicalNeighborhoodRecord,
    CanonicalStorageSummaryRecord,
)

__all__ = (
    "ConfiguredInvestigationGraph",
    "ConfiguredNeighborhoodQuery",
    "GraphRefreshStatusQuery",
    "GraphSearchQuery",
    "GraphSearchResult",
    "InvestigationReadStore",
    "InvestigationStoreBinding",
    "InvestigationStorageQueries",
    "LanguageSummaryFamily",
    "LanguageSummaryQueries",
    "LanguageSummaryQuery",
    "PostgresInvestigationReadStore",
    "ProjectSummaryQuery",
)

LanguageSummaryFamily = Literal["python", "terraform", "openapi", "js_framework", "nix"]


@dataclass(frozen=True)
class GraphRefreshStatusQuery:
    """Exact visible graph ids whose read-only status is requested."""

    graph_ids: tuple[str, ...]


@dataclass(frozen=True)
class GraphSearchQuery:
    """Validated search target, text, filters, and page window."""

    graph_id: str
    target: str
    query: str
    kind: str | None
    path: str | None
    limit: int
    offset: int
    include_raw: bool


@dataclass(frozen=True)
class GraphSearchResult:
    """One search page; ``total`` is ``None`` when the owner omitted it."""

    rows: tuple[Any, ...]
    total: int | None
    has_more: bool


@dataclass(frozen=True)
class ProjectSummaryQuery:
    """Configured graph whose canonical storage summary is requested."""

    graph_id: str


@dataclass(frozen=True)
class ConfiguredNeighborhoodQuery:
    """Validated neighborhood center and traversal for a configured graph."""

    graph_id: str
    node: str
    direction: str
    depth: int
    graph_key_version: int


@dataclass(frozen=True)
class LanguageSummaryQuery:
    """Configured graph and one of the five maintained summary families."""

    graph_id: str
    family: LanguageSummaryFamily


class InvestigationReadStore(Protocol):
    """Domain read operations for configured graph investigation."""

    def refresh_statuses(
        self, query: GraphRefreshStatusQuery
    ) -> Mapping[str, OpsRefreshGraphStatus]: ...

    def search(self, query: GraphSearchQuery) -> GraphSearchResult: ...

    def project_summary(
        self, query: ProjectSummaryQuery
    ) -> CanonicalStorageSummaryRecord: ...

    def configured_neighborhood(
        self, query: ConfiguredNeighborhoodQuery
    ) -> CanonicalNeighborhoodRecord: ...

    def language_summary(self, query: LanguageSummaryQuery) -> Any: ...


class InvestigationStoreBinding(Protocol):
    """Backend binding for configured investigation reads."""

    def storage_label(self, selection: GraphSelection) -> str | None:
        """Backend storage name for the existing redacted ``database`` display."""
        ...

    def investigation_store(self) -> InvestigationReadStore: ...


@dataclass(frozen=True)
class ConfiguredInvestigationGraph:
    """Neutral selection plus the backend binding that serves it."""

    selection: GraphSelection
    stores: InvestigationStoreBinding


@dataclass(frozen=True)
class LanguageSummaryQueries:
    """Maintained PostgreSQL language/framework summary owners."""

    python: Callable[..., Any]
    terraform: Callable[..., Any]
    openapi: Callable[..., Any]
    js_framework: Callable[..., Any]
    nix: Callable[..., Any]


@dataclass(frozen=True)
class InvestigationStorageQueries:
    """Maintained PostgreSQL query owners, bound at call time."""

    refresh_status: Callable[..., Mapping[str, OpsRefreshGraphStatus]]
    search: Callable[..., Mapping[str, Any]]
    storage_summary: Callable[..., CanonicalStorageSummaryRecord]
    neighborhood: Callable[..., CanonicalNeighborhoodRecord]
    language_summaries: LanguageSummaryQueries


@dataclass(frozen=True)
class PostgresInvestigationReadStore:
    """PostgreSQL adapter over the maintained investigation readback owners."""

    config: OpsConfig
    psql_command: str | None
    queries: InvestigationStorageQueries

    def refresh_statuses(
        self, query: GraphRefreshStatusQuery
    ) -> Mapping[str, OpsRefreshGraphStatus]:
        graph_ids = tuple(query.graph_ids)
        for graph_id in graph_ids:
            checked_graph(self.config, graph_id, require_readback=False)
        return self.queries.refresh_status(
            self.config,
            graph_ids=graph_ids,
            psql_command=self.psql_command,
            readback_mode="host_only",
        )

    def search(self, query: GraphSearchQuery) -> GraphSearchResult:
        context = self._context(query.graph_id)
        payload = self.queries.search(
            self.config,
            database=context.database,
            root_path=context.root_path,
            target=query.target,
            query=query.query,
            kind=query.kind,
            path=query.path,
            limit=query.limit,
            offset=query.offset,
            include_raw=query.include_raw,
            psql_command=self.psql_command,
            repository_identity=context.repository_identity,
        )
        if not isinstance(payload, Mapping):
            raise McpOpsError("MCP search readback returned an unexpected shape")
        rows: Sequence[Any] = payload.get("results", ())
        total = payload.get("total")
        return GraphSearchResult(
            rows=tuple(rows),
            total=None if total is None else int(total),
            has_more=bool(payload.get("has_more", False)),
        )

    def project_summary(
        self, query: ProjectSummaryQuery
    ) -> CanonicalStorageSummaryRecord:
        context = self._context(query.graph_id)
        return read_configured_graph(
            context, self.queries.storage_summary, root_path=context.root_path
        )

    def configured_neighborhood(
        self, query: ConfiguredNeighborhoodQuery
    ) -> CanonicalNeighborhoodRecord:
        context = self._context(query.graph_id)
        return read_configured_graph(
            context,
            self.queries.neighborhood,
            root_path=context.root_path,
            node=query.node,
            direction=query.direction,
            depth=query.depth,
            graph_key_version=query.graph_key_version,
        )

    def language_summary(self, query: LanguageSummaryQuery) -> Any:
        owners = self.queries.language_summaries
        family = query.family
        if family == "python":
            owner = owners.python
        elif family == "terraform":
            owner = owners.terraform
        elif family == "openapi":
            owner = owners.openapi
        elif family == "js_framework":
            owner = owners.js_framework
        elif family == "nix":
            owner = owners.nix
        else:
            raise McpOpsError(f"unsupported summary family: {family}")
        context = self._context(query.graph_id)
        return read_configured_graph(context, owner, root_path=context.root_path)

    def _context(self, graph_id: str) -> McpOpsGraphContext:
        graph: OpsGraphConfig = checked_graph(self.config, graph_id)
        return McpOpsGraphContext(
            config=self.config,
            graph=graph,
            psql_command=self.psql_command,
        )
