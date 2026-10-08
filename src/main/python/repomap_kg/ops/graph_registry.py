"""Backend-neutral view of a parsed configured-graph registry.

Both ``OpsConfig`` (PostgreSQL homes) and ``LocalSqliteConfig`` (SQLite Local
homes) satisfy :class:`GraphRegistryConfig`. Graph selection, visibility,
redaction and server-memory inventory need only these fields; backend
bindings narrow to the concrete type before touching any storage detail.
"""

from __future__ import annotations

from typing import Protocol

from repomap_kg.ops.config_records import (
    OpsGraphConfig,
    OpsServerMemoryConfig,
    OpsServiceConfig,
)


class GraphRegistryConfig(Protocol):
    @property
    def config_path(self) -> str: ...

    @property
    def config_home(self) -> str | None: ...

    @property
    def config_files(self) -> tuple[str, ...]: ...

    @property
    def schema_version(self) -> int: ...

    @property
    def service(self) -> OpsServiceConfig: ...

    @property
    def graphs(self) -> tuple[OpsGraphConfig, ...]: ...

    @property
    def server_memory(self) -> OpsServerMemoryConfig: ...


__all__ = ("GraphRegistryConfig",)
