"""SQLite Local home configuration and the SQLite-capable registry loaders.

A home whose ``[storage] backend = "sqlite"`` parses into
:class:`LocalSqliteConfig`: the neutral registry fields of ``OpsConfig`` with
no PostgreSQL or runtime settings. PostgreSQL-only commands keep using
``load_ops_config``/``load_ops_config_home``, which refuse such a home before
deriving any PostgreSQL value. Only SQLite-capable entry points (MCP config
loading and the Local ``ops`` commands: ``sqlite-init``, ``config-check``,
``graphs``, ``refresh-preflight``, direct ``refresh-graph`` and
``refresh-enabled``) call the ``load_graph_registry_config*`` loaders, which
return either type.

One home selects one backend. Each enabled graph of a SQLite home owns one
SQLite database under the home's private control root; that file is
graph authority for the Local view only and is never a PostgreSQL mirror.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from repomap_kg.ops.config_helpers import (
    OpsConfigDiagnostic,
    unknown_top_level_diagnostics,
)
from repomap_kg.ops.config_graphs import parse_graphs_section
from repomap_kg.ops.config_loading import (
    SUPPORTED_SCHEMA_VERSION,
    build_ops_config_from_payload,
    load_ops_config,
    _read_ops_config_home_payload,
    read_toml_payload,
)
from repomap_kg.ops.config_records import (
    OpsConfig,
    OpsConfigError,
    OpsGraphConfig,
    OpsServerMemoryConfig,
    OpsServiceConfig,
    OpsSourcesConfig,
)
from repomap_kg.ops.config_sections import (
    parse_server_memory_section,
    parse_service_section,
)
from repomap_kg.ops.config_sources import parse_sources_section
from repomap_kg.ops.config_storage import (
    SQLITE_BACKEND,
    StorageBackend,
    parse_storage_section,
)
from repomap_kg.ops.resolved_config import (
    ConfiguredRepositoryIdentity,
    configured_repository_identity,
    resolve_graph_identity,
)
from repomap_kg.storage.sqlite_local.schema import LocalGraphBinding

SQLITE_GRAPH_STORE_RELATIVE = Path("state") / "sqlite-local" / "graphs"
SQLITE_GRAPH_SUFFIX = ".sqlite3"
# Public display values for a Local graph's derived database file; the
# physical path is never projected (ADR 0075).
SQLITE_DATABASE_SOURCE = "sqlite-graph-file"
SQLITE_GRAPH_DATABASE_DISPLAY = "[graph-database]"
_POSTGRES_ONLY_SECTIONS = ("postgres", "runtime")


@dataclass(frozen=True)
class LocalSqliteConfig:
    """A parsed SQLite Local home: registry fields only, no PostgreSQL."""

    config_path: str
    config_home: str | None
    config_files: tuple[str, ...]
    schema_version: int
    service: OpsServiceConfig
    graphs: tuple[OpsGraphConfig, ...]
    server_memory: OpsServerMemoryConfig
    sources: OpsSourcesConfig
    diagnostics: tuple[OpsConfigDiagnostic, ...] = ()

    @property
    def storage_backend(self) -> StorageBackend:
        return SQLITE_BACKEND

    @property
    def control_root(self) -> Path:
        return Path(self.config_home or Path(self.config_path).resolve().parent)

    @property
    def graph_store_root(self) -> Path:
        return self.control_root / SQLITE_GRAPH_STORE_RELATIVE


def sqlite_graph_database_path(config: LocalSqliteConfig, graph: OpsGraphConfig) -> Path:
    """Return the one database file owned by ``graph``; never inside a source."""
    root = config.graph_store_root.resolve()
    for binding in graph.effective_source_bindings:
        source = Path(binding.root_path_expanded).resolve()
        if root == source or root.is_relative_to(source) or source.is_relative_to(root):
            raise OpsConfigError(
                (
                    OpsConfigDiagnostic(
                        "error",
                        "sqlite-graph-store-overlaps-source",
                        f"graphs.{graph.id}",
                        "SQLite graph store must not overlap a configured source root",
                    ),
                )
            )
    return root / f"{graph.id}{SQLITE_GRAPH_SUFFIX}"


def local_graph_binding(graph: OpsGraphConfig) -> LocalGraphBinding:
    """The logical graph identity a Local database is bound to at init."""
    return LocalGraphBinding(
        graph_id=graph.id,
        repository_identity=str(configured_repository_identity(graph.id)),
        root_path=f"graph:{graph.id}",
    )


def build_local_sqlite_config_from_payload(
    payload: Mapping[str, Any],
    *,
    config_path: str,
    config_home: str | None,
    config_files: tuple[str, ...],
    diagnostics: Sequence[OpsConfigDiagnostic] = (),
) -> LocalSqliteConfig:
    collected = list(diagnostics)
    schema_version = payload.get("schema_version")
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        raise OpsConfigError(
            collected
            + [
                OpsConfigDiagnostic(
                    "error",
                    "unsupported-schema-version",
                    "schema_version",
                    f"unsupported schema_version {schema_version!r}; supported: 1",
                )
            ]
        )
    backend, storage_diagnostics = parse_storage_section(payload.get("storage"))
    collected.extend(storage_diagnostics)
    if backend != SQLITE_BACKEND:
        raise OpsConfigError(
            [
                OpsConfigDiagnostic(
                    "error",
                    "sqlite-local-home-required",
                    "storage.backend",
                    "storage.backend must be sqlite for a SQLite Local home",
                )
            ]
        )
    for section in _POSTGRES_ONLY_SECTIONS:
        if section in payload:
            collected.append(
                OpsConfigDiagnostic(
                    "error",
                    "sqlite-local-home-rejects-postgres-settings",
                    section,
                    f"{section} settings are PostgreSQL-only and are not allowed in a "
                    "SQLite Local home",
                )
            )
    service, service_diagnostics = parse_service_section(payload.get("service"))
    graphs, graph_diagnostics = parse_graphs_section(payload.get("graphs"))
    server_memory, memory_diagnostics = parse_server_memory_section(
        payload.get("server_memory")
    )
    sources, source_diagnostics = parse_sources_section(payload.get("sources", {}))
    collected.extend(service_diagnostics)
    collected.extend(graph_diagnostics)
    collected.extend(memory_diagnostics)
    collected.extend(source_diagnostics)
    identity_owners: dict[ConfiguredRepositoryIdentity, str] = {}
    for index, graph in enumerate(graphs):
        path = f"graphs[{index}]"
        if graph.database is not None:
            collected.append(
                OpsConfigDiagnostic(
                    "error",
                    "sqlite-local-graph-database-unsupported",
                    f"{path}.database",
                    "a SQLite Local graph owns one derived database file; "
                    "graph database names are PostgreSQL-only",
                )
            )
        resolve_graph_identity(
            graph, path=path, identity_owners=identity_owners, diagnostics=collected
        )
    errors = [item for item in collected if item.severity == "error"]
    if errors:
        raise OpsConfigError(errors)
    return LocalSqliteConfig(
        config_path=config_path,
        config_home=config_home,
        config_files=config_files,
        schema_version=SUPPORTED_SCHEMA_VERSION,
        service=service,
        graphs=tuple(graphs),
        server_memory=server_memory,
        sources=sources,
        diagnostics=tuple(collected),
    )


def load_graph_registry_config_home(
    config_home: str | Path | None = None,
) -> OpsConfig | LocalSqliteConfig:
    """Load a home as whichever backend it declares."""
    home, payload, files, diagnostics = _read_ops_config_home_payload(config_home)
    builder = (
        build_local_sqlite_config_from_payload
        if _declares_sqlite(payload)
        else build_ops_config_from_payload
    )
    return builder(
        payload,
        config_path=str(home),
        config_home=str(home),
        config_files=files,
        diagnostics=diagnostics,
    )


def load_graph_registry_config(
    config_path: str | Path,
) -> OpsConfig | LocalSqliteConfig:
    """Load a home directory or single TOML file as its declared backend."""
    path = Path(config_path)
    if path.is_dir():
        return load_graph_registry_config_home(path)
    if path.suffix == ".json":
        return load_ops_config(path)
    payload = read_toml_payload(path)
    if not _declares_sqlite(payload):
        return load_ops_config(path)
    return build_local_sqlite_config_from_payload(
        payload,
        config_path=str(path),
        config_home=None,
        config_files=(path.name,),
        diagnostics=unknown_top_level_diagnostics(payload),
    )


def declared_storage_backend(
    *,
    repo_map_home: str | None,
    config_path: str | None,
) -> StorageBackend | None:
    """Return the backend a home or file declares, or ``None`` if unreadable.

    Reads raw TOML only. Callers use it to route before the full parse, so
    an unreadable or PostgreSQL home falls through to the unchanged
    PostgreSQL path and its existing refusal order.
    """
    try:
        if repo_map_home or not config_path:
            _home, payload, _files, _diagnostics = _read_ops_config_home_payload(
                repo_map_home
            )
        else:
            path = Path(config_path)
            if path.is_dir():
                _home, payload, _files, _diagnostics = _read_ops_config_home_payload(path)
            elif path.suffix == ".json":
                return None
            else:
                payload = dict(read_toml_payload(path))
    except (OpsConfigError, OSError):
        return None
    return SQLITE_BACKEND if _declares_sqlite(payload) else "postgresql"


def _declares_sqlite(payload: Mapping[str, Any]) -> bool:
    storage = payload.get("storage")
    return isinstance(storage, dict) and storage.get("backend") == SQLITE_BACKEND


__all__ = (
    "LocalSqliteConfig",
    "SQLITE_DATABASE_SOURCE",
    "SQLITE_GRAPH_DATABASE_DISPLAY",
    "SQLITE_GRAPH_STORE_RELATIVE",
    "build_local_sqlite_config_from_payload",
    "declared_storage_backend",
    "load_graph_registry_config",
    "load_graph_registry_config_home",
    "local_graph_binding",
    "sqlite_graph_database_path",
)
