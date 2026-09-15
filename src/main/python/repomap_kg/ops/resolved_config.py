"""Pure resolved database and configured repository authority."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import NewType

from repomap_kg.graph.multi_source import (
    GraphSourceBinding,
    MultiSourceIdentityError,
    multi_source_configuration_id,
)
from repomap_kg.ops.config_records import (
    OpsConfig,
    OpsConfigDiagnostic,
    OpsConfigError,
    OpsGraphConfig,
)

DatabaseName = NewType("DatabaseName", str)
ConfiguredRepositoryIdentity = NewType("ConfiguredRepositoryIdentity", str)

MAINTENANCE_DATABASE = DatabaseName("postgres")
RESERVED_DATABASES = frozenset({"postgres", "template0", "template1"})
_DATABASE_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,62}\Z")


@dataclass(frozen=True)
class ResolvedGraphConfig:
    """One graph with explicit database and relocation-stable identity."""

    source: OpsGraphConfig
    database: DatabaseName
    repository_identity: ConfiguredRepositoryIdentity
    bindings: tuple[GraphSourceBinding, ...]
    configuration_identity: str

    @property
    def graph_id(self) -> str:
        return self.source.id


@dataclass(frozen=True)
class ResolvedOpsConfig:
    """Collision-free graph, control, and maintenance database topology."""

    source: OpsConfig
    default_database: DatabaseName
    control_database: DatabaseName
    maintenance_database: DatabaseName
    graphs: tuple[ResolvedGraphConfig, ...]
    owned_databases: tuple[DatabaseName, ...]

    def graph(self, graph_id: str) -> ResolvedGraphConfig:
        for graph in self.graphs:
            if graph.graph_id == graph_id:
                return graph
        raise KeyError(graph_id)


def configured_repository_identity(graph_id: str) -> ConfiguredRepositoryIdentity:
    """Return the versioned identity independent of mutable source location."""

    return ConfiguredRepositoryIdentity(f"repo1:{graph_id}")


def control_database_for(default_database: str) -> DatabaseName:
    """Derive the dedicated control target from the configured default."""

    value = f"{default_database}_control"
    if not _DATABASE_PATTERN.fullmatch(value):
        raise ValueError("control database target is invalid")
    return DatabaseName(value)


def resolve_ops_config(config: OpsConfig) -> ResolvedOpsConfig:
    """Resolve and validate the complete database and repository topology."""

    diagnostics: list[OpsConfigDiagnostic] = []
    default_database = _database_name(
        config.postgres.database,
        path="postgres.database",
        diagnostics=diagnostics,
    )
    if default_database in RESERVED_DATABASES:
        diagnostics.append(
            _error(
                "reserved-default-graph-database",
                "postgres.database",
                "global graph database target is reserved for maintenance or templates",
            )
        )
    try:
        control_database = control_database_for(default_database)
    except ValueError:
        diagnostics.append(
            _error(
                "invalid-control-database",
                "postgres.database",
                "derived control database target is invalid",
            )
        )
        control_database = DatabaseName("")

    resolved_graphs: list[ResolvedGraphConfig] = []
    database_owners: dict[DatabaseName, str] = {}
    identity_owners: dict[ConfiguredRepositoryIdentity, str] = {}
    for index, graph in enumerate(config.graphs):
        path = f"graphs[{index}]"
        database = _database_name(
            graph.database or default_database,
            path=f"{path}.database",
            diagnostics=diagnostics,
        )
        if database in RESERVED_DATABASES:
            diagnostics.append(
                _error(
                    "reserved-graph-database",
                    f"{path}.database",
                    "graph database target is reserved for maintenance or templates",
                )
            )
        prior_graph = database_owners.get(database)
        if prior_graph is not None:
            diagnostics.append(
                _error(
                    "duplicate-effective-graph-database",
                    f"{path}.database",
                    "duplicate effective graph database is not allowed",
                )
            )
        else:
            database_owners[database] = graph.id

        identity = configured_repository_identity(graph.id)
        prior_identity = identity_owners.get(identity)
        if prior_identity is not None:
            diagnostics.append(
                _error(
                    "duplicate-configured-repository-identity",
                    f"{path}.id",
                    "configured repository identity collision is not allowed",
                )
            )
        else:
            identity_owners[identity] = graph.id
        try:
            bindings = tuple(
                item.domain_binding(graph.id) for item in graph.effective_source_bindings
            )
            config_id = multi_source_configuration_id(graph.id, bindings)
        except MultiSourceIdentityError as error:
            diagnostics.append(
                _error(
                    "invalid-source-binding-identity",
                    f"{path}.source_bindings" if graph.explicit_source_bindings else path,
                    str(error),
                )
            )
            bindings = ()
            config_id = ""
        resolved_graphs.append(
            ResolvedGraphConfig(
                graph,
                database,
                identity,
                bindings,
                config_id,
            )
        )

    if control_database in RESERVED_DATABASES or control_database in database_owners:
        diagnostics.append(
            _error(
                "control-database-collision",
                "postgres.database",
                "control database target must be distinct from graph and maintenance targets",
            )
        )
    if diagnostics:
        raise OpsConfigError(diagnostics)

    owned = tuple(sorted((*database_owners, control_database)))
    return ResolvedOpsConfig(
        source=config,
        default_database=default_database,
        control_database=control_database,
        maintenance_database=MAINTENANCE_DATABASE,
        graphs=tuple(resolved_graphs),
        owned_databases=owned,
    )


def _database_name(
    value: str,
    *,
    path: str,
    diagnostics: list[OpsConfigDiagnostic],
) -> DatabaseName:
    if not _DATABASE_PATTERN.fullmatch(value):
        diagnostics.append(
            _error(
                "invalid-database-target",
                path,
                "database target must be a safe PostgreSQL identifier",
            )
        )
    return DatabaseName(value)


def _error(code: str, path: str, message: str) -> OpsConfigDiagnostic:
    return OpsConfigDiagnostic("error", code, path, message)


__all__ = [
    "ConfiguredRepositoryIdentity",
    "DatabaseName",
    "MAINTENANCE_DATABASE",
    "RESERVED_DATABASES",
    "ResolvedGraphConfig",
    "ResolvedOpsConfig",
    "configured_repository_identity",
    "control_database_for",
    "resolve_ops_config",
]
