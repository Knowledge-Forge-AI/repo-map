"""Read-only SQLite Local graph-store readiness for ``config-check``/``graphs --check-db``.

One probe per configured graph, in configuration order, disabled graphs
included. A probe resolves the graph's derived database path (source-root
metadata only, never source content) and opens an existing file through the
maintained read-only reader, which ``lstat``s first and never creates a file.
It never takes the publisher lock, opens the writer, initializes, migrates,
repairs, reconciles or reads retained attempts, so a missing database stays
missing and no ``state/`` directory is created.

An exact-behind database (a known older schema version whose ledger and
physical schema are exactly that catalog prefix, LOCAL8) is ``schema-behind``
with its accepted generation and ``error=graph-database-schema-behind``; only
``ops sqlite-upgrade`` changes it. Drift and future schemas stay
``unrecognized``.

As with every Local read, SQLite may create or keep an existing WAL database's
own ``-wal``/``-shm`` sidecars; the main database bytes are unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from repomap_kg.ops.config_local import (
    LocalSqliteConfig,
    local_graph_binding,
    sqlite_graph_database_path,
)
from repomap_kg.ops.config_records import OpsConfigError, OpsGraphConfig
from repomap_kg.storage.sqlite_local.connection import read_transaction
from repomap_kg.storage.sqlite_local.migrations import classify
from repomap_kg.storage.sqlite_local.schema import (
    GRAPH_MISMATCH,
    NOT_INITIALIZED,
    SCHEMA_BEHIND,
    SCHEMA_DRIFT,
    SCHEMA_UNSUPPORTED,
    UNRECOGNIZED,
    LocalStoreError,
    accepted_identity,
)

NOT_INITIALIZED_STATE = "not-initialized"
CURRENT_STATE = "current"
UNRECOGNIZED_STATE = "unrecognized"
UNAVAILABLE_STATE = "unavailable"
INVALID_CONFIGURATION_STATE = "invalid-configuration"
SCHEMA_BEHIND_STATE = "schema-behind"
READINESS_STATES = (
    NOT_INITIALIZED_STATE,
    CURRENT_STATE,
    UNRECOGNIZED_STATE,
    UNAVAILABLE_STATE,
    INVALID_CONFIGURATION_STATE,
    SCHEMA_BEHIND_STATE,
)
STORE_OVERLAPS_SOURCE = "sqlite-graph-store-overlaps-source"
_UNRECOGNIZED_CODES = frozenset({UNRECOGNIZED, SCHEMA_DRIFT, SCHEMA_UNSUPPORTED, GRAPH_MISMATCH})


@dataclass(frozen=True)
class LocalGraphReadiness:
    """One graph's store state; ``error`` is a bounded code, never a path or SQL."""

    graph_id: str
    state: str
    accepted_generation: int | None = None
    error: str | None = None

    @property
    def published(self) -> bool:
        return self.accepted_generation is not None

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "state": self.state,
            "published": self.published,
            "accepted_generation": self.accepted_generation,
            "error": self.error,
        }


def probe_local_graph(config: LocalSqliteConfig, graph: OpsGraphConfig) -> LocalGraphReadiness:
    """Classify one graph's database without creating or changing anything."""
    try:
        path = sqlite_graph_database_path(config, graph)
    except OpsConfigError:
        return LocalGraphReadiness(
            graph.id, INVALID_CONFIGURATION_STATE, error=STORE_OVERLAPS_SOURCE
        )
    try:
        with read_transaction(path, local_graph_binding(graph), accept_behind=True) as connection:
            behind = classify(connection).kind == "behind"
            accepted = accepted_identity(connection)
    except LocalStoreError as error:
        return LocalGraphReadiness(graph.id, _state_for(error.code), error=error.code)
    return LocalGraphReadiness(
        graph.id,
        SCHEMA_BEHIND_STATE if behind else CURRENT_STATE,
        accepted_generation=None if accepted is None else accepted.generation,
        error=SCHEMA_BEHIND if behind else None,
    )


def probe_local_graphs(config: LocalSqliteConfig) -> tuple[LocalGraphReadiness, ...]:
    """Probe every configured graph in configuration order."""
    return tuple(probe_local_graph(config, graph) for graph in config.graphs)


def _state_for(code: str) -> str:
    if code == NOT_INITIALIZED:
        return NOT_INITIALIZED_STATE
    if code in _UNRECOGNIZED_CODES:
        return UNRECOGNIZED_STATE
    return UNAVAILABLE_STATE


__all__ = (
    "CURRENT_STATE",
    "INVALID_CONFIGURATION_STATE",
    "LocalGraphReadiness",
    "NOT_INITIALIZED_STATE",
    "READINESS_STATES",
    "SCHEMA_BEHIND_STATE",
    "UNAVAILABLE_STATE",
    "UNRECOGNIZED_STATE",
    "probe_local_graph",
    "probe_local_graphs",
)
